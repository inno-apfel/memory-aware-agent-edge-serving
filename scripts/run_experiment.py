"""Run the same frozen workload at K=1,2,4, recording raw artifacts."""

import argparse
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
import math
import os
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
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", default="workloads/tasks.jsonl")
    parser.add_argument("--output", default="results/smoke")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--mock", action="store_true")
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
    if not a.mock and not a.pid:
        parser.error(
            "Real runs require --pid for local server memory; remote sampling integration is pending"
        )
    root = Path(a.output)
    root.mkdir(parents=True, exist_ok=False)
    content = Path(a.workload).read_bytes()
    (root / "workload.jsonl").write_bytes(content)
    tasks = [json.loads(line) for line in content.decode().splitlines() if line.strip()]
    process = None
    try:
        if a.mock:
            ready = root / "mock-port.txt"
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "scripts.mock_server",
                    "--ready-file",
                    str(ready),
                ],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            deadline = time.perf_counter() + 10
            while not ready.exists():
                if process.poll() is not None or time.perf_counter() > deadline:
                    raise RuntimeError("Mock failed to start")
                time.sleep(0.02)
            url = f"http://127.0.0.1:{ready.read_text()}/v1/chat/completions"
            pid = process.pid
        else:
            server = load_config()["server"]
            url = (
                a.url or f"http://{server['host']}:{server['port']}/v1/chat/completions"
            )
            pid = a.pid
        repo = Path(__file__).resolve().parents[1]
        git = ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo)]
        commit = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
        dirty = bool(
            subprocess.check_output(git + ["status", "--porcelain"], text=True).strip()
        )
        summaries = []
        for k in a.concurrency:
            out = root / f"k{k}"
            out.mkdir()
            manifest = dict(
                run_id=out.name,
                mode="MOCK_FUNCTIONAL_ONLY" if a.mock else "REAL_MODEL",
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
                memory_scope=(
                    "mock server RSS/USS"
                    if a.mock
                    else "explicit local server process tree"
                ),
                pending_real_metadata=(
                    [
                        "model file hash",
                        "runtime version",
                        "hardware budget",
                        "token/context calibration",
                    ]
                    if not a.mock
                    else []
                ),
            )
            (out / "run_manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            stop = threading.Event()
            samples = []
            errors = []

            def collect():
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
        (root / "comparison.json").write_text(json.dumps(summaries, indent=2))
        print(json.dumps(summaries, indent=2))
    finally:
        if process:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
