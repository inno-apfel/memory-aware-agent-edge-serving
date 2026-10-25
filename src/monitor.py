# monitor.py

"""Monitor a process tree and optionally write its samples to CSV."""

import psutil

from collections.abc import Iterator
import time

from src.utils import get_server_pid

FIELDS = (
    "t_wall",
    "t_mono",
    "rss",
    "uss",
    "vms",
    "sys_avail",
    "swap_used",
    "cpu_pct",
)
MetricValue = float | int | str

pid = get_server_pid()

def run_monitor(stop_event, samples):
    monitor = monitor_process()
    for sample in monitor:
        samples.append(sample)
        if stop_event.is_set():
            break

def monitor_process(pid: int = pid, interval: float = 0.2) -> Iterator[dict[str, MetricValue]]:
    """Yield process-tree resource samples until the process exits.

    Each sample is a dictionary with the same fields as the CSV output. The
    final sample has ``rss="DEAD"`` and empty values for the other metrics.
    """
    if interval <= 0:
        raise ValueError("interval must be greater than zero")

    process = psutil.Process(pid)
    process.cpu_percent()  # Prime CPU measurement; the first value is always 0.

    while True:
        try:
            if process.status() == psutil.STATUS_ZOMBIE:
                raise psutil.NoSuchProcess(pid)
            processes = [process] + process.children(recursive=True)
            rss = sum(child.memory_info().rss for child in processes)
            uss = sum(child.memory_full_info().uss for child in processes)
            vms = sum(child.memory_info().vms for child in processes)
            cpu = process.cpu_percent()
        except psutil.NoSuchProcess:
            yield {
                "t_wall": time.time(),
                "t_mono": time.monotonic(),
                "rss": "DEAD",
                "uss": "",
                "vms": "",
                "sys_avail": "",
                "swap_used": "",
                "cpu_pct": "",
            }
            break

        yield {
            "t_wall": time.time(),
            "t_mono": time.monotonic(),
            "rss": rss,
            "uss": uss,
            "vms": vms,
            "sys_avail": psutil.virtual_memory().available,
            "swap_used": psutil.swap_memory().used,
            "cpu_pct": cpu,
        }
        time.sleep(interval)