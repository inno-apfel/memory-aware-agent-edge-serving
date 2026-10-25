# runner.py

import time
import threading
import json

from src.send import run_workload
from src.monitor import run_monitor

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

def generate_body(prompt):
    return {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "stream": True,
        "temperature": 0,
        "seed": 42,
        "ignore_eos": True,
        "cache_prompt": False,
        "chat_template_kwargs": {"enable_thinking": False},   # try to turn thinking off
    }

# ---- Config ----
N = 50
CONCURRENCY = 10

path = Path(__file__).resolve().parent.parent / "workloads" / "examples.jsonl"
with open(path) as f:
    workload = [json.loads(line) for line in f if line.strip()]

# ---- Setup Monitoring ----
monitored_samples = []
stop_event = threading.Event()
monitor_thread = threading.Thread(
    target=run_monitor, args=(stop_event, monitored_samples), daemon=True
)

# ---- Start Monitoring ----
monitor_thread.start()
time.sleep(5)  # baseline samples before load

request_results = []
t0 = time.time()
try:
    request_results = run_workload(workload, concurrency=CONCURRENCY)
finally:
    wall = time.time() - t0
    time.sleep(5)  # trailing samples after load
    stop_event.set()
    monitor_thread.join()

# ---- Process Monitoring Results ----
df = pd.DataFrame(monitored_samples)
# elapsed seconds since first sample
df["t_elapsed"] = df["t_mono"] - df["t_mono"].iloc[0]
# bytes -> GB|
for c in ["rss", "uss", "vms", "sys_avail", "swap_used"]:
    df[c + "_gb"] = df[c] / 1024**3

# ---- Plot ----

fig, axes = plt.subplots(2, 1, figsize=(10, 9), sharex=True)

# 1. Process memory (rss/uss)
axes[0].plot(df["t_elapsed"], df["rss_gb"], label="RSS")
axes[0].plot(df["t_elapsed"], df["uss_gb"], label="USS", linestyle="--")
axes[0].set_ylabel("Process mem (GB)")
axes[0].legend()

# 2. CPU
axes[1].plot(df["t_elapsed"], df["cpu_pct"], color="tab:orange", label="CPU %")
axes[1].set_ylabel("CPU (%)")
axes[1].set_xlabel("Elapsed time (s)")
axes[1].legend()

for ax in axes:
    ax.grid(alpha=0.3)

fig.suptitle("Process monitor")
fig.tight_layout()

fig.savefig("results/monitor_plot.png", dpi=150, bbox_inches="tight")

# ---- Summary ----
ok = [r for r in request_results if r.get("status") in (200, "ok")]
lat = sorted(r["latency"] for r in request_results)
print(f"{len(ok)}/{len(request_results)} succeeded in {wall:.1f}s "
      f"(concurrency={CONCURRENCY})")
if lat:
    print(f"latency  p50={lat[len(lat)//2]:.2f}s  max={lat[-1]:.2f}s")