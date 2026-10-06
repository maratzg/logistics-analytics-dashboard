from __future__ import annotations

from pathlib import Path

import pandas as pd

from .analytics import (
    rank_vessels_by_eta_revisions,
    rank_vessels_by_history_events,
    rank_voyages_by_eta_revisions,
    rank_voyages_by_history_events,
)
from .app_state import load_workbook_data
from .config import load_config
from .platform_paths import user_config_dir, user_log_dir
from .validators import ValidationIssue
from .version import APP_NAME, APP_VERSION
from .workbook_health import health_message, validate_workbook


def main(config_path: str | Path | None = None, *, user_config_path: str | Path | None = None) -> int:
    try:
        config = load_config(config_path, user_config_path=user_config_path)
        health = validate_workbook(
            config.workbook_path,
            required_sheets=config.required_sheets,
            optional_sheets=config.optional_sheets,
        )
        if not health.can_load:
            print_health_report(config=config, health=health)
            return 2
        data = load_workbook_data(config)
        print_report(
            workbook_path=config.workbook_path,
            structure=data.structure,
            weekly_metrics=data.weekly_metrics,
            history_metrics=data.history_metrics,
            weekly_df=data.weekly_df,
            history_df=data.history_df,
            issues=data.issues,
            max_issue_details=config.max_issue_details,
        )
        return 1 if any(issue.severity == "ERROR" for issue in data.issues) else 0
    except Exception as exc:
        print("==================================================")
        print("WEEKLY OPERATIONS - DATA VALIDATION")
        print()
        print("Status: FAILED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        return 2


def print_report(
    *,
    workbook_path: Path,
    structure,
    weekly_metrics,
    history_metrics,
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    issues: list[ValidationIssue],
    max_issue_details: int,
) -> None:
    errors = [issue for issue in issues if issue.severity == "ERROR"]
    warnings = [issue for issue in issues if issue.severity == "WARNING"]

    print("==================================================")
    print("WEEKLY OPERATIONS - DATA VALIDATION")
    print(f"Application: {APP_NAME} {APP_VERSION}")
    print()
    print(f"Workbook: {workbook_path}")
    print("Status:   Loaded successfully (read-only)")
    print()
    print("WORKBOOK STRUCTURE")
    if structure is None:
        print("Structure: unavailable")
    else:
        print(f"Sheets: {', '.join(structure.sheet_names)}")
        for sheet in structure.sheets:
            table_summary = ", ".join(f"{table.name}={table.ref}" for table in sheet.tables) or "none"
            print(f"- {sheet.name}: rows={sheet.max_row}, cols={sheet.max_column}, tables={table_summary}")
    print()
    print("WEEKLY")
    print(f"Valid operational rows:  {weekly_metrics.valid_operational_rows}")
    print(f"Weekly blocks:           {weekly_metrics.unique_block_count}")
    print(f"Cancelled rows:          {weekly_metrics.cancelled_rows}")
    print(f"Summary:                 {weekly_metrics.total_summary:g}")
    print(f"TEU:                     {weekly_metrics.total_teu:g}")
    print(f"TS:                      {weekly_metrics.total_ts:g}")
    print()
    print("LOG_HISTORY")
    print(f"History records:         {history_metrics.history_records}")
    print(f"ETA changes:             {history_metrics.eta_changes}")
    print(f"ETD changes:             {history_metrics.etd_changes}")
    print(f"Cut-Off changes:         {history_metrics.cut_off_changes}")
    print(f"Vessel changes:          {history_metrics.vessel_changes}")
    print(f"Voyage changes:          {history_metrics.voyage_changes}")
    print(f"ETA T/S changes:         {history_metrics.eta_ts_changes}")
    print()
    print("VALIDATION")
    print(f"Errors:                  {len(errors)}")
    print(f"Warnings:                {len(warnings)}")

    if issues:
        print()
        print("Issue details:")
        for issue in issues[:max_issue_details]:
            location = f" [{issue.location}]" if issue.location else ""
            print(f"- {issue.severity}{location}: {issue.message}")
        remaining = len(issues) - max_issue_details
        if remaining > 0:
            print(f"- ... {remaining} more issue(s) omitted. Increase max_issue_details in config settings.")

    print()
    print("==================================================")
    print("MILESTONE 2 ANALYTICS")
    print()
    if _has_operational_weekly_rows(weekly_df):
        print(f"Available vessels:       {_joined_values(_unique_values(weekly_df, 'Vessel'))}")
        print(f"Available voyages:       {_joined_values(_unique_values(weekly_df, 'Voyage'))}")
    else:
        print("No active WEEKLY operational records are currently available.")
        print("History analytics remain available, but live current-state analytics require WEEKLY rows.")

    if history_df.empty:
        print()
        print("LOG_HISTORY contains no history records, so timeline/ranking analytics are empty.")
        return

    print()
    print(f"History vessels:         {_joined_values(_unique_values(history_df, 'Vessel'))}")
    print(f"History voyages:         {_joined_values(_unique_values(history_df, 'Voyage'))}")
    _print_dataframe("Top vessels by changes", rank_vessels_by_history_events(history_df, limit=5))
    _print_dataframe("Top vessels by ETA revisions", rank_vessels_by_eta_revisions(history_df, limit=5))
    _print_dataframe("Top voyages by changes", rank_voyages_by_history_events(history_df, limit=5))
    _print_dataframe("Top voyages by ETA revisions", rank_voyages_by_eta_revisions(history_df, limit=5))


def _has_operational_weekly_rows(df: pd.DataFrame) -> bool:
    if df.empty or "_is_operational" not in df.columns:
        return False
    return bool(df["_is_operational"].fillna(False).astype(bool).any())


def _unique_values(df: pd.DataFrame, column: str) -> list[str]:
    if df.empty or column not in df.columns:
        return []
    values: dict[str, str] = {}
    for value in df[column].tolist():
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if not text:
            continue
        values.setdefault(text.casefold(), text)
    return sorted(values.values(), key=str.casefold)


def _joined_values(values: list[str], *, limit: int = 10) -> str:
    if not values:
        return "none"
    shown = values[:limit]
    suffix = f" (+{len(values) - limit} more)" if len(values) > limit else ""
    return ", ".join(shown) + suffix


def _print_dataframe(title: str, df: pd.DataFrame) -> None:
    print()
    print(title)
    if df.empty:
        print("  none")
        return
    print(df.to_string(index=False))


def print_health_report(*, config, health) -> None:
    print("==================================================")
    print("WEEKLY OPERATIONS - DATA VALIDATION")
    print(f"Application: {APP_NAME} {APP_VERSION}")
    print()
    print(f"Status:   {health.status.value}")
    print(f"Message:  {health_message(health)}")
    print(f"Workbook: {health.path or 'Not configured'}")
    print()
    print("CONFIGURATION")
    print(f"Project config: {config.project_config_path}")
    print(f"User config:    {config.user_config_path}")
    print(f"Config folder:  {config.user_config_path.parent if config.user_config_path else user_config_dir()}")
    print(f"Log folder:     {user_log_dir()}")
    if config.config_errors:
        print()
        print("Config errors:")
        for error in config.config_errors:
            print(f"- {error}")
    if health.errors:
        print()
        print("Workbook errors:")
        for error in health.errors:
            print(f"- {error}")
    if health.warnings:
        print()
        print("Workbook warnings:")
        for warning in health.warnings:
            print(f"- {warning}")
    if health.detected_sheets:
        print()
        print(f"Detected sheets: {', '.join(health.detected_sheets)}")
    print("==================================================")


if __name__ == "__main__":
    raise SystemExit(main())
