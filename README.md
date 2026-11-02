# Memory-aware agent edge serving

**Research Question:** <br>
On a memory-capped llama.cpp server, what limits completed agent work as concurrency, context size, and tool-delay idle time vary: decode bandwidth, KV capacity, or re-prefill after context loss?

# Quick start

### Set up the conda environment

```bash
conda env create -f environment.yml
conda activate 291
```

### Install llama.cpp

```bash
curl -LsSf https://llama.app/install.sh | sh
```

### Run Benchmark

```bash
python -m src.workload --seed 42 --count 16 --output workloads/tasks-v2.jsonl
python -m experiments.run_experiment --workload workloads/tasks-v2.jsonl --concurrency 1 2 4 --timeout 120 --output results/real-v2-new-run
```

## Project structure

### Bottleneck diagnostics

Add `--diagnostics` to `python -m experiments.run_experiment` to save per-core
and server-thread CPU, Linux PSI, and GPU telemetry alongside memory.csv.
The managed server currently runs CPU-only. For GPU experiments, start a
CUDA-enabled server separately and supply its local `--pid` and completion `--url`.
See [monitoring and Nsight timeline analysis](docs/bottleneck-monitoring.md) for
commands, artifact fields, sampling corrections, and interpretation limits.
The larger frozen suite is `python -m scripts.run_diagnostic_suite --help`;
offline CUDA timeline analysis is `python -m scripts.analyze_gpu_timeline --help`.

```text
memory-aware-agent-edge-serving/
├── README.md                    # how to run everything
├── docs/
│   ├── codebase-guide.md        # Architecture and contributor guide
│   └── quality-calibration.md   # Workload quality calibration
├── src/
│   ├── server.py                # start llama-server, cap memory, record the manifest
│   ├── client.py                # send requests, log timings
│   ├── workload.py              # generate tasks.jsonl from a seed
│   ├── runner.py                # the agent loop + FIFO scheduler
│   ├── monitor.py               # sample memory
│   └── utils.py                 # Shared utilities
├── experiments/
│   └── run_experiment.py        # Benchmark runner and summary generation
├── workloads/
├── results/                     # Generated experiment outputs (git-ignored)
├── tests/
├── config.yml                   # Server configuration
└── environment.yml              # Conda environment definition
```


See the [codebase guide](docs/codebase-guide.md) for the runtime flow, module
responsibilities, workload schema, scheduler behavior, and output definitions.

The benchmark runs against a local llama.cpp server and samples that server's
process tree. Use the same frozen workload file for each concurrency setting.
RSS is host memory; it does not measure GPU memory or KV cache occupancy. See
[quality calibration](docs/quality-calibration.md) for workload design and
comparison limits. Generated results are ignored by Git and should be archived
separately.
