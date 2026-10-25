"""Shared configuration helpers for the ``src`` modules."""

from pathlib import Path

import psutil

import yaml


def load_url(config_path: Path = Path("config.yml")) -> str:
    """Read and return the endpoint URL from a YAML configuration file.

    Raises:
        ValueError: If the configuration is not a mapping with a string ``url``.
    """
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict) or not isinstance(config.get("url"), str):
        raise ValueError(f"Expected a 'url' string in {config_path}")
    return config["url"]

def find_server_pid(name_hint="llama"):
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