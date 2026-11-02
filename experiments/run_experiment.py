"""Run the same workload at one or more concurrency limits and archive results.

Each requested K gets an independent output directory with a manifest, scheduler
logs, process-tree memory samples, and summary. A configured local model server
is started and stopped for each K. The root output directory must not already
exist so a previous run cannot be overwritten.
"""

import argparse
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import requests
import subprocess
import sys
import threading
import time

from src.runner import run_tasks
from src.monitor import monitor_process
from src.server import LlamaServer
from src.utils import load_config, percentile, write_json

SERVER_START_TIMEOUT_S = 300


def parse_args():
    """Parse CLI options and return them as an argparse.Namespace.

    Returns:
        argparse.Namespace: Parsed options with these attributes:
            workload (str): Workload JSONL path; defaults to
                ``workloads/tasks-v2.jsonl``.
            output (str): New output directory path; defaults to
                ``results/smoke``.
            concurrency (list[int]): Distinct positive concurrency values;
                defaults to ``[1, 2, 4]``.
            url (str | None): Completion endpoint override; defaults to None.
            timeout (float): HTTP inactivity timeout in seconds; defaults to 30.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", default="workloads/tasks-v2.jsonl")
    parser.add_argument("--output", default="results/smoke")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--url")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="HTTP connect/read inactivity timeout, not task deadline",
    )
    args = parser.parse_args()

    # validate args
    if (
        any(k < 1 for k in args.concurrency)
        or len(set(args.concurrency)) != len(args.concurrency)
        or args.timeout <= 0
    ):
        parser.error("Need distinct positive concurrency values and positive timeout")
    return args


def write_json(path, data, *, indent=2):
    # Writes JSON to the supplied artifact path.
    path.write_text(json.dumps(data, indent=indent), encoding="utf-8")


def prepare_output(args):
    # Writes the frozen workload input to root/workload.jsonl.
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    content = Path(args.workload).read_bytes()
    (root / "workload.jsonl").write_bytes(content)
    tasks = [json.loads(line) for line in content.decode().splitlines() if line.strip()]
    return root, content, tasks


def collect_repository_metadata():
    """Capture the repository revision and working-tree state."""
    repo = Path(__file__).resolve().parents[1]
    git = ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo)]
    commit = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    dirty = bool(
        subprocess.check_output(git + ["status", "--porcelain"], text=True).strip()
    )
    return repo, commit, dirty


def create_manifest(args, out, k, content, url, repo, commit, dirty, pid, config):
    # Writes the run record to out/run_manifest.json.
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
        server_config=config,
        dependencies={
            n: importlib.metadata.version(n)
            for n in ["requests", "psutil", "PyYAML"]
        },
        start_wall=time.time(),
        start_monotonic=time.perf_counter(),
        timeout_s=args.timeout,
        window="finite workload from injection origin through drain; no warmup",
        memory_scope="explicit local server process tree",
        pending_real_metadata=[
            "model file hash",
            "runtime version",
            "hardware budget",
            "token/context calibration",
        ],
    )
    write_json(out / "run_manifest.json", manifest)
    return manifest


def write_monitor_artifacts(out, samples, errors):
    # Writes samples to out/memory.csv and errors to out/monitor_errors.json.
    if samples:
        with (out / "memory.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(samples[0]))
            writer.writeheader()
            writer.writerows(samples)
    write_json(out / "monitor_errors.json", errors, indent=None)


def create_summary(out, k, rows, wall, samples, errors, mode):
    # Writes the calculated run summary to out/summary.json.
    successful = [r for r in rows if r["status"] == "completed"]
    lat = [r["latency_s"] for r in successful]
    summary = dict(
        mode=mode,
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
    write_json(out / "summary.json", summary)
    return summary


def wait_for_server(process, server_config):
    """Wait until the configured local server reports that its model is ready."""
    health_url = f"http://{server_config["host"]}:{server_config['port']}/health"
    deadline = time.monotonic() + SERVER_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"llama.cpp server exited during startup with code {process.returncode}"
            )
        try:
            if requests.get(health_url, timeout=1).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise TimeoutError(
        f"llama.cpp server did not become ready within {SERVER_START_TIMEOUT_S} seconds"
    )


def run_one(args, root, content, tasks, url, repo, commit, dirty, config, k):
    """Run one concurrency setting and write its artifacts."""
    out = root / f"k{k}"
    out.mkdir()
    server = LlamaServer(config["server"])
    process = server.start()
    try:
        wait_for_server(process, config["server"])
        manifest = create_manifest(
            args, out, k, content, url, repo, commit, dirty, process.pid, config
        )

        # Sample the server in parallel with task execution; stop and join the
        # collector even if the scheduler exits with an exception.
        stop = threading.Event()
        samples = []
        errors = []

        def collect():
            """Collect server-tree samples until stopped or the PID disappears."""
            try:
                for sample in monitor_process(pid=process.pid, interval=0.02):
                    samples.append(dict(run_id=out.name, **sample))
                    if stop.is_set() or sample["rss"] == "DEAD":
                        break
            except Exception as exc:
                errors.append(repr(exc))

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()
        try:
            rows, wall = run_tasks(tasks, k, out, url=url, timeout=args.timeout)
        finally:
            stop.set()
            thread.join()
            write_monitor_artifacts(out, samples, errors)

        # Percentiles include completed tasks only; status counts retain failures.
        return create_summary(out, k, rows, wall, samples, errors, manifest["mode"])
    finally:
        server.stop()


def main():
    # Writes the combined summaries to root/comparison.json.
    args = parse_args()
    root, content, tasks = prepare_output(args)
    config = load_config()
    server_config = config["server"]
    url = args.url or (
        f"http://{server_config['host']}:{server_config['port']}"
        "/v1/chat/completions"
    )
    repo, commit, dirty = collect_repository_metadata()

    # Run concurrency settings sequentially against the same loaded workload.
    summaries = [
        run_one(args, root, content, tasks, url, repo, commit, dirty, config, k)
        for k in args.concurrency
    ]
    write_json(root / "comparison.json", summaries)
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
