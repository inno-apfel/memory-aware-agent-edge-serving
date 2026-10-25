# utils.py

"""Shared configuration helpers for the ``src`` modules."""

import psutil
import yaml

from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yml"

def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Read a YAML configuration file and return it as a dictionary.

    Raises:
        ValueError: If the file does not contain a mapping at the top level.
    """
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise ValueError(f"Expected a mapping at the top level of {config_path}")
    return config

def get_server_pid(name_hint="llama"):
    """Read and return the endpoint URL from a YAML configuration file.
    Returns the PID of the first process whose name or command line contains the given hint.
    """
    matches = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if name_hint in (p.info["name"] or "") or name_hint in cmd:
            if "python" not in (p.info["name"] or ""):   # skip this script / the notebook
                matches.append((p.info["pid"], cmd))
    return matches[0][0]