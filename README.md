# Memory-aware agent edge serving

**Research Question:** <br>
On a memory-capped llama.cpp server, what limits completed agent work as concurrency, context size, and tool-delay idle time vary: decode bandwidth, KV capacity, or re-prefill after context loss?

# Quick start

### Set up conda enviroment

```bash
conda env create -f enviroment.yml
conda activate 291
```

### Start llama.cpp server

```bash
curl -LsSf https://llama.app/install.sh | sh
python launch_server.py
# grab llama.cpp server process ID for later
pgreg -l llama
```

### Run Benchmark

```bash
python -m workloads.generate --profile v2 --seed 42 --count 16 --output workloads/tasks-v2.jsonl
# replace SERVER_PID with found process ID
python -m scripts.run_experiment --pid SERVER_PID --workload workloads/tasks-v2.jsonl --concurrency 1 2 4 --timeout 120 --output results/real-v2-new-run
```

## Project structure

```text
memory-aware-agent-edge-serving/
├── docs/                       # Baseline notes and quality calibration
├── results/                    # Generated experiment outputs (git-ignored)
├── scripts/
│   ├── mock_server.py           # Deterministic local HTTP fixture
│   └── run_experiment.py        # Benchmark runner and summary generation
├── src/
│   ├── agent_runner.py          # Agent scheduling and task execution
│   ├── monitor.py               # Process memory sampling
│   ├── runner.py                # Runner entry points
│   ├── send.py                  # Request/workload compatibility API
│   ├── transport.py             # Streaming HTTP transport
│   └── utils.py                 # Shared utilities
├── tests/
│   └── test_baseline.py         # Baseline regression tests
├── workloads/
│   ├── examples.jsonl           # Example request payloads
│   ├── generate.py              # Seeded workload generator
│   ├── tasks.jsonl              # Frozen baseline workload
│   └── tasks-v2.jsonl           # Frozen v2 workload
├── config.yml                   # Server configuration
├── environment.yml              # Conda environment definition
├── launch_server.py             # Local model server launcher
└── README.md
```

<!-- 
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
environments are ignored by Git and should be archived separately. -->
