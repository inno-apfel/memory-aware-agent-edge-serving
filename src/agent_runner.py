"""FIFO by ready time; K bounds model calls, tools hold no request slots."""

import heapq
import itertools
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from src.transport import send_request

GENERATION_FIELDS = {
    "chat_template_kwargs",
    "reasoning_budget_tokens",
    "response_format",
}


def integer_answer(step, text):
    """Parse the declared output format without accepting equations or coercing booleans."""
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


def run_tasks(tasks, concurrency, output, url=None, timeout=30, sender=send_request):
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
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    origin = time.perf_counter()
    seq = itertools.count()
    ready = []
    inflight = {}
    rows = []
    states = []
    (output / "timeline.json").write_text(
        json.dumps(dict(origin_monotonic=origin, origin_wall=time.time()))
    )
    events = (output / "events.jsonl").open("w", encoding="utf-8")
    reqs = (output / "requests.jsonl").open("w", encoding="utf-8")
    taskfile = (output / "tasks.jsonl").open("w", encoding="utf-8")

    def emit(kind, st, **extra):
        events.write(
            json.dumps(
                dict(
                    run_id=output.name,
                    event=kind,
                    task_id=st["task"]["task_id"],
                    step_id=st["step"],
                    t=time.perf_counter() - origin,
                    **extra,
                )
            )
            + "\n"
        )
        events.flush()

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

    def arrive(st, now):
        st.update(arrived=True, injected=now)
        emit("arrival", st, scheduled=st["task"]["arrival_offset_s"])

    def finish(st, status):
        row = dict(
            run_id=output.name,
            task_id=st["task"]["task_id"],
            task_type=st["task"]["task_type"],
            status=status,
            quality_pass=status == "completed",
            arrival=st["task"]["arrival_offset_s"],
            injected=st["injected"],
            end=time.perf_counter() - origin,
            queue_s=st["queue_s"],
            tool_wait_s=st["tool_wait_s"],
            steps_completed=st["steps_completed"],
        )
        row["latency_s"] = row["end"] - row["arrival"]
        rows.append(row)
        taskfile.write(json.dumps(row) + "\n")
        taskfile.flush()
        emit("task_end", st, status=status)

    def invoke(body):
        dispatch = time.perf_counter() - origin
        try:
            result = sender(body, timeout=timeout, url=url)
        except Exception as exc:
            result = dict(status="error", error=repr(exc), response_text="")
        return dispatch, time.perf_counter() - origin, result

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while ready or inflight:
                now = time.perf_counter() - origin
                for st in states:
                    if not st["arrived"] and st["task"]["arrival_offset_s"] <= now:
                        arrive(st, now)
                for future in list(inflight):
                    if not future.done():
                        continue
                    st, ready_at, body = inflight.pop(future)
                    dispatch, end, result = future.result()
                    st["queue_s"] += dispatch - ready_at
                    reqs.write(
                        json.dumps(
                            dict(
                                run_id=output.name,
                                task_id=st["task"]["task_id"],
                                step_id=st["step"],
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
                    emit("request_end", st, request_end=end, status=result["status"])
                    step = st["task"]["steps"][st["step"]]
                    if result["status"] != "ok":
                        finish(st, result["status"])
                        continue
                    if not validate(step, result["response_text"]):
                        finish(st, "validation_failed")
                        continue
                    st["steps_completed"] += 1
                    st["history"] = body["messages"] + [
                        dict(role="assistant", content=result["response_text"])
                    ]
                    st["step"] += 1
                    if st["step"] == len(st["task"]["steps"]):
                        finish(st, "completed")
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
                    emit("tool_wait", st, tool_start=tool_start, tool_end=next_ready)
                    heapq.heappush(ready, (next_ready, next(seq), st))
                now = time.perf_counter() - origin
                while ready and ready[0][0] <= now and len(inflight) < concurrency:
                    ready_at, order, st = heapq.heappop(ready)
                    if not st["arrived"]:
                        arrive(st, now)
                    emit("admit", st, ready=ready_at, sequence=order)
                    step = st["task"]["steps"][st["step"]]
                    prompt = step["prompt"]
                    if "{tool_result}" in prompt:
                        prompt = prompt.replace("{tool_result}", str(st["tool_result"]))
                    body = dict(
                        messages=st["history"] + [dict(role="user", content=prompt)],
                        max_tokens=step["max_tokens"],
                        stream=True,
                        temperature=0,
                        seed=42,
                        cache_prompt=False,
                        stream_options={"include_usage": True},
                        chat_template_kwargs={"enable_thinking": False},
                    )
                    body.update(step.get("generation", {}))
                    inflight[pool.submit(invoke, body)] = (st, ready_at, body)
                time.sleep(0.001)
    finally:
        events.close()
        reqs.close()
        taskfile.close()
    return rows, time.perf_counter() - origin
