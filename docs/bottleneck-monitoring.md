# Bottleneck telemetry

Run the existing baseline with `--diagnostics` to add optional Linux per-core,
server-thread, pressure and GPU samples:

```bash
python -m experiments.run_experiment --pid SERVER_PID \
  --workload workloads/tasks-v2.jsonl --concurrency 1 2 4 8 \
  --timeout 120 --diagnostics --output results/diagnostic-new
```

Use a new output directory. This does not modify workload generation, admission,
quality validation, or the existing memory.csv format. Sampling is optional.

The current managed server (`src/server.py`) explicitly uses `--device none`
and `--gpu-layers 0`. Keep that CPU-only baseline unchanged. For a GPU experiment,
start a CUDA-enabled llama.cpp server separately, verify GPU offload in its startup
log, then pass its local `--pid` and completion `--url` to the experiment command.
The PID must identify that same server, not the client or a different endpoint.
An external server is never stopped by the experiment runner. Without `--pid`,
the existing per-K managed startup/shutdown behavior is retained. Merely collecting
gpu.csv does not prove model GPU offload: these counters cover the whole device.

| File | Scope and interpretation |
| --- | --- |
| memory.csv | Existing process-tree RSS/USS; parent process CPU; guest available RAM and swap |
| cpu_cores.csv | Guest logical CPU busy and I/O-wait percentages; busy excludes idle and I/O wait |
| cpu_threads.csv | Server parent process threads; delta user+system CPU seconds / elapsed seconds; 100% = one logical CPU |
| pressure.jsonl | Guest system CPU/memory/I/O PSI, cumulative vmstat counters, RAM and swap |
| gpu.csv | Whole GPU utilization, memory activity, VRAM, power, temperature and clocks; other applications may contribute |
| resource_metadata.json | PID creation time, command, CPU affinity/count, scope and units |
| resource_errors.json | Collector errors, including missing/failed GPU queries |

Nominal interval is 0.5 seconds plus sampling overhead. Each row has a wall clock
timestamp; CPU/pressure also include a monotonic timestamp. GPU queries also save
their completion time. Join against timeline.json rather than assuming samples
are exactly periodic. A newly discovered thread has no CPU-delta baseline and is
omitted for its first interval. Missing PSI keys, blank names and NVIDIA N/A fields
are not zeros. A failed collector is recorded, not silently accepted as no load.

Collector version 2 computes per-core utilization from raw CPU-time deltas and
excludes duplicate guest/guest_nice accounting. During the 2026-10-31 diagnosis,
the initial collector used `100 - cpu_times_percent().idle - iowait` at subsecond
intervals. The installed psutil implementation used a minimum one-second
denominator, producing false busy percentages. Those original per-core columns
are explicitly invalid; other telemetry is unaffected. Corrected validation
runs use the same frozen workload and have `collector_version: 2` in metadata.
Do not use the old per-core files to claim CPU saturation.

Compute PSI stall fraction from delta total microseconds divided by observed
elapsed microseconds. System CPU `full` is not used to claim CPU saturation.
VM counter deltas must be compared over the same run. Major faults can include
file-backed page loads; they do not alone establish swapping or memory exhaustion.
`utilization.memory` measures device memory activity time, not VRAM occupancy and
not percentage of theoretical memory bandwidth.

The Windows host is outside guest PSI. Optional `scripts/sample_host.py` records
host RAM and per-core CPU and explicitly records inaccessible pagefile counters.
It stops when the specified stop file exists. Additional Windows paging rates can
be collected with Win32_PerfFormattedData_PerfOS_Memory; retain timestamps and
coverage limits. Do not infer host memory health from guest available RAM alone.

```powershell
python scripts/sample_host.py --output results/host-cpu-ram.jsonl --stop-file results/host-stop
# In another terminal:
./scripts/sample_windows_pressure.ps1 -Output results/host-paging.jsonl -StopFile results/host-stop
# Stop both collectors after experiments:
New-Item -ItemType File -Path results/host-stop
```

Use fresh output and stop-file paths. The Windows paging script does not collect
application names or content. The output directory must already exist.

## Frozen diagnosis suite

```bash
python -m scripts.run_diagnostic_suite --pid SERVER_PID \
  --output results/diagnostic-suite-new
```

This freezes v2 seed 20261031, 64 mixed tasks at 0.02-second arrivals, runs K
1/2/4/8 then 8/4/2/1, and probes 32 tasks with doubled long-context distractor
records at K=1/8. A four-task warmup is saved separately. The probe is not a paired
context-length-only comparison because it also has fewer tasks. All failures
are retained; changing the seed does not guarantee quality success.

These are finite backlog/drain experiments, not steady-state arrival capacity
estimates. Report task quality, actual generated tokens, and runtime overhead
alongside performance. Two repeats support descriptive comparisons only.
Busy CPU threads can be CUDA polling; use a profiler before declaring a CPU
arithmetic bottleneck. GPU utilization alone cannot separate kernel throughput,
memory bandwidth, launch/synchronization overhead, or WSL driver costs.

Primary metric references:
- https://docs.kernel.org/accounting/psi.html
- https://docs.nvidia.com/deploy/nvidia-smi/index.html
- https://docs.nvidia.com/cuda/cuda-runtime-api/cuda_runtime_api/group__CUDART__DEVICE.html

## GPU timeline analysis

Use NVIDIA Nsight Systems interactive launch/start/stop to collect only a warmed
request interval. Capture Graph envelopes for the full workload, then use short
`--cuda-graph-trace=node` windows for individual kernel timing. Retain native
`.nsys-rep` captures, exported SQLite, workload hashes, all output/quality logs,
the exact profiler version, and capture warnings. The local 2026-11-01 report uses
v2 seed=42 with 16 tasks; its absolute timings are not directly comparable with
the earlier seed=20261031 64-task diagnostic suite.

```bash
nsys export --type=sqlite --output=node-k1.sqlite node-k1.nsys-rep
python -m scripts.analyze_gpu_timeline SQLITE_DIRECTORY --output analysis.json
```

The analyzer merges overlapping GPU work across streams, clips pre-capture
records (including negative-time Graph history), and intersects CPU sync/launch
calls with GPU work. CPU synchronization waiting for active GPU kernels is not
independent overhead. Conversely, a sync call while the GPU is idle is an
observation, not proof that its entire duration is removable. LaunchKernel API
counts can include graph construction calls. Graph-level kernel tables exclude
internal Graph nodes; Graph envelopes must not be interpreted as pure kernel busy
time. Do not infer memory bandwidth saturation from this timeline alone.

API interval union and 100-ms binning use streaming calculations so millions of
launch calls do not require duplicate Python interval lists. Analyze offline,
after capture, to avoid the analyzer itself competing for RAM/CPU. Review graph
association and missing-event diagnostics before drawing conclusions. The report
includes a no-profiler Graph-enable/disable intervention and explicitly retains
a contaminated overhead comparison rather than presenting it as clean evidence.
