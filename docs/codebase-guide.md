# Codebase guide

This guide follows one benchmark run from its inputs through its output files,
then maps the main responsibilities to source modules. It is intended to help a
new contributor decide where a change belongs and understand what the metrics do
and do not mean.

## What the project measures

The benchmark compares finite agent workloads against a local llama.cpp server
at different maximum numbers of simultaneous model requests (`K`). The scheduler
keeps task steps in order, but releases a request slot while a task waits for a
simulated tool delay. This measures a particular mix of request concurrency,
prompt/output sizes, task arrivals, and tool idle time. It is not a steady-state
throughput test and does not directly measure GPU memory or KV-cache occupancy.

Use the same workload file and server configuration for each K in a comparison.
The checked-in `workloads/tasks-v2.jsonl` is the reproducible seed-42 fixture;
the generator can create another fixture, but regenerating a file changes the
input artifact and its hash if generation parameters differ.

## Run flow

1. `launch_server.py` reads `config.yml` and starts `llama serve` in the
   foreground. Leave it running in its own terminal.
2. `workloads/generate.py` can write a seeded JSONL workload. The checked-in
   v2 file already contains one fixture.
3. `scripts/run_experiment.py` validates CLI values, copies and hashes the
   workload, records environment and Git metadata, and runs each requested K.
4. For a K, it starts `src.monitor.monitor_process` in a background thread and
   calls `src.agent_runner.run_tasks`.
5. The scheduler sends each admitted request through `src.transport.send_request`.
   It validates the returned content, continues a successful task chain, and
   records request, event, and task rows.
6. The experiment runner stops sampling, writes summaries, then proceeds to the
   next K. Its output directory must be new; existing results are never replaced.

## Source map

| File | Responsibility | Change here when… |
| --- | --- | --- |
| `launch_server.py` | Maps `config.yml` to the `llama serve` command. | The server command interface changes. |
| `src/utils.py` | Loads YAML and discovers a local process by name. | Shared config loading or process discovery changes. |
| `src/transport.py` | Sends streaming HTTP requests and parses SSE events. | Endpoint behavior, timeout handling, or response parsing changes. |
| `src/agent_runner.py` | Validates task input, schedules ready steps, manages history/tools, and writes per-request logs. | Scheduling policy, task semantics, or task-level metrics change. |
| `src/monitor.py` | Samples process-tree RSS/USS/VMS, CPU, and host memory/swap. | Sampling cadence or memory collection changes. |
| `workloads/generate.py` | Builds deterministic v2 task mappings and serializes JSONL. | Workload categories, prompts, arrival rates, or generation settings change. |
| `scripts/run_experiment.py` | CLI orchestration, run manifests, per-K summaries, and comparison output. | Run-level metadata or summary calculations change. |
| `tests/test_benchmark.py` | Model-free checks using an injected deterministic sender. | Scheduler or generation contracts change. |

## Workload format and v2 settings

Each JSONL line is one task object with these fields:

- `task_id`: unique identifier within the input file.
- `task_type`: one of `short`, `long_context`, `long_output`, or `three_step`.
- `arrival_offset_s`: scheduled arrival relative to the scheduler start.
- `steps`: ordered model requests. A step has a prompt and `max_tokens`; optional
  fields specify exact expected output, answer format, generation parameters,
  or tool behavior.
- `initial_messages`: optional system/history messages for the first request.
- `workload_profile`: descriptive version tag.

The v2 arithmetic steps enable thinking with a 512-token reasoning budget and
request a JSON object with exactly one integer `answer`. The client validates
the actual returned value against the task's expected answer. Tool-copy steps
disable thinking and use the preceding actual assistant output as tool input;
the expected answer is used for validation only. Long prose disables thinking,
uses a 1024-token output limit, and is checked for minimum word count and an
`END` suffix. Those checks do not establish factual or semantic quality. See
[`quality-calibration.md`](quality-calibration.md) for calibration evidence and
comparability limits.

## Scheduler behavior and invariants

The scheduler keeps pending work in a min-heap ordered by ready time and a
monotonically increasing tie-break sequence. It submits up to K requests to a
thread pool. A task's steps are sequential: the next step becomes ready only
after the prior request succeeds, passes validation, and completes any local
tool delay. Failed requests and invalid answers terminate that task without a
retry. Tool waits do not occupy model-request slots.

The injected `sender` argument exists so scheduler tests do not need a model or
network server. Production uses `send_request`. Keep expected answers out of the
request body; they are evaluation data and must never inform model output or
tool input.

## Transport result contract

`send_request` returns a mapping with a `status` for every outcome. `status` is
`ok` only after a finish reason and terminal SSE `[DONE]` event. Otherwise it
returns a failure status such as an HTTP code, `timeout`, `connection_error`,
`protocol_error`, `server_error`, or `incomplete_stream`. The scheduler treats
anything except `ok` as task failure.

The request timeout is a connect/read inactivity timeout. A stream that keeps
producing data can exceed the configured duration; it is not a total task
deadline. `ttft` measures time to the first content or reasoning event,
`ttft_content` measures time to visible content, and `chunks` counts SSE content
events rather than tokens. Missing server usage remains `null`.

## Output layout and metric meanings

Given `--output results/run-name`, the experiment creates:

```text
results/run-name/
├── workload.jsonl             # Exact input copy for the run
├── comparison.json            # Summaries for all requested K values
├── k1/                         # One directory per K (for example K=1)
│   ├── run_manifest.json       # Workload/code/environment/run metadata
│   ├── timeline.json           # Scheduler monotonic and wall-clock origins
│   ├── events.jsonl            # Arrival, admission, tool wait, request/task end
│   ├── requests.jsonl          # Request body, output, timings, usage, status
│   ├── tasks.jsonl             # One terminal row per task
│   ├── memory.csv              # Process-tree and host memory samples
│   ├── monitor_errors.json     # Sampling errors, if any
│   └── summary.json            # Completion, latency, throughput, memory summary
└── k2/, k4/                    # Same artifact set for additional K values
```

Important metric definitions:

- `queue_s` is request dispatch time minus ready time.
- Task `latency_s` is task end time minus its planned arrival offset. It includes
  injection delay, queueing, model work, and tool waits.
- `drain_s` is elapsed time from scheduler start until all finite workload tasks
  have terminated.
- `completed_tasks_per_s` is successful task count divided by `drain_s`; it is
  finite-workload throughput, not steady-state throughput.
- P50/P95 are nearest-rank percentiles over successful task latencies only.
  Read them alongside the status counts and completion rate.
- `peak_rss_bytes` is the maximum sampled process-tree RSS. Sampling can miss
  short spikes; RSS is not GPU memory or KV-cache occupancy.
- The memory CSV's `sys_avail` and `swap_used` are host-wide values; process
  RSS/USS/VMS are totals over the server and its descendants.

The manifest records the workload SHA-256, Git revision and dirty flag, hashes
of Python sources, Python/platform/dependency versions, server configuration,
PID, URL, and run timing. It currently leaves model-file hash, runtime version,
hardware budget, and token/context calibration as follow-up metadata; record
those alongside archived results for publishable comparisons.

## Working on the code

- Change workload prompts or generation parameters in `workloads/generate.py`,
  regenerate a new fixture, and keep that exact fixture for every K in a run.
- Change task progression or queue policy in `src/agent_runner.py`; preserve
  one terminal row per task and one request row per submitted model request.
- Change API parsing in `src/transport.py`; preserve explicit status values and
  retain partial response/error details for diagnosis.
- Change memory metrics in `src/monitor.py`; document units and whether a field
  is process-tree or host-wide.
- Change aggregate reporting in `scripts/run_experiment.py`; keep the manifest
  and raw logs so summaries can be recalculated later.
- Run model-free tests with `python -m unittest discover -s tests -v`. A passing
  test suite does not check real model quality or server-version compatibility.

The runtime dependencies used by the benchmark are `requests`, `psutil`, and
`PyYAML`; their environment is defined in `environment.yml`. Results and Python
bytecode caches are local artifacts, not source files.
