# Phase 1 GPU configuration

[`phase1-gpu.yml`](../phase1-gpu.yml) records the actual service settings used in
the Oct 28-31 and Nov 1 GPU experiments. It selects **Qwen3.5-0.8B Q8_0**, not
the Qwen2.5-Coder-3B CPU model used in the November 3 memory-budget sweep.
The default `config.yml` still selects the original CPU-only startup path.

## Pinned runtime and model

- Runtime: llama.cpp **0.8.0-dev, b11960, commit 8642541b2**, Linux x86-64,
  built with GNU 13.3.0; the installed distribution was CUDA **12.8**.
- Official binaries: [b11960 release](https://github.com/ggml-org/llama.cpp/releases/tag/b11960),
  `llama-b11960-bin-ubuntu-cuda-12.8-x64.tar.gz` and
  `cudart-llama-b11960-bin-ubuntu-cuda-12.8-x64.tar.gz`.
- Model: `ggml-org/Qwen3.5-0.8B-GGUF`, revision
  `807dfd9a6fadbf703207aac3bfb0b2b3040d077c`, file `Qwen3.5-0.8B-Q8_0.gguf`.
  [Pinned download](https://huggingface.co/ggml-org/Qwen3.5-0.8B-GGUF/resolve/807dfd9a6fadbf703207aac3bfb0b2b3040d077c/Qwen3.5-0.8B-Q8_0.gguf).
- Model SHA256: `37ae482d336108d23516fa35e8e0c4126688d81018b87178a18d752a1357814f`,
  size 833592096 bytes. Put it at `models/Qwen3.5-0.8B-Q8_0.gguf`.
- Reference hardware: RTX 5060 Laptop GPU, 8151 MiB VRAM; Windows/WSL2 Ubuntu.
  A CUDA-capable llama.cpp build, NVIDIA GPU/driver and the matching runtime
  libraries are required. Other machines can reproduce the configuration but
  should not assume identical absolute timings.

Model paths are resolved relative to the YAML file, not the shell's working
directory. `command: ['llama-server']` searches PATH. `--binary` accepts a local
binary path; `--library-path` supplies its Linux `LD_LIBRARY_PATH`.
These overrides are recorded in managed experiment manifests.

The launcher checks the configured model hash and expected runtime version
before starting the service. A mismatch fails explicitly; downloading the newest
`llama` application is not a substitute for the pinned runtime.

## Start directly

From the repository root in Linux/WSL, with `llama-server` and its shared
libraries already discoverable:

Install Git LFS in that same Linux environment (`sudo apt-get install git-lfs`
on Ubuntu). A Windows installation alone does not provide Linux `git-lfs`;
the benchmark reads Git metadata in its current environment.

```bash
python -m src.server --config phase1-gpu.yml --dry-run
python -m src.server --config phase1-gpu.yml
```

For the directory layout used on the original machine:

```bash
python -m src.server --config phase1-gpu.yml \
  --binary ../llama-linux-b11960/llama-b11960/llama-server \
  --library-path ../llama-linux-b11960/llama-b11960:../llama-linux-b11960/cudart-llama-b11960-bin-ubuntu-cuda-12.8-x64
```

`--dry-run` prints resolved arguments only; it does not verify installed files or
load the model. Actual startup performs version/hash verification. A direct
startup prints its PID and remains in the foreground; Ctrl+C stops its child.
Use an unused configured port; do not start two services on 9931.
Health check: `http://127.0.0.1:9931/health`.

## Run benchmark using the same YAML

The managed runner supports the same `--config`, `--binary`, `--library-path`
options. It starts a fresh local model service for each K, records the chosen
configuration, waits for health, and stops only the service it started.

```bash
python -m experiments.run_experiment --config phase1-gpu.yml \
  --binary ../llama-linux-b11960/llama-b11960/llama-server \
  --library-path ../llama-linux-b11960/llama-b11960:../llama-linux-b11960/cudart-llama-b11960-bin-ubuntu-cuda-12.8-x64 \
  --workload data/gpu-timeline-20261101/suite/workload.jsonl \
  --concurrency 1 2 4 --diagnostics --timeout 120 --output results/phase1-gpu-new
```

Alternatively, start the server separately and pass its PID to the experiment
runner with `--config phase1-gpu.yml --pid PID`; an externally supplied server
is not started, stopped, or version-checked by that runner. Verify its actual
command and logs yourself. Default CLI use without `--config` retains CPU mode.

## What is controlled

- All GPU layers (`--gpu-layers all`, equivalent to original `-ngl all`).
- Flash attention on; 8 generation / 8 prompt-processing CPU threads.
- 10 slots, total context 40960 = 4096 per slot. Client concurrency K is separate.
- RAM prompt cache budget 0, no idle-slot cache, no context shifting, no unified KV.
- Remove inherited `GGML_CUDA_DISABLE_GRAPHS` in the child environment to select
  the original default Graph path. The separate Graph-disabled intervention in
  the raw data is **not** the default GPU profile.
- Request-side temperature, seed, thinking budget, token limits and validators
  live in the frozen workload/runner, not the server YAML. The archived 16-task
  workload above is the Nov 1/v2 seed42 input; the Oct 31 clean suite used a
  different frozen 64-task seed20261031 input, available in its data directory.

Changing model, runtime, K, load, context or cache mode changes the experiment.
Simply launching this YAML does not reproduce Nsight capture windows or the
counterfactual Graph intervention; see the raw suite plans and
[bottleneck monitoring](bottleneck-monitoring.md).

## Validation on November 3

The YAML was loaded by the managed experiment runner with the pinned local CUDA
runtime and model. At K=2 the first four archived tasks (one of each type) all
passed, including all three dependent steps; 6/6 HTTP requests succeeded.
GPU/CPU/memory sampling reported no collector errors, and the server was stopped
automatically afterward. This was a functional smoke check, not a replacement
for the original performance experiments. Regression tests passed (26 passed;
the separately opt-in cgroup OOM test was skipped in this GPU-focused run).
