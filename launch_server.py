"""Launch the configured llama.cpp server in the foreground.

Usage: ``python launch_server.py``. Edit ``config.yml`` to change the model,
endpoint, context allocation, or parallel slots. The launcher passes those
settings to the installed ``llama`` CLI and waits for the server process to exit.
Run the benchmark in a separate terminal so the launcher remains alive.
"""
import subprocess

from src.utils import load_config

server = load_config().get("server")

cmd = [
    "llama", "serve",
    "-hf", server["model"],
    "--metrics",
    "-np", str(server["parallel_slots"]),
    "-c", str(server["context_size"]),
    "--host", server["host"],
    "--port", str(server["port"]),
]

print("launching:", " ".join(cmd))
subprocess.run(cmd)
