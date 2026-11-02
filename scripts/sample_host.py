"""Supplement WSL telemetry with Windows-host RAM and per-core CPU (no admin)."""
import argparse
import json
from pathlib import Path
import time
import psutil


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--stop-file", required=True)
    a = p.parse_args()
    psutil.cpu_percent(percpu=True)
    with Path(a.output).open("x") as f:
        while not Path(a.stop_file).exists():
            mem = psutil.virtual_memory()
            try:
                swap_used, swap_error = psutil.swap_memory().used, None
            except Exception as exc:
                swap_used, swap_error = None, str(exc)
            f.write(json.dumps(dict(wall_time=time.time(), cpu_pct_per_core=psutil.cpu_percent(percpu=True),
                    ram_total=mem.total, ram_available=mem.available,
                    swap_used=swap_used, swap_error=swap_error)) + "\n")
            f.flush()
            time.sleep(1)


if __name__ == "__main__":
    main()
