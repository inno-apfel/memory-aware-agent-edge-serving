# Enforced DRAM budget experiment (CPU-only)

This experiment changes cgroup v2 `memory.max`, not model size, context length,
or an admission estimate. It does not cap CUDA VRAM. It runs the current
Qwen2.5-Coder-3B-Instruct Q4_K_M model with fixed 10 slots, 40960 total context,
8 CPU threads, K=2, and zero swap allowance for the service cgroup.

## Isolation and loading

Run in Linux/WSL with an already delegated writable memory controller. Root
privileges or equivalent delegation are required. The runner creates only a
new direct `/sys/fs/cgroup/agent-memory-<uuid>` child. The exec helper verifies
membership before replacing itself with llama-server; all model descendants
inherit the same group. Clients and samplers stay outside. Read-back validates
the memory limit and swap cap. Removal is refused while the group is populated.
Do not run the experiment with a busy host, existing server on the target port,
or another process mapping the same model.

The pinned b11960 runtime uses `--load-mode none` to load weights into native
memory rather than sharing a precharged mmap. This is an explicit experimental
choice, different from the runtime's default mmap loading. It can expose a sharp
startup/anonymous-memory feasibility boundary rather than a smooth page-cache
reclaim curve. Do not extrapolate these results to mmap, GPU offload, different
models, or cache eviction. `memory.high` remains max; `memory.swap.max` is zero.

## Commands

Download and verify the official model separately; record its revision and hash.
Supply absolute paths or paths relative to the repository. Use fresh outputs.

```bash
python -m workloads.memory_budget --output results/memory-new/frozen32.jsonl

python -m experiments.run_memory_budget \
  --server /path/to/llama-server --model /path/to/model.gguf \
  --libraries /path/to/runtime:/path/to/cudart \
  --budget-mib 6144 --workload results/memory-new/frozen32.jsonl \
  --output results/memory-new/pilot-wide

# Select four budgets only AFTER pilot calibration; these are examples.
python -m experiments.run_memory_matrix \
  --server /path/to/llama-server --model /path/to/model.gguf \
  --libraries /path/to/runtime:/path/to/cudart \
  --budgets-mib 6144 3840 3750 3712 --repeats 3 \
  --workload results/memory-new/frozen32.jsonl --output results/memory-new/formal

python -m experiments.analyze_memory_budget \
  --input results/memory-new/formal --output results/memory-new/analysis
```

The matrix writes a shuffled run order before starting. Each trial starts a fresh
service with its limit already active, performs a separate four-task warmup,
then runs the same 32-task finite burst. Warmup is not mixed with measured tasks.
Startup timeout is 180 s, whole worker watchdog 900 s (warmup included), HTTP
inactivity timeout 60 s. The service is stopped in cleanup, including exceptions.
The runner refuses to touch a preexisting server on the requested port.

## Files and metric scope

- `manifest.json`: hashes, exact command, budget readback, PID, source, timers.
- `cgroup.jsonl`: startup-to-shutdown memory.current/peak/stat/events/pressure,
  memory.high/max and swap current/max; timestamps and units in kernel convention.
- `ready_snapshot.json`: service-ready state before warmup.
- `outcome.json`: startup, worker and service outcome, OOM counters, cleanup data.
- `server.log`, `worker.log`: failures and full runtime diagnostics.
- `warmup/`: all warmup requests/tasks, excluded from results.
- `measured/`: requests/tasks/events/timeline, memory.csv, GPU and CPU CSV,
  pressure.jsonl, metadata/errors and worker summary.
- `analysis/aggregate.csv`, `analysis.json`, `by_budget.json`: per-run values and
  per-budget descriptive repeat summaries; startup failures have missing TTFT,
  not zero. All input tasks count toward service completion feasibility.

TTFT is time from the client HTTP call to first content OR reasoning chunk;
ttft_content is time to visible content. Percentiles summarize HTTP-ok requests,
including ones whose task later fails semantic quality. Queue delay is reported
separately; ready-to-first adds request queueing and is not the entire task's
completion latency. PSI percent is delta some.total / measured elapsed time.
RSS and cgroup memory are distinct. finite burst completion rate is not a
steady-state sustainable arrival rate. Compare per-task type and step when
interpreting mixed TTFT. Retain failed/unstarted groups, not only survivors.

The CPU model calibration strengthens requested prose length while preserving
upstream min_words=140, END validator and max_tokens=1024. The separate
`memory-budget-cpu-v1` profile leaves upstream workloads unchanged. Freeze before
formal trials and never tune prompts per memory budget.

The recipe in `workloads/_memory_budget_base.py` is frozen from commit 39aea8c
and intentionally independent of the current default workload generator. It
preserves the exact inputs used in the November 3 experiments, including the
140-word prose validator. It does not alter the default profile's validation.
The checked-in `workloads/memory-budget-cpu-v1.jsonl` is the canonical 32-task
input; regeneration is hash-tested. Raw data/report archives retain the original
experimental source snapshot, before this packaging-only import isolation.

## Checks

## November 3 measured results

The completed matrix used Qwen2.5-Coder-3B-Instruct Q4_K_M, CPU-only,
`--load-mode none`, zero service swap, K=2 and the same 32-task input. Each
budget was repeated three times with a fresh service and separate warmup.

| Budget (MiB) | Quality-passing tasks | Trials with OOM | Mean per-run TTFT P95 (s) |
| --- | --- | --- | --- |
| 6144 | 96/96 | 0/3 | 7.65 |
| 3840 | 96/96 | 0/3 | 7.68 |
| 3750 | 96/96 | 0/3 | 7.57 |
| 3712 | 0/96 | 3/3 | unavailable |

The nine complete runs each generated 3937 tokens. All three 3712-MiB trials
started and completed warmup, then failed with OOM during measured requests.
Missing TTFT is not zero; their short failure-drain time is not a performance
gain. At 3750 MiB, measured memory PSI averaged approximately 0.00015%, despite
some limit/reclaim events. The evidence supports a workload-feasibility boundary,
not a substantial smooth TTFT degradation above it. Three repeats are descriptive.

This is a K=2 result for the specified loading mode, model and memory policy.
It does not establish whether K=1 or admission control could avoid the lower
budget's runtime peak, and does not measure GPU memory constraints or KV eviction.
Full raw logs, the original experimental source snapshot and the report are
distributed separately in the November 3 handoff archive, not committed here.

## Validation commands

```bash
python -m unittest discover -s tests -v
# Explicit Linux/root integration test: a disposable 64MiB child allocates 256MiB.
MEMORY_CGROUP_TEST=1 python -m unittest discover -s tests -v
```

See the authoritative [cgroup v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).
The OOM test touches only its owned group. Do not rerun expensive model trials
just for regression tests; pure tests cover parser, failure accounting and TTFT.
