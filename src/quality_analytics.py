from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .date_utils import is_meaningful_value, normalize_text
from .history_processing import IDENTITY_AMBIGUOUS, IDENTITY_RESOLUTION_COLUMN
from .operational_calculations import identity_row_mask, operational_mask
from .schema import CALCULATED_COLUMNS


QUALITY_COLUMNS = [
    "Severity",
    "Category",
    "Message",
    "RowID",
    "BlockID",
    "Vessel",
    "Voyage",
    "Booking number",
    "Field",
    "Raw Value",
    "Suggested Correction",
]


def generate_quality_issues(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    *,
    weekly_raw_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    issues: list[dict[str, Any]] = []
    raw = weekly_raw_df if weekly_raw_df is not None else weekly_df
    identity_rows = weekly_df[identity_row_mask(weekly_df)].copy() if not weekly_df.empty else weekly_df.copy()
    operational = weekly_df[operational_mask(weekly_df)].copy() if not weekly_df.empty else weekly_df.copy()

    _duplicate_row_ids(operational, issues)
    _duplicate_bookings(operational, issues)
    for index, row in operational.iterrows():
        source = _raw_row(row, raw, index)
        amount = _number(row.get("CNTR AMT"))
        size = _number(row.get("SIZE"))
        gwt = _number(row.get("GWT"))

        if amount is not None and amount < 0:
            _add(issues, "Critical", "Negative quantity", "CNTR AMT cannot be negative.", row, "CNTR AMT", source.get("CNTR AMT"), "Correct the container amount in WEEKLY.")
        if gwt is not None and gwt < 0:
            _add(issues, "Critical", "Negative quantity", "GWT cannot be negative.", row, "GWT", source.get("GWT"), "Correct the gross weight in WEEKLY.")
        if amount is not None and amount > 0 and size is None:
            _add(issues, "Warning", "Missing equipment", "SIZE is missing for a row with containers.", row, "SIZE", source.get("SIZE"), "Enter 2 for 20ft or 4 for 40ft when applicable.")
        elif size is not None and size not in {2, 4}:
            _add(issues, "Warning", "Invalid equipment", f"SIZE {size:g} is not a supported 20ft/40ft code.", row, "SIZE", source.get("SIZE"), "Confirm the equipment size; supported analytical codes are 2 and 4.")
        if amount is not None and amount > 0 and not is_meaningful_value(row.get("TYPE")):
            _add(issues, "Warning", "Missing equipment", "TYPE is missing for a row with containers.", row, "TYPE", source.get("TYPE"), "Enter the observed equipment type.")
        if amount is not None and amount > 0 and row.get("LoadStatus") == "Loaded" and gwt is None:
            _add(issues, "Warning", "Missing weight", "GWT is missing for loaded cargo.", row, "GWT", source.get("GWT"), "Enter gross weight or confirm that it is genuinely unavailable.")

        for field in ["ETA", "ETD", "Cut-Off", "ETA T/S"]:
            raw_value = source.get(field)
            if is_meaningful_value(raw_value) and pd.isna(row.get(field)):
                _add(issues, "Warning", "Invalid date", f"{field} is not a valid supported date.", row, field, raw_value, "Correct the date value in WEEKLY.")
        if not is_meaningful_value(row.get("Vessel")):
            _add(issues, "Warning", "Incomplete voyage identity", "Operational row has no Vessel.", row, "Vessel", source.get("Vessel"), "Enter the vessel name or confirm the row identity.")
        if not is_meaningful_value(row.get("Voyage")):
            _add(issues, "Warning", "Incomplete voyage identity", "Operational row has no Voyage.", row, "Voyage", source.get("Voyage"), "Enter the voyage or confirm the row identity.")
        if not is_meaningful_value(row.get("BlockID")):
            _add(issues, "Critical", "Incomplete voyage identity", "Operational row has no BlockID and is excluded from voyage-level analytics.", row, "BlockID", source.get("BlockID"), "Restore the current physical BlockID through the workbook workflow; do not construct or parse RowID.")
        if is_meaningful_value(row.get("POD")) and not is_meaningful_value(row.get("POD CODE")):
            _add(issues, "Information", "Destination metadata", "POD is populated without POD CODE.", row, "POD CODE", source.get("POD CODE"), "Add POD CODE if the destination is expected to have one.")

        week = _number(row.get("Week"))
        if week is None or week % 1 != 0 or not 1 <= week <= 53:
            _add(issues, "Warning", "Invalid week", "Week must be an explicit integer from 1 to 53.", row, "Week", source.get("Week"), "Correct the editable Week value; do not change or parse IDs.")
        if row.get("LoadStatus") == "Unknown":
            _add(issues, "Warning", "Unexpected status", "LoadStatus is not Loaded, Empty, or blank.", row, "LoadStatus", row.get("_raw_LoadStatus"), "Use Loaded or Empty; blank is valid and means Loaded.")
        row_status = normalize_text(row.get("RowStatus"))
        if row_status not in {"", "active", "cancelled"}:
            _add(issues, "Warning", "Unexpected status", "RowStatus is not blank, Active, or Cancelled.", row, "RowStatus", source.get("RowStatus"), "Use the workbook's supported row status values.")

        for column in ["Summary", "TEU", "TS", "Total Containers", "Total TEU", "Total GWT"]:
            value = _number(row.get(column))
            if value is not None and value < 0:
                _add(issues, "Critical", "Impossible calculation", f"Calculated {column} is negative.", row, column, value, "Correct the negative source quantity; Python calculations are authoritative.")
        _formula_cache_issues(row, issues)

    _inconsistent_voyage_metadata(operational, issues)
    _ambiguous_history(history_df, issues)
    _orphan_history(identity_rows, history_df, issues)
    return pd.DataFrame(issues, columns=QUALITY_COLUMNS)


def quality_summary(issues_df: pd.DataFrame) -> pd.DataFrame:
    if issues_df.empty:
        return pd.DataFrame(columns=["Severity", "Category", "Issue Count"])
    return issues_df.groupby(["Severity", "Category"], dropna=False).size().reset_index(name="Issue Count")


def _duplicate_row_ids(identity_rows: pd.DataFrame, issues: list[dict[str, Any]]) -> None:
    if identity_rows.empty or "RowID" not in identity_rows.columns:
        return
    keys = identity_rows["RowID"].map(normalize_text)
    duplicates = identity_rows[keys.duplicated(keep=False)]
    for _, row in duplicates.iterrows():
        _add(issues, "Critical", "Duplicate identity", "RowID is duplicated.", row, "RowID", row.get("RowID"), "Assign a unique opaque RowID through the workbook workflow.")


def _duplicate_bookings(operational: pd.DataFrame, issues: list[dict[str, Any]]) -> None:
    if operational.empty or "Booking number" not in operational.columns:
        return
    booking_keys = operational["Booking number"].map(normalize_text)
    counts = operational.assign(_booking_key=booking_keys).groupby("_booking_key", dropna=False)["RowID"].nunique()
    duplicate_keys = {key for key, count in counts.items() if key and count > 1}
    for _, row in operational[booking_keys.isin(duplicate_keys)].iterrows():
        _add(issues, "Information", "Duplicate-looking booking", "Booking number appears on more than one RowID.", row, "Booking number", row.get("Booking number"), "Review whether the repeated booking is an intentional equipment split.")


def _inconsistent_voyage_metadata(operational: pd.DataFrame, issues: list[dict[str, Any]]) -> None:
    identity = ["Vessel", "Voyage", "BlockID"]
    if operational.empty or not all(column in operational.columns for column in identity):
        return
    working = operational.copy()
    keys = []
    for column in identity:
        key = f"_identity_{column}"
        working[key] = working[column].map(normalize_text)
        keys.append(key)
    for _, group in working.groupby(keys, dropna=False, sort=True):
        for field in ["Week", "SVC", "POL", "POD", "POD CODE", "ETA", "ETD", "Cut-Off"]:
            if field not in group.columns:
                continue
            values = {_comparison_value(value) for value in group[field].tolist() if is_meaningful_value(value)}
            if len(values) > 1:
                row = group.iloc[0]
                _add(issues, "Warning", "Inconsistent voyage metadata", f"{field} has {len(values)} different values within one voyage instance.", row, field, sorted(values), "Review the rows sharing Vessel, Voyage, and BlockID.")


def _orphan_history(identity_rows: pd.DataFrame, history_df: pd.DataFrame, issues: list[dict[str, Any]]) -> None:
    if history_df.empty or "RowID" not in history_df.columns:
        return
    current_ids = {normalize_text(value) for value in identity_rows.get("RowID", pd.Series(dtype=object)).tolist() if normalize_text(value)}
    for _, row in history_df.iterrows():
        row_id = normalize_text(row.get("RowID"))
        if row_id and row_id not in current_ids:
            _add(issues, "Warning", "Orphan history", "LOG_HISTORY RowID has no current WEEKLY identity row.", row, "RowID", row.get("RowID"), "Confirm whether the row was legitimately removed or the history identity is incorrect.")


def _ambiguous_history(history_df: pd.DataFrame, issues: list[dict[str, Any]]) -> None:
    if history_df.empty or IDENTITY_RESOLUTION_COLUMN not in history_df.columns:
        return
    ambiguous = history_df[
        history_df[IDENTITY_RESOLUTION_COLUMN].map(normalize_text).eq(normalize_text(IDENTITY_AMBIGUOUS))
    ]
    if ambiguous.empty:
        return
    seen: set[str] = set()
    for _, row in ambiguous.iterrows():
        row_id = normalize_text(row.get("RowID"))
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        _add(
            issues,
            "Critical",
            "Ambiguous history identity",
            "LOG_HISTORY RowID matches more than one current operational row, so current context cannot be resolved safely.",
            row,
            "RowID",
            row.get("RowID"),
            "Resolve the duplicate current RowID through the workbook workflow; Python will not guess which record owns the history.",
        )


def _formula_cache_issues(row: pd.Series, issues: list[dict[str, Any]]) -> None:
    for column in CALCULATED_COLUMNS:
        cache_column = f"_workbook_{column}"
        if cache_column not in row.index or not is_meaningful_value(row.get(cache_column)):
            continue
        cached = _number(row.get(cache_column))
        calculated = _number(row.get(column))
        if cached is None or calculated is None or not math.isclose(cached, calculated, abs_tol=0.000001):
            _add(issues, "Information", "Formula cache mismatch", f"Workbook cache for {column} differs from the Python calculation.", row, column, row.get(cache_column), "Refresh Excel formulas if desired; analytics continue to use the Python result.")


def _add(
    issues: list[dict[str, Any]],
    severity: str,
    category: str,
    message: str,
    row: pd.Series,
    field: str,
    raw_value: Any,
    correction: str,
) -> None:
    issues.append(
        {
            "Severity": severity,
            "Category": category,
            "Message": message,
            "RowID": row.get("RowID"),
            "BlockID": row.get("BlockID"),
            "Vessel": row.get("Vessel"),
            "Voyage": row.get("Voyage"),
            "Booking number": row.get("Booking number"),
            "Field": field,
            "Raw Value": raw_value,
            "Suggested Correction": correction,
        }
    )


def _raw_row(row: pd.Series, raw: pd.DataFrame, index: Any) -> pd.Series:
    source_excel_row = row.get("_source_excel_row")
    if source_excel_row is not None and "_source_excel_row" in raw.columns:
        source_number = pd.to_numeric(pd.Series([source_excel_row]), errors="coerce").iloc[0]
        matches = raw[pd.to_numeric(raw["_source_excel_row"], errors="coerce").eq(source_number)]
        if not matches.empty:
            return matches.iloc[0]
    if index in raw.index:
        selected = raw.loc[index]
        return selected.iloc[0] if isinstance(selected, pd.DataFrame) else selected
    return row


def _number(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(numeric) else float(numeric)


def _comparison_value(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value).strip().casefold()
