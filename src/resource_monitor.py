"""Optional Linux bottleneck telemetry; unavailable counters are never zeros.

CPU thread percentages use one logical CPU = 100%. PSI total is cumulative
microseconds stalled. GPU counters cover the whole device, including other apps.
"""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

import psutil


def parse_psi(text):
    return {parts[0]: {k: float(v) for k, v in
            (item.split("=") for item in parts[1:])}
            for line in text.splitlines() if (parts := line.split())}


def thread_deltas(previous, current, elapsed):
    # A new thread has no baseline: omit its first interval, never infer zero.
    return {tid: max(0, seconds - previous[tid]) / elapsed * 100
            for tid, seconds in current.items() if tid in previous and elapsed > 0}


def core_percent(previous, current):
    """Normalize raw Linux time deltas; guest is already included in user/nice."""
    delta = {k: max(0, v - previous.get(k, v)) for k, v in current.items()}
    total = sum(v for k, v in delta.items() if k not in ("guest", "guest_nice"))
    if total <= 0:
        return None
    wait = delta.get("iowait", 0)
    busy = max(0, total - delta.get("idle", 0) - wait)
    return busy / total * 100, wait / total * 100, total


class ResourceMonitor:
    def __init__(self, pid, output, interval=0.5):
        if interval <= 0:
            raise ValueError("interval must be positive")
        self.pid, self.output, self.interval = pid, Path(output), interval
        self.stop = threading.Event()
        self.thread = None
        self.errors = []

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
        (self.output / "resource_errors.json").write_text(json.dumps(self.errors, indent=2))

    def _run(self):
        try:
            self._collect()
        except Exception as exc:
            self.errors.append(repr(exc))

    def _collect(self):
        proc = psutil.Process(self.pid)
        client = psutil.Process()
        client.cpu_percent()
        gpu = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
        fields = ["utilization.gpu", "utilization.memory", "memory.used", "memory.free",
                  "power.draw", "power.limit", "clocks.sm", "clocks.mem", "temperature.gpu"]
        metadata = dict(collector_version=2, pid=self.pid, process_created=proc.create_time(), command=proc.cmdline(),
                        logical_cpus=psutil.cpu_count(), affinity=proc.cpu_affinity(),
                        interval_s=self.interval, gpu_scope="whole device",
                        thread_scope="server parent process; not child processes",
                        cpu_unit="one logical CPU=100%; system core percentages are per-core",
                        gpu_fields=fields, psi_unit="total: cumulative microseconds",
                        missing="empty field or omitted JSON key, never zero")
        (self.output / "resource_metadata.json").write_text(json.dumps(metadata, indent=2))
        handles = []
        def writer(name, columns):
            f = (self.output / name).open("w", newline="")
            handles.append(f)
            w = csv.writer(f); w.writerow(columns)
            return w
        try:
            core = writer("cpu_cores.csv", ["wall_time", "monotonic", "cpu", "busy_pct", "iowait_pct", "total_delta_s"])
            threads = writer("cpu_threads.csv", ["wall_time", "monotonic", "tid", "name", "cpu_pct"])
            gpucsv = writer("gpu.csv", ["wall_time", "sample_end_wall", "gpu_index"] + fields)
            pressure = (self.output / "pressure.jsonl").open("w")
            handles.append(pressure)
            old_threads = {t.id: t.user_time + t.system_time for t in proc.threads()}
            previous_time = time.perf_counter()
            old_cores = psutil.cpu_times(percpu=True)
            while not self.stop.wait(self.interval):
                started = time.perf_counter(); wall = time.time()
                cpus = psutil.cpu_times(percpu=True)
                for i, (before, after) in enumerate(zip(old_cores, cpus)):
                    values = core_percent(before._asdict(), after._asdict())
                    if values is not None:
                        core.writerow([wall, started, i, *values])
                old_cores = cpus
                now_threads = {t.id: t.user_time + t.system_time for t in proc.threads()}
                for tid, pct in thread_deltas(old_threads, now_threads, started-previous_time).items():
                    try:
                        name = Path(f"/proc/{self.pid}/task/{tid}/comm").read_text().strip()
                    except OSError:
                        name = ""
                    threads.writerow([wall, started, tid, name, pct])
                old_threads, previous_time = now_threads, started
                mem, swap = psutil.virtual_memory(), psutil.swap_memory()
                row = dict(wall_time=wall, monotonic=started, total_bytes=mem.total,
                           available_bytes=mem.available, swap_used_bytes=swap.used,
                           swap_in_bytes=swap.sin, swap_out_bytes=swap.sout,
                           collector_client_pid=client.pid, collector_client_cpu_pct=client.cpu_percent())
                for resource in ("cpu", "memory", "io"):
                    p = Path("/proc/pressure") / resource
                    if p.exists():
                        row[resource + "_psi"] = parse_psi(p.read_text())
                p = Path("/proc/vmstat")
                if p.exists():
                    values = dict(line.split() for line in p.read_text().splitlines())
                    row["vmstat"] = {k: int(v) for k, v in values.items()
                                     if k in ("pgmajfault", "pswpin", "pswpout", "oom_kill")
                                     or k.startswith(("pgscan_", "pgsteal_", "allocstall"))}
                pressure.write(json.dumps(row) + "\n")
                try:
                    raw = subprocess.check_output([gpu, "--query-gpu=" + ",".join(fields),
                                                   "--format=csv,noheader,nounits"], text=True, timeout=3)
                    end = time.time()
                    for index, line in enumerate(raw.splitlines()):
                        gpucsv.writerow([wall, end, index] + [x.strip() for x in line.split(",")])
                except (OSError, subprocess.SubprocessError) as exc:
                    self.errors.append(dict(wall_time=wall, gpu_error=repr(exc)))
                for f in handles:
                    f.flush()
        finally:
            for f in handles:
                f.close()
