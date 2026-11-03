"""Run one CPU-only, swap-free model trial with an enforced cgroup budget.

Fresh service per invocation; limits apply before exec. Native model memory is
loaded with --load-mode none so previously charged mappings cannot hide weights.
The client and all collectors remain outside the service's cgroup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import psutil
import requests
from src.memory_budget import CgroupMonitor, MemoryBudget, snapshot


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--server', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--libraries', required=True, help='Colon-separated LD_LIBRARY_PATH')
    p.add_argument('--budget-mib', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workload', type=Path, required=True)
    p.add_argument('--concurrency', type=int, default=2)
    p.add_argument('--port', type=int, default=9931)
    p.add_argument('--startup-timeout', type=float, default=180)
    p.add_argument('--trial-timeout', type=float, default=900)
    p.add_argument('--http-timeout', type=float, default=60)
    a = p.parse_args()
    if not (1 <= a.concurrency <= 10) or min(a.startup_timeout, a.trial_timeout, a.http_timeout) <= 0:
        p.error('Invalid concurrency or timeout')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', a.port)) == 0:
            raise RuntimeError('Requested port is already in use; refusing to touch existing service')
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / 'workload.jsonl').write_bytes(a.workload.read_bytes())
    group = MemoryBudget(a.budget_mib * 1024**2)
    initial = group.create()
    monitor = CgroupMonitor(group.path, a.output / 'cgroup.jsonl')
    command = [str(a.server.resolve()), '-m', str(a.model.resolve()), '--host', '127.0.0.1',
               '--port', str(a.port), '--device', 'none', '-ngl', '0', '--load-mode', 'none',
               '--metrics', '-np', '10', '-c', '40960', '-t', '8', '-tb', '8',
               '--cache-ram', '0', '--no-cache-idle-slots', '--no-context-shift', '--no-kv-unified']
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = a.libraries
    git = ['git', '-c', f'safe.directory={Path.cwd().as_posix()}']
    manifest = dict(budget_mib=a.budget_mib, concurrency=a.concurrency, cgroup=str(group.path),
        cgroup_initial=initial, command=command, start_wall=time.time(),
        model_sha256=hashlib.file_digest(a.model.open('rb'), 'sha256').hexdigest(),
        workload_sha256=hashlib.sha256(a.workload.read_bytes()).hexdigest(),
        source_sha256={str(f): hashlib.sha256(f.read_bytes()).hexdigest()
            for folder in ('src', 'scripts', 'experiments', 'workloads') for f in Path(folder).glob('*.py')},
        git_commit=subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip(),
        git_dirty=bool(subprocess.check_output(git + ['status', '--porcelain'], text=True).strip()),
        runtime_version=subprocess.run([str(a.server.resolve()), '--version'], env=env,
            capture_output=True, text=True).stderr,
        ram_total=psutil.virtual_memory().total, logical_cpus=psutil.cpu_count(),
        limits_scope='service tree DRAM, not client, host, or VRAM',
        timeouts=dict(startup=a.startup_timeout, whole_worker=a.trial_timeout, http_inactivity=a.http_timeout))
    write(a.output / 'manifest.json', manifest)
    process = worker = None
    outcome = dict(status='not_started')
    monitor.start()
    try:
        with (a.output / 'server.log').open('xb') as log:
            process = subprocess.Popen([sys.executable, '-m', 'scripts.cgroup_exec', str(group.path), '--', *command],
                stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            manifest['server_pid'] = process.pid
            manifest['process_created'] = psutil.Process(process.pid).create_time()
            write(a.output / 'manifest.json', manifest)
            started = time.monotonic()
            deadline = started + a.startup_timeout
            base = f'http://127.0.0.1:{a.port}'
            ready = False
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if requests.get(base + '/health', timeout=1).status_code == 200:
                        ready = True
                        break
                except requests.RequestException:
                    pass
                time.sleep(.2)
            outcome.update(startup_s=time.monotonic()-started, ready=ready)
            if not ready:
                outcome['status'] = 'startup_exit' if process.poll() is not None else 'startup_timeout'
            else:
                members = (group.path / 'cgroup.procs').read_text().split()
                if str(process.pid) not in members:
                    raise RuntimeError('Server PID is not inside the budget group')
                write(a.output / 'ready_snapshot.json', snapshot(group.path))
                with (a.output / 'worker.log').open('xb') as clientlog:
                    worker = subprocess.Popen([sys.executable, '-m', 'scripts.memory_trial_worker',
                        '--pid', str(process.pid), '--output', str(a.output), '--workload', str(a.workload),
                        '--concurrency', str(a.concurrency), '--url', base + '/v1/chat/completions',
                        '--timeout', str(a.http_timeout)], stdout=clientlog, stderr=subprocess.STDOUT,
                        start_new_session=True)
                    try:
                        outcome['worker_returncode'] = worker.wait(timeout=a.trial_timeout)
                        outcome['status'] = 'finished' if worker.returncode == 0 else 'worker_error'
                    except subprocess.TimeoutExpired:
                        outcome['status'] = 'trial_timeout'
                        os.killpg(worker.pid, signal.SIGTERM)
                        worker.wait(timeout=10)
                outcome['model_alive_after_worker'] = process.poll() is None
    except Exception as exc:
        outcome.update(status='orchestration_error', error=repr(exc))
        raise
    finally:
        if worker and worker.poll() is None:
            os.killpg(worker.pid, signal.SIGKILL)
            worker.wait()
        outcome['before_shutdown'] = snapshot(group.path)
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    (group.path / 'cgroup.kill').write_text('1')
                    process.wait(timeout=10)
            outcome['server_returncode'] = process.returncode
        monitor.close()
        outcome.update(final=snapshot(group.path), monitor_errors=monitor.errors, end_wall=time.time())
        outcome['oom_kill'] = outcome['final']['memory.events'].get('oom_kill', 0)
        if outcome['oom_kill']:
            outcome['execution_status'] = outcome['status']
            outcome['status'] = 'service_oom'
        write(a.output / 'outcome.json', outcome)
        group.close()
    print(json.dumps(dict(output=str(a.output), status=outcome['status'], oom_kill=outcome['oom_kill'])), flush=True)


if __name__ == '__main__':
    main()
