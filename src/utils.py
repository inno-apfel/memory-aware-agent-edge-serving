"""Shared project configuration and local server process discovery."""

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
    """Find the sole non-Python process matching ``name_hint`` and return its PID.

    This convenience discovery is ambiguous when multiple llama servers run;
    callers should pass an explicit PID for reproducible measurements. Raises
    ``RuntimeError`` unless exactly one candidate is found.
    """
    matches = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if name_hint in (p.info["name"] or "") or name_hint in cmd:
            if "python" not in (
                p.info["name"] or ""
            ):  # skip this script / the notebook
                matches.append((p.info["pid"], cmd))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one server, found {len(matches)}; use explicit PID"
        )
    return matches[0][0]
