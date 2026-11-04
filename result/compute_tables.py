"""Recompute Table 1 and Table 2 of the Phase 1 writeup from raw logs.
Usage: python compute_tables.py PATH_TO/data
"""
import json, sys, glob
from pathlib import Path
from statistics import mean

DATA = Path(__file__).resolve().parent.parent / "data"

def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

def percentile(xs, p):
    """Linear-interpolation percentile (same as numpy's default)."""
    xs = sorted(xs); k = (len(xs) - 1) * p / 100
    f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)

# ---------------- Table 1: E1 = baseline-v2-20261028, all 9 runs ----------------
prompt, gen = {}, {}
for run in glob.glob(str(DATA / "baseline-v2-20261028" / "repeat*" / "k*")):
    ttype = {t["task_id"]: t["task_type"] for t in read_jsonl(Path(run) / "tasks.jsonl")}
    for r in read_jsonl(Path(run) / "requests.jsonl"):
        key = (ttype[r["task_id"]], r["step_id"])
        prompt.setdefault(key, []).append(r["usage"]["prompt_tokens"])
        gen.setdefault(key, []).append(r["usage"]["completion_tokens"])
print("Table 1 (mean over all E1 requests of that type/step)")
for key in sorted(prompt):
    print(f"  {key[0]:13s} step {key[1]}: prompt {mean(prompt[key]):7.1f}  generated {mean(gen[key]):6.1f}  (n={len(gen[key])})")

# ---------------- Table 2: E2 = diagnostic-20261031/clean-r1, K=1,2,4,8 ----------------
print("\nTable 2 (E2, one run per K)")
print("  K  Valid.  Drain  Goodput  Tok/s   P50    P95   Queue  VRAM")
for k in (1, 2, 4, 8):
    run = DATA / "diagnostic-20261031" / "clean-r1" / f"k{k}"
    tasks = read_jsonl(run / "tasks.jsonl")
    reqs = read_jsonl(run / "requests.jsonl")
    ok = [t for t in tasks if t["status"] == "completed" and t.get("quality_pass", True)]
    drain = max(t["end"] for t in tasks)                       # first arrival (t=0) -> last completion
    goodput = len(ok) / drain                                  # validated tasks per second
    toks = sum(r["usage"]["completion_tokens"] for r in reqs) / drain
    lat = [t["latency_s"] for t in ok]                         # end - arrival, validated tasks only
    queue = mean(t["queue_s"] for t in tasks)                  # summed over each task's steps
    vram = max(int(row.split(",")[5]) for row in open(run / "gpu.csv").read().splitlines()[1:])
    print(f"  {k}  {len(ok)}/{len(tasks)}  {drain:6.1f}  {goodput:.3f}  {toks:6.1f}  "
          f"{percentile(lat,50):5.1f}  {percentile(lat,95):5.1f}  {queue:5.1f}  {vram}")

    # python compute_tables.py data