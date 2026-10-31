"""Run the same workload at one or more concurrency limits and archive results.

Each requested K gets an independent output directory with a manifest, scheduler
logs, process-tree memory samples, and summary. The CLI requires the local model
server PID because remote-process memory sampling is not implemented. The root
output directory must not already exist so a previous run cannot be overwritten.
"""

import argparse
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

from src.agent_runner import run_tasks
from src.monitor import monitor_process
from src.utils import load_config


def percentile(values, p):
    """Return the nearest-rank percentile, or ``None`` for an empty sample."""
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def main(argv=None):
    """Parse CLI arguments, run each K sequentially, and write comparisons.

    The workload bytes are copied into the output root and hashed into every
    manifest. The summary reports completed task throughput and successful-task
    latency percentiles; failures and memory monitor errors remain explicit.
    """
    # Parse and validate options before creating any output artifacts.
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", default="workloads/tasks-v2.jsonl")
    parser.add_argument("--output", default="results/smoke")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--url")
    parser.add_argument(
        "--pid", type=int, help="Local MODEL server PID, not client PID"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="HTTP connect/read inactivity timeout, not task deadline",
    )
    a = parser.parse_args(argv)
    if (
        any(k < 1 for k in a.concurrency)
        or len(set(a.concurrency)) != len(a.concurrency)
        or a.timeout <= 0
    ):
        parser.error("Need distinct positive concurrency values and positive timeout")
    if not a.pid:
        parser.error(
            "Real runs require --pid for local server memory; remote sampling integration is pending"
        )
    # Freeze the exact input bytes in the run directory. The saved copy and
    # manifest hash make it possible to confirm that each K saw the same tasks.
    root = Path(a.output)
    root.mkdir(parents=True, exist_ok=False)
    content = Path(a.workload).read_bytes()
    (root / "workload.jsonl").write_bytes(content)
    tasks = [json.loads(line) for line in content.decode().splitlines() if line.strip()]
    server = load_config()["server"]
    url = a.url or f"http://{server['host']}:{server['port']}/v1/chat/completions"
    pid = a.pid
    # Capture repository and environment metadata once for this invocation.
    repo = Path(__file__).resolve().parents[1]
    git = ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo)]
    commit = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    dirty = bool(
        subprocess.check_output(git + ["status", "--porcelain"], text=True).strip()
    )
    # Run concurrency settings sequentially so each gets its own logs and
    # memory-sampling window against the same loaded workload.
    summaries = []
    for k in a.concurrency:
        out = root / f"k{k}"
        out.mkdir()
        manifest = dict(
            run_id=out.name,
            mode="REAL_MODEL",
            workload_sha256=hashlib.sha256(content).hexdigest(),
            concurrency=k,
            url=url,
            server_pid=pid,
            git_commit=commit,
            dirty=dirty,
            source_sha256={
                str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in ["src", "scripts", "workloads"]
                for p in (repo / folder).rglob("*.py")
            },
            python=sys.version,
            platform=platform.platform(),
            server_config=load_config(),
            dependencies={
                n: importlib.metadata.version(n)
                for n in ["requests", "psutil", "PyYAML"]
            },
            start_wall=time.time(),
            start_monotonic=time.perf_counter(),
            timeout_s=a.timeout,
            window="finite workload from injection origin through drain; no warmup",
            memory_scope="explicit local server process tree",
            pending_real_metadata=[
                "model file hash",
                "runtime version",
                "hardware budget",
                "token/context calibration",
            ],
        )
        (out / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        # Sample the server in parallel with task execution; stop and join the
        # collector even if the scheduler exits with an exception.
        stop = threading.Event()
        samples = []
        errors = []

        def collect():
            """Collect server-tree samples until stopped or the PID disappears."""
            try:
                for sample in monitor_process(pid=pid, interval=0.02):
                    samples.append(dict(run_id=out.name, **sample))
                    if stop.is_set() or sample["rss"] == "DEAD":
                        break
            except Exception as exc:
                errors.append(repr(exc))

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()
        try:
            rows, wall = run_tasks(tasks, k, out, url=url, timeout=a.timeout)
        finally:
            stop.set()
            thread.join()
            if samples:
                with (out / "memory.csv").open("w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(samples[0]))
                    writer.writeheader()
                    writer.writerows(samples)
            (out / "monitor_errors.json").write_text(json.dumps(errors))
        # Summarize terminal task rows and sampled memory. Percentiles include
        # successful tasks only, while status counts retain every failure.
        successful = [r for r in rows if r["status"] == "completed"]
        lat = [r["latency_s"] for r in successful]
        summary = dict(
            mode=manifest["mode"],
            k=k,
            tasks=len(rows),
            completed=len(successful),
            statuses=dict(Counter(r["status"] for r in rows)),
            drain_s=wall,
            completed_tasks_per_s=len(successful) / wall,
            p50_s=percentile(lat, 0.5),
            p95_s=percentile(lat, 0.95),
            peak_rss_bytes=max(
                (s["rss"] for s in samples if isinstance(s["rss"], int)),
                default=None,
            ),
            memory_samples=len(samples),
            monitor_errors=errors,
        )
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        summaries.append(summary)
    # Persist a root-level comparison after all requested K values complete.
    (root / "comparison.json").write_text(json.dumps(summaries, indent=2))
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
