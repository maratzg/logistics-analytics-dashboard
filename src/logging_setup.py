from __future__ import annotations

import logging
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .platform_paths import APP_DIR_NAME, ensure_directory, user_log_dir


LOG_FILE_NAME = "app.log"
MAX_LOG_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3
_ACTIVE_LOG_DIR: Path | None = None


def configure_logging(*, log_dir: str | Path | None = None, level: int = logging.INFO, console: bool = True) -> Path:
    global _ACTIVE_LOG_DIR
    preferred_directory = Path(log_dir).expanduser() if log_dir is not None else user_log_dir()
    try:
        directory = ensure_directory(preferred_directory)
    except OSError:
        directory = ensure_directory(Path(tempfile.gettempdir()) / APP_DIR_NAME / "logs")
    log_path = directory / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(level)

    if not any(getattr(handler, "_history_dashboard_file_handler", False) for handler in root.handlers):
        try:
            file_handler = _file_handler(log_path, level)
        except OSError:
            directory = ensure_directory(Path(tempfile.gettempdir()) / APP_DIR_NAME / "logs")
            log_path = directory / LOG_FILE_NAME
            file_handler = _file_handler(log_path, level)
        file_handler.setLevel(level)
        file_handler._history_dashboard_file_handler = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
    _ACTIVE_LOG_DIR = directory

    if console and not any(getattr(handler, "_history_dashboard_console_handler", False) for handler in root.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        console_handler._history_dashboard_console_handler = True  # type: ignore[attr-defined]
        root.addHandler(console_handler)

    logging.captureWarnings(True)
    logging.getLogger(__name__).info("Logging initialized: %s", log_path)
    return log_path


def current_log_dir() -> Path:
    return _ACTIVE_LOG_DIR or user_log_dir()


def _file_handler(log_path: Path, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    return handler
