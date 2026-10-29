# Memory-aware agent edge serving

This branch implements Member B's workloads and request-level FIFO baseline.
See [the implementation and run guide](docs/baseline.md) for definitions,
artifact schemas, limits, and the deferred real-model integration checklist.

## Quick functional check

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-baseline.txt
.\.venv\Scripts\python.exe -m workloads.generate --seed 42 --count 16
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.run_experiment --mock --output results/first-run
```

Use a new output directory on each run. The mock is a local HTTP fixture, not an
LLM. Its throughput and process memory are functional validation data only.
The script starts/stops the fixture and compares K=1,2,4 with the same workload.

## Real model

`config.yml` and `launch_server.py` retain the original server configuration.
After Member A verifies the runtime command, model and resource limits:

```bash
python launch_server.py
# In a separate terminal, replace SERVER_PID with the local server process ID.
python -m scripts.run_experiment --pid SERVER_PID --output results/real-first
```

Real runs require a local server PID for memory sampling. Remote memory sampling
and strict whole-task deadlines are not yet implemented. The HTTP timeout is an
inactivity timeout. Token lengths and context capacity need real-runtime calibration.

### Bounded thinking workload profile

The original workload is retained as `v1`. For Qwen3.5-0.8B, use the separately
versioned `v2` profile after verifying support for llama.cpp's
`reasoning_budget_tokens` and JSON schema output:

```bash
python -m workloads.generate --profile v2 --seed 42 --count 16 --output workloads/tasks-v2.jsonl
python -m scripts.run_experiment --pid SERVER_PID --workload workloads/tasks-v2.jsonl --concurrency 1 2 4 --timeout 120 --output results/real-v2-new-run
```

Arithmetic uses a 512-token thinking budget and an exact integer `answer` JSON
field. Tool-copy steps turn thinking off and bind the actual tool output into
the next prompt. Long prose keeps the original 180-word minimum and END check.
See [quality calibration](docs/quality-calibration.md) for the rationale and
comparability limits. Use the same frozen file for every concurrency setting.

## Layout

- `workloads/generate.py`: seeded short, long-context, long-output, three-step tasks.
- `workloads/tasks.jsonl`: frozen task fixture for the new runner.
- `workloads/examples.jsonl`: legacy single-request payload examples.
- `src/agent_runner.py`: ready-time FIFO, task histories, tools, validation and logs.
- `src/transport.py`: streaming HTTP adapter and explicit failure records.
- `src/send.py`: legacy `send_request` and `run_workload` compatibility API.
- `src/monitor.py`: process-tree sampling with explicit PID support.
- `scripts/run_experiment.py`: CLI, manifests, memory collection and summaries.
- `scripts/mock_server.py`: deterministic local HTTP fixture.
- `tests/test_baseline.py`: scheduler and HTTP regression tests.
- `main.ipynb`: original exploratory notebook; not the reproducible experiment entry.

Memory values are bytes. RSS is not GPU memory or KV occupancy. Stream chunks are
not tokens; absent usage is null. All failures are retained. Results and virtual
environments are ignored by Git and should be archived separately.
