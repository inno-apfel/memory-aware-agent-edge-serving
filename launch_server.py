# launch_server.py: usage: python launch_server.py
import subprocess

from src.utils import load_config

server = load_config().get("server")

cmd = ["llama", "serve",
       "-hf", server["model"],
       "--metrics",
       "-np", str(server["parallel_slots"]),
       "-c", str(server["context_size"]),
       "--host", server["host"],
       "--port", str(server["port"])]

print("launching:", " ".join(cmd))
subprocess.run(cmd)