"""Linux cgroup v2 limits for a single owned model-service process tree."""
import json
from pathlib import Path
import threading
import time
import uuid


def key_values(text):
    return {k: int(v) for k, v in (line.split() for line in text.splitlines())}


def parse_pressure(text):
    return {parts[0]: {k: float(v) for k, v in
            (item.split('=') for item in parts[1:])}
            for line in text.splitlines() if (parts := line.split())}


def snapshot(path):
    path = Path(path)
    result = {'wall_time': time.time(), 'monotonic': time.monotonic()}
    for name in ('memory.current', 'memory.peak', 'memory.max', 'memory.high',
                 'memory.swap.max', 'memory.swap.current'):
        text = (path / name).read_text().strip()
        result[name] = int(text) if text != 'max' else text
    for name in ('memory.events', 'memory.stat', 'cgroup.events'):
        result[name] = key_values((path / name).read_text())
    result['memory.pressure'] = parse_pressure((path / 'memory.pressure').read_text())
    return result


class MemoryBudget:
    def __init__(self, limit_bytes, root='/sys/fs/cgroup'):
        if limit_bytes <= 0:
            raise ValueError('Memory budget must be positive')
        self.limit = int(limit_bytes)
        self.root = Path(root)
        self.path = self.root / ('agent-memory-' + uuid.uuid4().hex)

    def create(self):
        if 'memory' not in (self.root / 'cgroup.subtree_control').read_text().split():
            raise RuntimeError('Parent must already delegate the memory controller')
        self.path.mkdir()
        try:
            (self.path / 'memory.max').write_text(str(self.limit))
            (self.path / 'memory.swap.max').write_text('0')
            (self.path / 'memory.oom.group').write_text('1')
            actual = snapshot(self.path)
            if actual['memory.max'] != self.limit or actual['memory.swap.max'] != 0:
                raise RuntimeError('Memory limit readback mismatch')
            return actual
        except BaseException:
            self.path.rmdir()
            raise

    def close(self):
        if not self.path.exists():
            return
        if (self.path / 'cgroup.procs').read_text().strip():
            raise RuntimeError('Refusing to remove a populated cgroup')
        self.path.rmdir()


class CgroupMonitor:
    def __init__(self, path, output, interval=.25):
        self.path, self.output, self.interval = Path(path), Path(output), interval
        self.stop = threading.Event()
        self.errors = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        with self.output.open('x') as f:
            while True:
                try:
                    f.write(json.dumps(snapshot(self.path)) + '\n')
                    f.flush()
                except Exception as exc:
                    self.errors.append(repr(exc))
                if self.stop.wait(self.interval):
                    break

    def close(self):
        self.stop.set()
        self.thread.join()
