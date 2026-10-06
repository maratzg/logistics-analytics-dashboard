from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .date_utils import is_meaningful_value, parse_schedule_date
from .history_processing import is_legacy_unavailable
from .operational_calculations import (
    ensure_weekly_schema,
    eta_year_series,
    identity_row_mask,
    normalize_load_status,
    operational_payload_mask,
    operational_mask,
    recalculate_operational_columns,
)
from .schema import (
    CALCULATED_COLUMNS,
    EXPECTED_HISTORY_COLUMNS,
    LOAD_STATUS_COLUMN,
    WEEKLY_INPUT_COLUMNS,
)
from .validators import DATE_COLUMNS, ValidationIssue


@dataclass(frozen=True, slots=True)
class CleanResult:
    dataframe: pd.DataFrame
    issues: list[ValidationIssue]


STRING_COLUMNS = [
    "Vessel",
    "Voyage",
    "Comments 1",
    "Booking number",
    "O/V",
    "SVC",
    "Booking status",
    "TYPE",
    "POL",
    "EU TS",
    "POD CODE",
    "POD",
    "CUSTOMER",
    "Comments 2",
    "RowStatus",
    "CancelReason",
    "BlockID",
    "RowID",
    "LoadStatus",
]


def clean_weekly(df: pd.DataFrame) -> CleanResult:
    issues: list[ValidationIssue] = []
    source_columns = list(df.columns)
    cleaned = ensure_weekly_schema(df)
    cleaned.attrs["source_columns"] = source_columns

    cleaned["_raw_LoadStatus"] = cleaned[LOAD_STATUS_COLUMN].copy()
    for column in CALCULATED_COLUMNS:
        cleaned[f"_workbook_{column}"] = cleaned[column].copy()

    _normalize_strings(cleaned, STRING_COLUMNS)
    _clear_structural_total_markers(cleaned)
    _normalize_numeric(cleaned, ["Week", "CNTR AMT", "SIZE", "GWT"], issues)
    _normalize_schedule_dates(cleaned, DATE_COLUMNS, issues)

    cleaned["_has_any_business_data"] = _business_data_mask(cleaned)
    cleaned[LOAD_STATUS_COLUMN] = cleaned[LOAD_STATUS_COLUMN].map(normalize_load_status)
    cleaned["ETA Year"] = eta_year_series(cleaned["ETA"])
    cleaned = recalculate_operational_columns(cleaned)
    cleaned["_has_stable_identity"] = identity_row_mask(cleaned)
    cleaned["_has_operational_payload"] = operational_payload_mask(cleaned)
    cleaned["_is_operational"] = operational_mask(cleaned)
    cleaned.attrs["source_columns"] = source_columns
    return CleanResult(cleaned, issues)


def clean_history(df: pd.DataFrame) -> CleanResult:
    issues: list[ValidationIssue] = []
    cleaned = df.copy()
    source_columns = list(cleaned.columns)
    for column in EXPECTED_HISTORY_COLUMNS:
        if column not in cleaned.columns:
            cleaned[column] = pd.NA
    cleaned.attrs["source_columns"] = source_columns
    cleaned["_raw_OldValue"] = cleaned["OldValue"].copy()
    cleaned["_raw_NewValue"] = cleaned["NewValue"].copy()

    _normalize_strings(
        cleaned,
        [
            "User",
            "BlockID",
            "RowID",
            "Vessel",
            "Voyage",
            "Booking number",
            "Comments 1",
            "Comments 2",
            "CancelReason",
            "Field",
            "OldValue",
            "NewValue",
        ],
    )
    _normalize_numeric(cleaned, ["Week", "Year", "Month"], issues)
    _normalize_dates(cleaned, ["Timestamp"], issues)
    cleaned["_legacy_bulk_edit"] = cleaned["OldValue"].map(is_legacy_unavailable) | cleaned["NewValue"].map(is_legacy_unavailable)
    cleaned["_old_value_available"] = cleaned["OldValue"].map(is_meaningful_value) & ~cleaned["OldValue"].map(is_legacy_unavailable)
    cleaned["_new_value_available"] = cleaned["NewValue"].map(is_meaningful_value) & ~cleaned["NewValue"].map(is_legacy_unavailable)
    cleaned.loc[cleaned["OldValue"].map(is_legacy_unavailable), "OldValue"] = pd.NA
    cleaned.loc[cleaned["NewValue"].map(is_legacy_unavailable), "NewValue"] = pd.NA
    _add_history_time_dimensions(cleaned)
    cleaned.attrs["source_columns"] = source_columns
    return CleanResult(cleaned, issues)


def _normalize_strings(df: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in df.columns:
            df[column] = df[column].map(lambda value: value.strip() if isinstance(value, str) else value)


def _clear_structural_total_markers(df: pd.DataFrame) -> None:
    """Exclude visual block footers from business-field normalization.

    The Excel layout labels each weekly footer as ``Total`` in the Week column.
    It is structural only when the row has no identifiers and no other editable
    business input. A real record containing ``Total`` as its Week remains an
    invalid numeric value and is still reported by validation.
    """

    if "Week" not in df.columns:
        return
    total_marker = df["Week"].astype(str).str.strip().str.casefold().eq("total")
    structural = total_marker.copy()
    for column in ["RowID", "BlockID"] + [name for name in WEEKLY_INPUT_COLUMNS if name != "Week"]:
        if column in df.columns:
            structural &= ~df[column].map(is_meaningful_value).fillna(False).astype(bool)
    if "_raw_LoadStatus" in df.columns:
        structural &= ~df["_raw_LoadStatus"].map(is_meaningful_value).fillna(False).astype(bool)
    if structural.any():
        df.loc[structural, "Week"] = pd.NA


def _normalize_numeric(df: pd.DataFrame, columns: Iterable[str], issues: list[ValidationIssue]) -> None:
    for column in columns:
        if column not in df.columns:
            continue
        original = df[column]
        converted = pd.to_numeric(original, errors="coerce")
        bad_mask = original.notna() & (original.astype(str).str.strip() != "") & converted.isna()
        for index in list(df.index[bad_mask]):
            source_row = df.at[index, "_source_excel_row"] if "_source_excel_row" in df.columns else index + 2
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"Invalid numeric value in {column}: {original.at[index]!r}",
                    f"Excel row {source_row}",
                )
            )
        df[column] = converted


def _normalize_dates(df: pd.DataFrame, columns: Iterable[str], issues: list[ValidationIssue]) -> None:
    for column in columns:
        if column not in df.columns:
            continue
        original = df[column]
        converted = pd.to_datetime(original, errors="coerce")
        bad_mask = original.notna() & (original.astype(str).str.strip() != "") & converted.isna()
        for index in list(df.index[bad_mask]):
            source_row = df.at[index, "_source_excel_row"] if "_source_excel_row" in df.columns else index + 2
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"Invalid date/datetime value in {column}: {original.at[index]!r}",
                    f"Excel row {source_row}",
                )
            )
        df[column] = converted


def _normalize_schedule_dates(df: pd.DataFrame, columns: Iterable[str], issues: list[ValidationIssue]) -> None:
    for column in columns:
        if column not in df.columns:
            continue
        original = df[column].copy()
        parsed_values = []
        for index, value in original.items():
            parsed = parse_schedule_date(value, field_name=column)
            parsed_values.append(parsed.parsed if parsed.parsed is not None else pd.NaT)
            if parsed.warning:
                source_row = df.at[index, "_source_excel_row"] if "_source_excel_row" in df.columns else index + 2
                issues.append(ValidationIssue("ERROR", parsed.warning, f"Excel row {source_row}"))
        df[column] = pd.to_datetime(pd.Series(parsed_values, index=df.index), errors="coerce")


def _business_data_mask(df: pd.DataFrame) -> pd.Series:
    business_columns = [column for column in WEEKLY_INPUT_COLUMNS if column in df.columns and column != LOAD_STATUS_COLUMN]
    mask = pd.Series(False, index=df.index, dtype=bool)
    for column in business_columns:
        mask |= df[column].map(is_meaningful_value).fillna(False).astype(bool)
    if "_raw_LoadStatus" in df.columns:
        mask |= df["_raw_LoadStatus"].map(is_meaningful_value)
    return mask


def _add_history_time_dimensions(df: pd.DataFrame) -> None:
    timestamps = pd.to_datetime(df["Timestamp"], errors="coerce")
    df["History Year"] = timestamps.dt.year.astype("Int64")
    df["History Month"] = timestamps.dt.month.astype("Int64")
    df["History Quarter"] = timestamps.map(
        lambda value: f"{value.year} Q{((value.month - 1) // 3) + 1}" if not pd.isna(value) else "Unknown"
    )
