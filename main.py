from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.app_state import create_application_state
from src.diagnostics import main as diagnostics_main
from src.logging_setup import configure_logging
from src.version import APP_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Weekly Operations history dashboard.")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Run the Milestone 1/2 terminal diagnostics instead of launching the desktop GUI.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Launch the GUI briefly and close automatically. Intended for development verification.",
    )
    parser.add_argument(
        "--environment-check",
        action="store_true",
        help="Print transfer/deployment environment information and exit.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional project default config path for development/testing.",
    )
    parser.add_argument(
        "--user-config",
        type=Path,
        default=None,
        help="Optional per-user config path for development/testing.",
    )
    parser.add_argument("--version", action="version", version=f"History Dashboard {APP_VERSION}")
    args = parser.parse_args()

    log_path = configure_logging()
    logging.getLogger(__name__).info("Application startup")

    if args.environment_check:
        from check_environment import main as environment_check_main

        return environment_check_main(config_path=args.config, user_config_path=args.user_config)

    if args.diagnostics:
        return diagnostics_main(config_path=args.config, user_config_path=args.user_config)

    try:
        from src.gui.app import run_gui
    except ModuleNotFoundError as exc:
        if exc.name == "customtkinter":
            print("CustomTkinter is not installed.")
            print("Install project dependencies first:")
            print("  pip install -r requirements.txt")
            return 2
        raise

    logging.getLogger(__name__).info("Log file: %s", log_path)
    state = create_application_state(config_path=args.config, user_config_path=args.user_config)
    return run_gui(state, smoke_test_ms=1800 if args.smoke_test else None)


if __name__ == "__main__":
    raise SystemExit(main())
