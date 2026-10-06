from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
from pathlib import Path
from typing import Iterable

from src.config import load_config
from src.platform_paths import user_config_dir, user_log_dir
from src.version import APP_NAME, APP_VERSION
from src.workbook_health import WorkbookHealthStatus, health_message, validate_workbook


REQUIRED_MODULES = ["openpyxl", "pandas", "customtkinter", "matplotlib"]
SUPPORTED_PYTHON = (3, 13)


def main(config_path: str | Path | None = None, *, user_config_path: str | Path | None = None) -> int:
    config = load_config(config_path, user_config_path=user_config_path)
    module_results = module_import_status(REQUIRED_MODULES)
    tk_ok, tk_message = check_tk_available()
    python_ok = sys.version_info[:2] == SUPPORTED_PYTHON
    health = validate_workbook(
        config.workbook_path,
        required_sheets=config.required_sheets,
        optional_sheets=config.optional_sheets,
    )

    print("==================================================")
    print(f"{APP_NAME.upper()} - ENVIRONMENT CHECK")
    print("==================================================")
    print(f"Application version: {APP_VERSION}")
    print(f"Python executable:   {sys.executable}")
    print(f"Python version:      {platform.python_version()}")
    print(f"Python 3.13 target:  {'OK' if python_ok else 'UNSUPPORTED'}")
    print(f"Operating system:    {platform.platform()}")
    print()
    print("DEPENDENCIES")
    for module, available in module_results.items():
        print(f"- {module}: {'OK' if available else 'MISSING'}")
    print(f"- tkinter/Tk: {'OK' if tk_ok else 'NOT AVAILABLE'} ({tk_message})")
    print()
    print("CONFIGURATION")
    print(f"Project config:      {config.project_config_path}")
    print(f"User config:         {config.user_config_path}")
    print(f"Config folder:       {config.user_config_path.parent if config.user_config_path else user_config_dir()}")
    print(f"Log folder:          {user_log_dir()}")
    print(f"Configured workbook: {config.workbook_path or 'Not configured'}")
    print()
    print("WORKBOOK HEALTH")
    print(f"Status:              {health.status.value}")
    print(f"Message:             {health_message(health)}")
    print(f"Exists:              {'Yes' if health.exists else 'No'}")
    if health.detected_sheets:
        print(f"Detected sheets:     {', '.join(health.detected_sheets)}")
    for error in health.errors:
        print(f"- ERROR: {error}")
    for warning in health.warnings:
        print(f"- WARNING: {warning}")
    for error in config.config_errors:
        print(f"- CONFIG ERROR: {error}")
    print("==================================================")

    dependency_failure = not python_ok or not all(module_results.values()) or not tk_ok
    workbook_failure = health.status not in {
        WorkbookHealthStatus.READY,
        WorkbookHealthStatus.READY_WITH_WARNINGS,
        WorkbookHealthStatus.NOT_CONFIGURED,
    }
    config_failure = bool(config.config_errors)
    return 1 if dependency_failure or workbook_failure or config_failure else 0


def module_import_status(modules: Iterable[str]) -> dict[str, bool]:
    return {module: importlib.util.find_spec(module) is not None for module in modules}


def check_tk_available() -> tuple[bool, str]:
    try:
        import tkinter as tk

        return True, f"tkinter importable, Tk {tk.TkVersion}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def cli_main() -> int:
    parser = argparse.ArgumentParser(description="Check History Dashboard transfer/deployment environment.")
    parser.add_argument("--config", type=Path, default=None, help="Optional project default config path.")
    parser.add_argument("--user-config", type=Path, default=None, help="Optional per-user config path.")
    args = parser.parse_args()
    return main(config_path=args.config, user_config_path=args.user_config)


if __name__ == "__main__":
    raise SystemExit(cli_main())
