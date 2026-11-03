"""Enter an experiment-owned cgroup before exec, without preexec_fn threads."""
import os
from pathlib import Path
import sys


def main():
    path = Path(sys.argv[1]).resolve()
    root = Path('/sys/fs/cgroup').resolve()
    if path.parent != root or not path.name.startswith('agent-memory-'):
        raise ValueError('Only a direct experiment-owned cgroup is allowed')
    command = sys.argv[2:]
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        raise ValueError('Missing command')
    (path / 'cgroup.procs').write_text(str(os.getpid()))
    own = Path('/proc/self/cgroup').read_text()
    if f'0::/{path.name}\n' not in own:
        raise RuntimeError('Cgroup membership verification failed')
    os.execvpe(command[0], command, os.environ)


if __name__ == '__main__':
    main()
