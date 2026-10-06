from __future__ import annotations

import os
import platform
from pathlib import Path

from .version import APP_NAME


APP_DIR_NAME = "".join(part for part in APP_NAME if part.isalnum())
CONFIG_ENV_VAR = "HISTORY_DASHBOARD_CONFIG_DIR"
LOG_ENV_VAR = "HISTORY_DASHBOARD_LOG_DIR"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def user_config_dir() -> Path:
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser()

    system = platform.system()
    home = Path.home()
    if system == "Windows":
        base = os.environ.get("APPDATA")
        return (Path(base).expanduser() if base else home / "AppData" / "Roaming") / APP_DIR_NAME
    if system == "Darwin":
        return home / "Library" / "Application Support" / APP_DIR_NAME

    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base).expanduser() if base else home / ".config") / APP_DIR_NAME


def user_config_path() -> Path:
    return user_config_dir() / "config.json"


def user_log_dir() -> Path:
    override = os.environ.get(LOG_ENV_VAR)
    if override:
        return Path(override).expanduser()

    system = platform.system()
    home = Path.home()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base).expanduser() if base else home / "AppData" / "Local") / APP_DIR_NAME / "logs"
    if system == "Darwin":
        return home / "Library" / "Logs" / APP_DIR_NAME

    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base).expanduser() if base else home / ".local" / "state") / APP_DIR_NAME / "logs"


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
