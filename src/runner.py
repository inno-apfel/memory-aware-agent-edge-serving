"""Execute multi-step agent tasks under a FIFO model-request concurrency cap.

The scheduler owns task readiness and history; :mod:`src.transport` owns HTTP.
Tasks become ready at their arrival offset or after a tool delay. The cap applies
only to in-flight model requests, so a task waiting on a simulated tool does not
occupy a model slot. JSONL artifacts are written as the run progresses.
"""

import heapq
import itertools
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from src.client import send_request

GENERATION_FIELDS = {
    "chat_template_kwargs",
    "reasoning_budget_tokens",
    "response_format",
}


def integer_answer(step, text):
    """Return an answer as text in the format declared by ``step``.

    For ``json_integer``, accept exactly ``{"answer": <int>}``; booleans,
    floats, extra keys, and stringified integers are rejected. Other steps use
    trimmed response text unchanged.
    """
    if step.get("answer_format") == "json_integer":
        value = json.loads(text)
        if (
            not isinstance(value, dict)
            or set(value) != {"answer"}
            or type(value["answer"]) is not int
        ):
            raise ValueError("Expected exactly one integer answer field")
        return str(value["answer"])
    return text.strip()


def validate(step, text):
    """Check a model response against one workload step's quality rule.

    Steps with ``expected`` use exact answer comparison. Prose steps use
    ``min_words`` and ``suffix``. This is a structural quality check, not a
    semantic assessment of generated prose.
    """
    text = text.strip()
    if "expected" in step:
        try:
            return integer_answer(step, text) == step["expected"]
        except (ValueError, TypeError):
            return False
    return (
        bool(text)
        and len(text.split()) >= step.get("min_words", 0)
        and text.endswith(step.get("suffix", ""))
    )


def _write_timeline(output, origin):
    # Writes the scheduler clock origin to output/timeline.json.
    (output / "timeline.json").write_text(
        json.dumps(dict(origin_monotonic=origin, origin_wall=time.time()))
    )


def _emit_event(events, run_id, origin, kind, state, **extra):
    # Writes one timestamped event to output/events.jsonl.
    events.write(
        json.dumps(
            dict(
                run_id=run_id,
                event=kind,
                task_id=state["task"]["task_id"],
                step_id=state["step"],
                t=time.perf_counter() - origin,
                **extra,
            )
        )
        + "\n"
    )
    events.flush()


def _arrive(state, now, events, run_id, origin):
    """Mark the task's first injection and record its scheduled arrival."""
    state.update(arrived=True, injected=now)
    _emit_event(
        events,
        run_id,
        origin,
        "arrival",
        state,
        scheduled=state["task"]["arrival_offset_s"],
    )


def _finish_task(state, status, rows, taskfile, events, run_id, origin):
    # Writes the terminal row to tasks.jsonl and task_end to events.jsonl.
    row = dict(
        run_id=run_id,
        task_id=state["task"]["task_id"],
        task_type=state["task"]["task_type"],
        status=status,
        quality_pass=status == "completed",
        arrival=state["task"]["arrival_offset_s"],
        injected=state["injected"],
        end=time.perf_counter() - origin,
        queue_s=state["queue_s"],
        tool_wait_s=state["tool_wait_s"],
        steps_completed=state["steps_completed"],
    )
    row["latency_s"] = row["end"] - row["arrival"]
    rows.append(row)
    taskfile.write(json.dumps(row) + "\n")
    taskfile.flush()
    _emit_event(events, run_id, origin, "task_end", state, status=status)


def _invoke(sender, url, body, timeout, origin):
    """Call the sender and convert unexpected exceptions into error results."""
    dispatch = time.perf_counter() - origin
    try:
        result = sender(url, body, timeout=timeout)
    except Exception as exc:
        result = dict(status="error", error=repr(exc), response_text="")
    return dispatch, time.perf_counter() - origin, result


def _write_request(
    reqs, events, run_id, origin, state, ready_at, dispatch, end, body, result
):
    # Writes the completed request to output/requests.jsonl and events.jsonl.
    reqs.write(
        json.dumps(
            dict(
                run_id=run_id,
                task_id=state["task"]["task_id"],
                step_id=state["step"],
                ready=ready_at,
                dispatch=dispatch,
                end=end,
                queue_s=dispatch - ready_at,
                body=body,
                **result,
            )
        )
        + "\n"
    )
    reqs.flush()
    _emit_event(
        events,
        run_id,
        origin,
        "request_end",
        state,
        request_end=end,
        status=result["status"],
    )


def _build_request_body(state, step):
    """Build the model request for the task's current step."""
    prompt = step["prompt"]
    if "{tool_result}" in prompt:
        prompt = prompt.replace("{tool_result}", str(state["tool_result"]))
    body = dict(
        messages=state["history"] + [dict(role="user", content=prompt)],
        max_tokens=step["max_tokens"],
        stream=True,
        temperature=0,
        seed=42,
        cache_prompt=False,
        stream_options={"include_usage": True},
        chat_template_kwargs={"enable_thinking": False},
    )
    body.update(step.get("generation", {}))
    return body


def run_tasks(tasks, concurrency, output, url, timeout=30, sender=send_request):
    """Run tasks and return ``(task_rows, elapsed_seconds)``.

    ``tasks`` is a sequence of mappings with unique ``task_id``, ``task_type``,
    nonnegative ``arrival_offset_s``, and a nonempty ``steps`` list. Each step
    has ``prompt`` and positive ``max_tokens``; optional fields include
    ``expected``/``answer_format``, ``generation``, ``tool_delay_s``, and
    ``tool_add``. ``initial_messages`` seeds a task's conversation history.

    A min-heap orders ready work by scheduled time and insertion sequence. At
    most ``concurrency`` calls are in flight. A successful step appends the
    actual assistant response to history; optional local tool arithmetic uses
    that response, then the next step becomes ready after its delay. Failed or
    invalid responses end the task without retrying. ``sender`` is injectable
    for deterministic scheduler tests and must return a mapping containing
    ``status`` and, on success, ``response_text``.

    Args:
        tasks: Workload tasks, normally from ``workloads.generate`` or JSONL.
        concurrency: Maximum number of simultaneous model requests.
        output: Directory for timeline, event, request, and task JSONL files.
        url: Completion endpoint forwarded to the sender. The experiment CLI
            resolves it from ``config.yml`` unless ``--url`` is supplied.
        timeout: Per-request connect/read inactivity timeout in seconds.
        sender: Callable that accepts request body plus ``timeout`` and ``url``.

    Returns:
        A list of task result rows and total scheduler wall time in seconds.

    Raises:
        ValueError: For invalid run parameters, duplicate IDs, malformed tasks,
            or unsupported generation parameters.
    """
    # Validate Inputs
    if concurrency < 1 or timeout <= 0 or not tasks:
        raise ValueError("Invalid run parameters")
    if len({t["task_id"] for t in tasks}) != len(tasks):
        raise ValueError("Duplicate IDs")
    for t in tasks:
        if t["arrival_offset_s"] < 0 or not t["steps"]:
            raise ValueError("Invalid task")
        for s in t["steps"]:
            if s.get("tool_delay_s", 0) < 0 or s["max_tokens"] < 1:
                raise ValueError("Invalid step")
            if set(s.get("generation", {})) - GENERATION_FIELDS:
                raise ValueError("Unsupported generation parameters")


    # Setup
    # Create the run clock, scheduler state, and append-only artifacts. The
    # timeline origin lets downstream analysis align scheduler and monitor data.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    origin = time.perf_counter()
    seq = itertools.count()
    ready = []
    inflight = {}
    rows = []
    states = []
    _write_timeline(output, origin)
    events = (output / "events.jsonl").open("w", encoding="utf-8")
    reqs = (output / "requests.jsonl").open("w", encoding="utf-8")
    taskfile = (output / "tasks.jsonl").open("w", encoding="utf-8")

    # Add all tasks to heap, FIFO queue will pull them based on arrival_offset_s
    for task in tasks:
        st = dict(
            task=task,
            step=0,
            history=list(task.get("initial_messages", [])),
            queue_s=0.0,
            tool_wait_s=0.0,
            arrived=False,
            steps_completed=0,
        )
        states.append(st)
        heapq.heappush(ready, (task["arrival_offset_s"], next(seq), st))

    # Process all task/request states until workload is finished
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while ready or inflight:
                # Record tasks whose scheduled arrival has occurred.
                now = time.perf_counter() - origin
                for st in states:
                    if not st["arrived"] and st["task"]["arrival_offset_s"] <= now:
                        _arrive(st, now, events, output.name, origin)


                # Process Inflight Requests
                for future in list(inflight):
                    if not future.done():
                        continue
                    st, ready_at, body = inflight.pop(future)
                    dispatch, end, result = future.result()
                    st["queue_s"] += dispatch - ready_at
                    _write_request(
                        reqs,
                        events,
                        output.name,
                        origin,
                        st,
                        ready_at,
                        dispatch,
                        end,
                        body,
                        result,
                    )
                    step = st["task"]["steps"][st["step"]]
                    if result["status"] != "ok":
                        _finish_task(
                            st,
                            result["status"],
                            rows,
                            taskfile,
                            events,
                            output.name,
                            origin,
                        )
                        continue
                    if not validate(step, result["response_text"]):
                        _finish_task(
                            st,
                            "validation_failed",
                            rows,
                            taskfile,
                            events,
                            output.name,
                            origin,
                        )
                        continue
                    st["steps_completed"] += 1
                    st["history"] = body["messages"] + [
                        dict(role="assistant", content=result["response_text"])
                    ]
                    st["step"] += 1
                    if st["step"] == len(st["task"]["steps"]):
                        _finish_task(
                            st,
                            "completed",
                            rows,
                            taskfile,
                            events,
                            output.name,
                            origin,
                        )
                        continue
                    delay = step.get("tool_delay_s", 0)
                    tool_start = time.perf_counter() - origin
                    st["tool_wait_s"] += delay
                    if "tool_add" in step:
                        value = (
                            int(integer_answer(step, result["response_text"]))
                            + step["tool_add"]
                        )
                        st["tool_result"] = value
                        st["history"].append(
                            dict(role="user", content=f"Tool result: {value}")
                        )
                    next_ready = tool_start + delay
                    _emit_event(
                        events,
                        output.name,
                        origin,
                        "tool_wait",
                        st,
                        tool_start=tool_start, tool_end=next_ready,
                    )
                    heapq.heappush(ready, (next_ready, next(seq), st))

                # Process Ready Requests if slots open up
                now = time.perf_counter() - origin
                while ready and ready[0][0] <= now and len(inflight) < concurrency:
                    ready_at, order, st = heapq.heappop(ready)
                    if not st["arrived"]:
                        _arrive(st, now, events, output.name, origin)
                    _emit_event(
                        events,
                        output.name,
                        origin,
                        "admit",
                        st,
                        ready=ready_at, sequence=order,
                    )
                    step = st["task"]["steps"][st["step"]]
                    body = _build_request_body(st, step)
                    future = pool.submit(
                        _invoke, sender, url, body, timeout, origin
                    )
                    inflight[future] = (st, ready_at, body)

                # sleep and check everything again    
                time.sleep(0.001)
    finally:
        # Always close logs, including when scheduling or the sender raises.
        events.close()
        reqs.close()
        taskfile.close()
    return rows, time.perf_counter() - origin
