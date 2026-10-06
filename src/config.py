from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .platform_paths import project_root, user_config_path as default_user_config_path


DEFAULT_REQUIRED_SHEETS = ["WEEKLY", "LOG_HISTORY"]
DEFAULT_OPTIONAL_SHEETS = ["TEMPLATE", "MASTER_DATA", "REPORT", "README"]
DEFAULT_MAX_ISSUE_DETAILS = 25
DEFAULT_EXPECTED_WORKBOOK_FILENAME = "logistics_operations_demo.xlsm"
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True, slots=True)
class AppConfig:
    workbook_path: Path | None = None
    required_sheets: list[str] = field(default_factory=lambda: list(DEFAULT_REQUIRED_SHEETS))
    optional_sheets: list[str] = field(default_factory=lambda: list(DEFAULT_OPTIONAL_SHEETS))
    max_issue_details: int = DEFAULT_MAX_ISSUE_DETAILS
    expected_workbook_filename: str = DEFAULT_EXPECTED_WORKBOOK_FILENAME
    user_config_path: Path | None = None
    project_config_path: Path | None = None
    config_errors: list[str] = field(default_factory=list)
    config_warnings: list[str] = field(default_factory=list)


def load_config(
    config_path: str | Path | None = None,
    *,
    user_config_path: str | Path | None = None,
) -> AppConfig:
    """Load layered project defaults and per-user settings.

    Project config is stored with the copied project and should contain safe
    defaults only. The workbook location is normally saved in the user's
    application-data config file after first-run selection.
    """

    project_path = _resolve_project_config_path(config_path)
    user_path = _resolve_user_config_path(user_config_path)

    project_raw, project_errors, project_warnings = _read_json_object(project_path, "project", missing_is_error=False)
    user_raw, user_errors, user_warnings = _read_json_object(user_path, "user", missing_is_error=False)

    raw = _default_raw_config()
    raw.update(project_raw)
    raw.update(user_raw)

    workbook_path, workbook_warnings = _resolve_workbook_path(project_raw, user_raw, project_path, user_path)
    return AppConfig(
        workbook_path=workbook_path,
        required_sheets=_string_list(raw.get("required_sheets"), DEFAULT_REQUIRED_SHEETS, "required_sheets"),
        optional_sheets=_string_list(raw.get("optional_sheets"), DEFAULT_OPTIONAL_SHEETS, "optional_sheets"),
        max_issue_details=_positive_int(raw.get("max_issue_details"), DEFAULT_MAX_ISSUE_DETAILS, "max_issue_details"),
        expected_workbook_filename=str(raw.get("expected_workbook_filename") or DEFAULT_EXPECTED_WORKBOOK_FILENAME),
        user_config_path=user_path,
        project_config_path=project_path,
        config_errors=project_errors + user_errors,
        config_warnings=project_warnings + user_warnings + workbook_warnings,
    )


def save_workbook_path(
    workbook_path: str | Path,
    *,
    user_config_path: str | Path | None = None,
    existing_config: AppConfig | None = None,
) -> AppConfig:
    """Persist the selected workbook path in the per-user config file only."""

    user_path = _resolve_user_config_path(user_config_path or (existing_config.user_config_path if existing_config else None))
    raw, _, _ = _read_json_object(user_path, "user", missing_is_error=False)
    raw["workbook_path"] = str(Path(workbook_path).expanduser())
    user_path.parent.mkdir(parents=True, exist_ok=True)
    with user_path.open("w", encoding="utf-8") as handle:
        json.dump(raw, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    return load_config(
        existing_config.project_config_path if existing_config and existing_config.project_config_path else None,
        user_config_path=user_path,
    )


def describe_config_locations(config: AppConfig) -> dict[str, Path | None]:
    return {
        "project_config": config.project_config_path,
        "user_config": config.user_config_path,
        "user_config_dir": config.user_config_path.parent if config.user_config_path else None,
    }


def _default_raw_config() -> dict[str, Any]:
    return {
        "required_sheets": list(DEFAULT_REQUIRED_SHEETS),
        "optional_sheets": list(DEFAULT_OPTIONAL_SHEETS),
        "max_issue_details": DEFAULT_MAX_ISSUE_DETAILS,
        "expected_workbook_filename": DEFAULT_EXPECTED_WORKBOOK_FILENAME,
    }


def _resolve_project_config_path(config_path: str | Path | None) -> Path:
    if config_path is None:
        return project_root() / "config.json"
    path = Path(config_path).expanduser()
    if path.is_absolute() or _looks_like_windows_absolute(str(config_path)):
        return path
    return Path.cwd() / path


def _resolve_user_config_path(path: str | Path | None) -> Path:
    if path is None:
        return default_user_config_path()
    candidate = Path(path).expanduser()
    if candidate.is_absolute() or _looks_like_windows_absolute(str(path)):
        return candidate
    return Path.cwd() / candidate


def _read_json_object(path: Path, label: str, *, missing_is_error: bool) -> tuple[dict[str, Any], list[str], list[str]]:
    if not path.exists():
        message = f"{label.title()} config file does not exist: {path}"
        return {}, [message] if missing_is_error else [], [] if missing_is_error else [message]

    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        return {}, [f"{label.title()} config JSON is invalid: {path} ({exc})"], []
    except OSError as exc:
        return {}, [f"{label.title()} config could not be read: {path} ({exc})"], []

    if not isinstance(raw, dict):
        return {}, [f"{label.title()} config must contain a JSON object: {path}"], []
    return raw, [], []


def _resolve_workbook_path(
    project_raw: dict[str, Any],
    user_raw: dict[str, Any],
    project_path: Path,
    user_path: Path,
) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    source_raw: dict[str, Any]
    source_base: Path
    if "workbook_path" in user_raw:
        source_raw = user_raw
        source_base = user_path.parent
    elif "workbook_path" in project_raw:
        source_raw = project_raw
        source_base = project_path.parent
        warnings.append("Workbook path came from project config. For office use, select the workbook once so it is saved in user config.")
    else:
        return None, warnings

    value = source_raw.get("workbook_path")
    if value is None or str(value).strip() == "":
        return None, warnings

    text = str(value).strip()
    path = Path(text).expanduser()
    if path.is_absolute() or _looks_like_windows_absolute(text):
        return path, warnings
    return (source_base / path).resolve(), warnings


def _string_list(value: Any, default: list[str], name: str) -> list[str]:
    if value is None:
        return list(default)
    if not isinstance(value, list):
        return list(default)
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return cleaned or list(default)


def _positive_int(value: Any, default: int, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _looks_like_windows_absolute(value: str) -> bool:
    return bool(_WINDOWS_ABSOLUTE_PATH.match(value) or value.startswith("\\\\"))
