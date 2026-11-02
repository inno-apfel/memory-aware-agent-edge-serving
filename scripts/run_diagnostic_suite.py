"""Frozen v2 burst workload, paired K sweep and longer-context probe."""
import argparse
import json
from pathlib import Path
import platform
import time

import psutil
import requests

from experiments.run_experiment import main as experiment
from src.workload import generate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    root = Path(a.output)
    root.mkdir(parents=True, exist_ok=True)
    if (root / "suite-plan.json").exists():
        raise RuntimeError("Refusing to overwrite a suite")
    process = psutil.Process(a.pid)
    if "llama-server" not in process.name():
        raise RuntimeError("PID is not llama-server")
    base = "http://127.0.0.1:9931"
    requests.get(base + "/health", timeout=10).raise_for_status()
    tasks = generate(64, seed=20261031, interval=.02)
    longer = generate(32, seed=20261031, interval=.02)
    for task in longer:
        if task["task_type"] == "long_context":
            extra = "\n".join(f"Record {i}: value {100+i}." for i in range(100, 200))
            task["steps"][0]["prompt"] = extra + "\n" + task["steps"][0]["prompt"]
    for name, items in [("mixed64", tasks), ("context32", longer)]:
        (root / (name + ".jsonl")).write_text("".join(json.dumps(t)+"\n" for t in items))
    plan = dict(seed=20261031, profile="v2", server_pid=a.pid,
                process_created=process.create_time(), server_command=process.cmdline(),
                platform=platform.platform(), logical_cpus=psutil.cpu_count(),
                ram_bytes=psutil.virtual_memory().total, swap_bytes=psutil.swap_memory().total,
                start_wall=time.time(), orders=[[1,2,4,8],[8,4,2,1]],
                context_probe=dict(count=32, long_context_records=200, order=[1,8]),
                arrival="finite burst, 0.02 s spacing; not steady-state throughput",
                repetitions="two paired repeats, descriptive not significance testing",
                generation="same frozen v2 config, no quality tuning or retries")
    (root / "suite-plan.json").write_text(json.dumps(plan, indent=2))
    # A complete 4-task warmup and telemetry smoke test, excluded from evaluation.
    (root / "warmup.jsonl").write_text("".join(json.dumps(t)+"\n" for t in generate(4, 101)))
    stages = [("warmup", "warmup", [1]), ("mixed-r1", "mixed64", [1,2,4,8]),
              ("mixed-r2", "mixed64", [8,4,2,1]), ("context-r1", "context32", [1,8])]
    for name, workload, order in stages:
        print("STAGE_START", name, time.time(), flush=True)
        (root / (name+"-metrics-before.txt")).write_text(requests.get(base+"/metrics", timeout=10).text)
        experiment(["--pid", str(a.pid), "--workload", str(root/(workload+".jsonl")),
                    "--output", str(root/name), "--concurrency", *map(str, order),
                    "--timeout", "120", "--diagnostics"])
        (root / (name+"-metrics-after.txt")).write_text(requests.get(base+"/metrics", timeout=10).text)
        print("STAGE_FINISHED", name, time.time(), flush=True)
    print("SUITE_FINISHED", flush=True)


if __name__ == "__main__":
    main()
