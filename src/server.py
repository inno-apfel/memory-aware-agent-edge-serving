"""Manage the configured llama.cpp server process.

Run ``python -m src.server`` to start the server in the foreground. Edit
``config.yml`` to change the model, endpoint, context allocation, or parallel
slots.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from src.utils import CONFIG_PATH, load_config


def load_launch_config(path=CONFIG_PATH, binary=None, library_path=None):
    """Resolve profile model paths relative to YAML; keep PATH commands portable."""
    path = Path(path).resolve()
    config = load_config(path)
    server = dict(config['server'])
    if server.get('model_file'):
        server['model_file'] = str((path.parent / server['model_file']).resolve())
    if binary:
        server['command'] = [str(Path(binary).resolve())]
    if library_path:
        server['environment'] = dict(server.get('environment', {}), LD_LIBRARY_PATH=library_path)
    if config.get('runtime', {}).get('expected_version_text'):
        server['expected_version_text'] = config['runtime']['expected_version_text']
    config['server'] = server
    return config


class LlamaServer:
    """Start and stop a llama.cpp server using its server configuration."""

    def __init__(self, server_config):
        self.server_config = server_config
        self.process = None

    def start(self):
        """Start the server process and return its ``Popen`` handle."""
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("llama.cpp server is already running")

        cmd = self.build_command()
        environment = self.launch_environment()
        self.verify_profile(environment)
        print("launching:", " ".join(cmd))
        self.process = subprocess.Popen(cmd, **({'env': environment} if environment is not None else {}))
        print(f"llama.cpp server PID: {self.process.pid}")
        return self.process

    def build_command(self):
        server = self.server_config
        cmd = server.get('command', ['llama', 'serve'])
        if not isinstance(cmd, list) or not cmd or not all(isinstance(v, str) and v for v in cmd):
            raise ValueError('server.command must be a nonempty list of strings')
        cmd = list(cmd)
        if server.get('model_file'):
            cmd += ['-m', server['model_file']]
        else:
            cmd += ['-hf', server['model']]
        device = server.get('device', 'none')
        if device is not None:
            cmd += ['--device', str(device)]
        cmd += ['--gpu-layers', str(server.get('gpu_layers', 0))]
        if server.get('metrics', True):
            cmd += ['--metrics']
        cmd += [
            "-np", str(server["parallel_slots"]),
            "-c", str(server["context_size"]),
            "--host", server["host"],
            "--port", str(server["port"]),
        ]
        for key, flag in [('flash_attn', '-fa'), ('threads', '-t'), ('threads_batch', '-tb'), ('cache_ram', '--cache-ram')]:
            if key in server:
                cmd += [flag, str(server[key])]
        for key, flag in [('cache_idle_slots', 'cache-idle-slots'), ('context_shift', 'context-shift'), ('kv_unified', 'kv-unified')]:
            if key in server:
                if not isinstance(server[key], bool):
                    raise ValueError(f'server.{key} must be boolean')
                cmd += ['--' + ('' if server[key] else 'no-') + flag]
        return cmd

    def launch_environment(self):
        server = self.server_config
        if not server.get('environment') and not server.get('environment_unset'):
            return None
        env = os.environ.copy()
        env.update(server.get('environment', {}))
        for name in server.get('environment_unset', []):
            env.pop(name, None)
        return env

    def verify_profile(self, environment=None):
        """Pinned GPU profiles reject wrong models/builds before launching."""
        server = self.server_config
        if server.get('model_sha256'):
            with Path(server['model_file']).open('rb') as f:
                actual = hashlib.file_digest(f, 'sha256').hexdigest()
            if actual != server['model_sha256']:
                raise RuntimeError('Model SHA256 does not match the frozen GPU profile')
        if server.get('expected_version_text'):
            result = subprocess.run(self.build_command()[:len(server.get('command', ['llama', 'serve']))] + ['--version'],
                                    env=environment, capture_output=True, text=True, timeout=15, check=True)
            version = result.stdout + result.stderr
            if not all(part in version for part in server['expected_version_text']):
                raise RuntimeError('Runtime version does not match frozen GPU profile: ' + version.strip())

    def stop(self):
        """Gracefully stop the server process if it is running."""
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
        self.process.wait()
        self.process = None


def main(argv=None):
    """Keep the server in the foreground when run as a module."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG_PATH)
    parser.add_argument('--binary', help='Override server command with a local llama-server binary')
    parser.add_argument('--library-path', help='LD_LIBRARY_PATH for the Linux runtime')
    parser.add_argument('--dry-run', action='store_true', help='Print resolved command without loading a model')
    args = parser.parse_args(argv)
    config = load_launch_config(args.config, args.binary, args.library_path)
    server = LlamaServer(config["server"])
    if args.dry_run:
        print(json.dumps(dict(command=server.build_command(), runtime=config.get('runtime'),
                             environment_keys=list(config['server'].get('environment', {})),
                             environment_unset=config['server'].get('environment_unset', [])), indent=2))
        return 0
    process = server.start()
    try:
        return process.wait()
    except KeyboardInterrupt:
        server.stop()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
