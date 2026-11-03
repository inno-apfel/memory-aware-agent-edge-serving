"""Warmup and measured requests outside the model's cgroup budget."""
import argparse
import json
from pathlib import Path
import threading

from src.monitor import monitor_process
from src.resource_monitor import ResourceMonitor
from src.runner import run_tasks
from workloads.memory_budget import generate_memory_tasks


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pid', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workload', type=Path, required=True)
    p.add_argument('--url', required=True)
    p.add_argument('--concurrency', type=int, default=2)
    p.add_argument('--timeout', type=float, default=60)
    a = p.parse_args()
    warm = a.output / 'warmup'
    warm.mkdir()
    run_tasks(generate_memory_tasks(4, seed=101), a.concurrency, warm, url=a.url, timeout=a.timeout)
    out = a.output / 'measured'
    out.mkdir()
    tasks = [json.loads(line) for line in a.workload.read_text().splitlines() if line.strip()]
    stop = threading.Event()
    errors = []
    def collect():
        import csv
        try:
            with (out / 'memory.csv').open('x', newline='') as f:
                writer = None
                for row in monitor_process(pid=a.pid, interval=.1):
                    if writer is None:
                        writer = csv.DictWriter(f, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    f.flush()
                    if stop.is_set() or row['rss'] == 'DEAD':
                        break
        except Exception as exc:
            errors.append(repr(exc))
    thread = threading.Thread(target=collect, daemon=True)
    diagnostics = ResourceMonitor(a.pid, out)
    thread.start()
    diagnostics.start()
    try:
        rows, wall = run_tasks(tasks, a.concurrency, out, url=a.url, timeout=a.timeout)
        (out / 'worker_summary.json').write_text(json.dumps(dict(tasks=len(rows),
            completed=sum(r['status'] == 'completed' for r in rows), drain_s=wall), indent=2))
    finally:
        stop.set()
        thread.join()
        diagnostics.close()
        (out / 'monitor_errors.json').write_text(json.dumps(errors))


if __name__ == '__main__':
    main()
