# Memory-aware agent edge serving

**Research Question:** <br>
On a memory-capped llama.cpp server, what limits completed agent work as concurrency, context size, and tool-delay idle time vary: decode bandwidth, KV capacity, or re-prefill after context loss?

# Quick start

### Set up the conda environment

```bash
conda env create -f environment.yml
conda activate 291
```

### Start llama.cpp server

```bash
curl -LsSf https://llama.app/install.sh | sh
python launch_server.py
# grab llama.cpp server process ID for later
pgrep llama
```

### Run Benchmark

```bash
python -m workloads.generate --seed 42 --count 16 --output workloads/tasks-v2.jsonl
# replace SERVER_PID with found process ID
python -m scripts.run_experiment --pid SERVER_PID --workload workloads/tasks-v2.jsonl --concurrency 1 2 4 --timeout 120 --output results/real-v2-new-run
```

## Project structure

```text
memory-aware-agent-edge-serving/
├── docs/
│   ├── codebase-guide.md        # Architecture and contributor guide
│   └── quality-calibration.md   # Workload quality calibration
├── results/                    # Generated experiment outputs (git-ignored)
├── scripts/
│   └── run_experiment.py        # Benchmark runner and summary generation
├── src/
│   ├── agent_runner.py          # Agent scheduling and task execution
│   ├── monitor.py               # Process memory sampling
│   ├── transport.py             # Streaming HTTP transport
│   └── utils.py                 # Shared utilities
├── tests/
│   └── test_benchmark.py        # Scheduler and validation tests
├── workloads/
│   ├── generate.py              # Seeded v2 workload generator
│   └── tasks-v2.jsonl           # Frozen benchmark workload
├── config.yml                   # Server configuration
├── environment.yml              # Conda environment definition
├── launch_server.py             # Local model server launcher
└── README.md
```

See the [codebase guide](docs/codebase-guide.md) for the runtime flow, module
responsibilities, workload schema, scheduler behavior, and output definitions.

The benchmark runs against a local llama.cpp server and samples that server's
process tree. Use the same frozen workload file for each concurrency setting.
RSS is host memory; it does not measure GPU memory or KV cache occupancy. See
[quality calibration](docs/quality-calibration.md) for workload design and
comparison limits. Generated results are ignored by Git and should be archived
separately.
