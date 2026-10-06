from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from .date_utils import is_meaningful_value
from .operational_calculations import LOAD_CLASS_UNKNOWN
from .schema import (
    CALCULATED_COLUMNS,
    EXPECTED_HISTORY_COLUMNS,
    EXPECTED_WEEKLY_COLUMNS,
    LEGACY_CALCULATED_COLUMNS,
    REQUIRED_OPERATIONAL_COLUMNS,
)


Severity = Literal["ERROR", "WARNING"]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: Severity
    message: str
    location: str | None = None


REQUIRED_WEEKLY_COLUMNS = REQUIRED_OPERATIONAL_COLUMNS + LEGACY_CALCULATED_COLUMNS
DATE_COLUMNS = ["ETA", "ETD", "Cut-Off", "ETA T/S"]
NUMERIC_COLUMNS = ["Week", "CNTR AMT", "SIZE", "GWT"] + CALCULATED_COLUMNS


def validate_weekly(df: pd.DataFrame) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    missing = [column for column in REQUIRED_WEEKLY_COLUMNS if column not in df.columns]
    if missing:
        issues.append(ValidationIssue("WARNING", f"WEEKLY is missing expected columns: {', '.join(missing)}"))
        return issues
    if df.empty:
        issues.append(ValidationIssue("WARNING", "WEEKLY contains no valid operational rows."))
        return issues

    populated_without_row_id = df[(~df["_has_stable_identity"]) & (df["_has_operational_payload"])]
    for _, row in populated_without_row_id.iterrows():
        issues.append(
            ValidationIssue(
                "WARNING",
                "Populated WEEKLY row has no RowID and is not counted as operational data.",
                _row_location(row),
            )
        )

    operational = df[df["_is_operational"]].copy()
    duplicate_mask = operational["RowID"].duplicated(keep=False)
    for _, row in operational[duplicate_mask].iterrows():
        issues.append(ValidationIssue("ERROR", f"Duplicate RowID: {row['RowID']}", _row_location(row)))

    if operational.empty:
        issues.append(ValidationIssue("WARNING", "WEEKLY contains no analytically populated operational rows."))

    missing_block = operational["BlockID"].isna() | (operational["BlockID"].astype(str).str.strip() == "")
    for _, row in operational[missing_block].iterrows():
        issues.append(ValidationIssue("ERROR", "Operational row is missing BlockID.", _row_location(row)))

    missing_week = operational["Week"].isna()
    for _, row in operational[missing_week].iterrows():
        issues.append(ValidationIssue("ERROR", "Operational row is missing a valid editable Week value.", _row_location(row)))

    for _, row in operational.iterrows():
        cancelled = _is_cancelled(row.get("RowStatus"))
        summary = row.get("Summary")
        teu = row.get("TEU")
        ts = row.get("TS")
        cntr_amt = row.get("CNTR AMT")
        size = row.get("SIZE")
        gwt = row.get("GWT")

        if row.get("LoadStatus") == LOAD_CLASS_UNKNOWN:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"Unrecognized LoadStatus {row.get('_raw_LoadStatus')!r}; loaded/empty quantities are not allocated.",
                    _row_location(row),
                )
            )

        if cancelled:
            for column_name in CALCULATED_COLUMNS:
                value = row.get(column_name)
                cached_value = row.get(f"_workbook_{column_name}")
                if _number_or_zero(value) != 0:
                    issues.append(ValidationIssue("ERROR", f"Cancelled row has non-zero {column_name}: {value}.", _row_location(row)))
                if is_meaningful_value(cached_value) and _number_or_zero(cached_value) != 0:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            f"Cancelled row has non-zero {column_name} in the workbook formula cache: {cached_value}.",
                            _row_location(row),
                        )
                    )
            continue

        if _is_number(summary) and _is_number(cntr_amt) and not math.isclose(float(summary), float(cntr_amt), abs_tol=0.000001):
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"Summary {summary} is inconsistent with CNTR AMT {cntr_amt}.",
                    _row_location(row),
                )
            )

        if _is_number(teu) and _is_number(cntr_amt) and _is_number(size):
            expected_teu = _expected_teu(float(cntr_amt), float(size))
            if not math.isclose(float(teu), expected_teu, abs_tol=0.000001):
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        f"TEU {teu} is inconsistent with CNTR AMT {cntr_amt} and SIZE {size}; expected {expected_teu:g}.",
                        _row_location(row),
                    )
                )

        if _is_number(ts) and _is_number(gwt) and not math.isclose(float(ts), float(gwt), abs_tol=0.000001):
            issues.append(
                ValidationIssue("ERROR", f"TS {ts} is inconsistent with GWT {gwt}.", _row_location(row))
            )

        if _number_or_zero(cntr_amt) > 0 and _number_or_zero(size) not in {2, 4}:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"SIZE {size!r} is not 2 or 4; TEU and 20ft/40ft allocations are zero.",
                    _row_location(row),
                )
            )

        _validate_formula_cache(row, issues)

    return issues


def validate_history(df: pd.DataFrame) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    source_columns = set(df.attrs.get("source_columns", df.columns))
    missing = [column for column in EXPECTED_HISTORY_COLUMNS if column not in source_columns]
    if missing:
        issues.append(ValidationIssue("ERROR", f"LOG_HISTORY is missing expected columns: {', '.join(missing)}"))
        return issues
    if df.empty:
        issues.append(ValidationIssue("WARNING", "LOG_HISTORY contains no history records. This is allowed for a cleaned workbook."))
        return issues

    if "History Year" in df.columns and "Year" in df.columns:
        workbook_year = pd.to_numeric(df["Year"], errors="coerce")
        derived_year = pd.to_numeric(df["History Year"], errors="coerce")
        mismatched = workbook_year.notna() & derived_year.notna() & workbook_year.ne(derived_year)
        if mismatched.any():
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{int(mismatched.sum())} history row(s) have workbook Year values that differ from Timestamp-derived History Year.",
                )
            )

    if "History Month" in df.columns and "Month" in df.columns:
        workbook_month = pd.to_numeric(df["Month"], errors="coerce")
        derived_month = pd.to_numeric(df["History Month"], errors="coerce")
        mismatched = workbook_month.notna() & derived_month.notna() & workbook_month.ne(derived_month)
        if mismatched.any():
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{int(mismatched.sum())} history row(s) have workbook Month values that differ from Timestamp-derived History Month.",
                )
            )
    return issues


def workbook_schema_issues(
    weekly_headers: list[str],
    history_headers: list[str],
    *,
    template_headers: list[str] | None = None,
    master_headers: list[str] | None = None,
) -> list[ValidationIssue]:
    """Validate workbook-facing schemas without requiring operational records."""

    issues: list[ValidationIssue] = []
    effective_weekly = weekly_headers or list(template_headers or [])
    if not effective_weekly:
        issues.append(ValidationIssue("WARNING", "WEEKLY has no generated block and TEMPLATE schema could not be confirmed."))
    else:
        missing_required = [column for column in REQUIRED_OPERATIONAL_COLUMNS if column not in effective_weekly]
        if missing_required:
            issues.append(ValidationIssue("ERROR", f"Operational schema is missing required columns: {', '.join(missing_required)}"))
        missing_v2 = [column for column in EXPECTED_WEEKLY_COLUMNS if column not in effective_weekly]
        if missing_v2:
            issues.append(ValidationIssue("WARNING", f"Operational schema is missing V2 columns: {', '.join(missing_v2)}"))

    missing_history = [column for column in EXPECTED_HISTORY_COLUMNS if column not in history_headers]
    if missing_history:
        issues.append(ValidationIssue("ERROR", f"LOG_HISTORY schema is missing columns: {', '.join(missing_history)}"))

    if master_headers:
        missing_master = [column for column in EXPECTED_WEEKLY_COLUMNS if column not in master_headers]
        if missing_master:
            issues.append(ValidationIssue("WARNING", f"Derived MASTER_DATA schema is missing V2 columns: {', '.join(missing_master)}"))
    return issues


def cross_check_master_data(weekly_df: pd.DataFrame, master_df: pd.DataFrame) -> list[ValidationIssue]:
    """Compare the optional derived table to WEEKLY without using it as a source."""

    issues: list[ValidationIssue] = []
    if weekly_df.empty or "_is_operational" not in weekly_df.columns:
        return issues
    weekly = weekly_df[weekly_df["_is_operational"].fillna(False).astype(bool)].copy()
    if weekly.empty:
        return issues
    if master_df.empty or "_is_operational" not in master_df.columns:
        return [ValidationIssue("WARNING", "MASTER_DATA is empty while WEEKLY contains operational rows; WEEKLY remains authoritative.")]
    master = master_df[master_df["_is_operational"].fillna(False).astype(bool)].copy()

    weekly_ids = set(weekly["RowID"].dropna().astype(str))
    master_ids = set(master["RowID"].dropna().astype(str))
    missing = weekly_ids - master_ids
    extra = master_ids - weekly_ids
    if missing:
        issues.append(ValidationIssue("WARNING", f"MASTER_DATA is missing {len(missing)} WEEKLY RowID value(s)."))
    if extra:
        issues.append(ValidationIssue("WARNING", f"MASTER_DATA contains {len(extra)} RowID value(s) not present in WEEKLY."))

    shared = weekly_ids & master_ids
    if shared:
        weekly_indexed = weekly.drop_duplicates("RowID", keep="first").set_index("RowID")
        master_indexed = master.drop_duplicates("RowID", keep="first").set_index("RowID")
        mismatch_count = 0
        mismatch_columns: set[str] = set()
        for row_id in shared:
            for column in EXPECTED_WEEKLY_COLUMNS:
                if column in {"RowID"} or column not in weekly_indexed.columns or column not in master_indexed.columns:
                    continue
                if not _equivalent_value(weekly_indexed.at[row_id, column], master_indexed.at[row_id, column]):
                    mismatch_count += 1
                    mismatch_columns.add(column)
        if mismatch_count:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"MASTER_DATA has {mismatch_count} value difference(s) from authoritative WEEKLY rows across: {', '.join(sorted(mismatch_columns))}.",
                )
            )
    return issues


def _expected_teu(cntr_amt: float, size: float) -> float:
    if size == 2:
        return cntr_amt
    if size == 4:
        return cntr_amt * 2
    return 0


def _is_cancelled(value: object) -> bool:
    return str(value or "").strip().upper() == "CANCELLED"


def _number_or_zero(value: object) -> float:
    if _is_number(value):
        return float(value)
    return 0


def _is_number(value: object) -> bool:
    return value is not None and not pd.isna(value) and isinstance(value, numbers.Real) and not isinstance(value, bool)


def _row_location(row: pd.Series) -> str:
    source_row = row.get("_source_excel_row")
    row_id = row.get("RowID")
    if source_row:
        return f"Excel row {int(source_row)} / RowID {row_id or 'blank'}"
    return f"RowID {row_id or 'blank'}"


def _validate_formula_cache(row: pd.Series, issues: list[ValidationIssue]) -> None:
    for column in CALCULATED_COLUMNS:
        cached = row.get(f"_workbook_{column}")
        calculated = row.get(column)
        if not is_meaningful_value(cached):
            continue
        cached_number = pd.to_numeric(pd.Series([cached]), errors="coerce").iloc[0]
        if pd.isna(cached_number):
            issues.append(ValidationIssue("WARNING", f"Workbook formula cache for {column} is not numeric: {cached!r}.", _row_location(row)))
        elif not math.isclose(float(cached_number), _number_or_zero(calculated), abs_tol=0.000001):
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"Workbook formula cache for {column} is {cached_number:g}; Python calculated {_number_or_zero(calculated):g} from source inputs.",
                    _row_location(row),
                )
            )


def _equivalent_value(left: object, right: object) -> bool:
    if not is_meaningful_value(left) and not is_meaningful_value(right):
        return True
    if _is_number(left) and _is_number(right):
        return math.isclose(float(left), float(right), abs_tol=0.000001)
    if isinstance(left, pd.Timestamp) or isinstance(right, pd.Timestamp):
        left_date = pd.to_datetime(left, errors="coerce")
        right_date = pd.to_datetime(right, errors="coerce")
        return not pd.isna(left_date) and not pd.isna(right_date) and left_date == right_date
    return str(left).strip().casefold() == str(right).strip().casefold()
