"""Manage the configured llama.cpp server process.

Run ``python -m src.server`` to start the server in the foreground. Edit
``config.yml`` to change the model, endpoint, context allocation, or parallel
slots.
"""
import subprocess

from src.utils import load_config


class LlamaServer:
    """Start and stop a llama.cpp server using its server configuration."""

    def __init__(self, server_config):
        self.server_config = server_config
        self.process = None

    def start(self):
        """Start the server process and return its ``Popen`` handle."""
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("llama.cpp server is already running")

        server = self.server_config
        cmd = [
            "llama", "serve",
            "-hf", server["model"],
            "--device", "none",
            "--gpu-layers", "0",
            "--metrics",
            "-np", str(server["parallel_slots"]),
            "-c", str(server["context_size"]),
            "--host", server["host"],
            "--port", str(server["port"]),
        ]
        print("launching:", " ".join(cmd))
        self.process = subprocess.Popen(cmd)
        print(f"llama.cpp server PID: {self.process.pid}")
        return self.process

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


def main():
    """Keep the server in the foreground when run as a module."""
    config = load_config()
    server = LlamaServer(config["server"])
    process = server.start()
    try:
        return process.wait()
    except KeyboardInterrupt:
        server.stop()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
