"""Sample host resource use for a model server process and its descendants.

RSS/USS/VMS are process-tree totals in bytes; system availability and swap are
host-wide byte counts. CPU percent is the root process's value since its prior
sample. These fields do not report GPU allocation or llama.cpp KV occupancy.
"""

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


def run_monitor(stop_event, samples, pid=None, interval=0.2):
    """Append samples to a caller-owned list until stopped or the process exits.

    This small adapter supports threaded callers. The final ``DEAD`` sample is
    appended when the process exits; ``stop_event`` is checked after each sample.
    """
    monitor = monitor_process(pid=pid, interval=interval)
    for sample in monitor:
        samples.append(sample)
        if stop_event.is_set():
            break


def monitor_process(
    pid: int | None = None, interval: float = 0.2
) -> Iterator[dict[str, MetricValue]]:
    """Yield process-tree and host-memory snapshots until ``pid`` exits.

    When ``pid`` is omitted, process discovery requires exactly one matching
    llama process. Use an explicit PID for benchmark runs to avoid ambiguity.
    ``interval`` is the delay between samples. The terminal sample uses
    ``rss="DEAD"`` and empty strings for metrics unavailable after exit.
    """
    if interval <= 0:
        raise ValueError("interval must be greater than zero")

    process = psutil.Process(get_server_pid() if pid is None else pid)
    process.cpu_percent()  # Prime CPU measurement; the first value is always 0.

    while True:
        try:
            # Aggregate the server and all current descendants; llama.cpp may
            # move work into child processes depending on how it was launched.
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
                "t_mono": time.perf_counter(),
                "rss": "DEAD",
                "uss": "",
                "vms": "",
                "sys_avail": "",
                "swap_used": "",
                "cpu_pct": "",
            }
            break

        # Keep wall and monotonic clocks together so memory samples can align
        # with the scheduler timeline while retaining external timestamps.
        yield {
            "t_wall": time.time(),
            "t_mono": time.perf_counter(),
            "rss": rss,
            "uss": uss,
            "vms": vms,
            "sys_avail": psutil.virtual_memory().available,
            "swap_used": psutil.swap_memory().used,
            "cpu_pct": cpu,
        }
        time.sleep(interval)
