"""
Persistent configuration stored at ~/.config/purpleteam/config.json.
Stores Proxmox connection defaults so they don't need to be re-entered each run.
"""
import json
import os
import stat
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "purpleteam"
CONFIG_FILE = CONFIG_DIR / "config.json"

FIELDS = ["host", "user", "token_name", "token_value", "node"]


def load() -> dict:
    """Return saved config, or empty dict if none exists."""
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open() as f:
        return json.load(f)


def save(cfg: dict) -> None:
    """Write config to disk with restricted permissions (owner read/write only)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        json.dump(cfg, f, indent=2)
    # Restrict to owner-only on POSIX; no-op on Windows
    try:
        os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except AttributeError:
        pass


def path() -> Path:
    return CONFIG_FILE
