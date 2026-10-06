from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .date_utils import normalize_text
from .history_processing import IDENTITY_RESOLUTION_COLUMN, IDENTITY_RESOLVED
from .operational_calculations import operational_mask


FilterValue = Any | Iterable[Any] | None


@dataclass(frozen=True, slots=True)
class FilterContext:
    """Shared current-state filter context for every Phase C analytical module."""

    vessel: FilterValue = None
    voyage: FilterValue = None
    week: FilterValue = None
    eta_month: FilterValue = None
    eta_year: FilterValue = None
    svc: FilterValue = None
    pol: FilterValue = None
    pod: FilterValue = None
    customer: FilterValue = None
    load_status: FilterValue = None
    row_status: FilterValue = None


@dataclass(frozen=True, slots=True)
class HistoryPeriodContext:
    """LOG_HISTORY reporting periods, derived only from Timestamp."""

    month: FilterValue = None
    quarter: FilterValue = None
    year: FilterValue = None


def apply_current_filters(
    df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    operational_only: bool = True,
) -> pd.DataFrame:
    result = df.copy()
    if result.empty:
        return result
    if operational_only:
        result = result[operational_mask(result)].copy()
    if context is None:
        return result

    result = _text_filter(result, "Vessel", context.vessel)
    result = _text_filter(result, "Voyage", context.voyage)
    result = _numeric_filter(result, "Week", context.week)
    result = _text_filter(result, "SVC", context.svc)
    result = _text_filter(result, "POL", context.pol)
    result = _text_filter(result, "POD", context.pod)
    result = _text_filter(result, "CUSTOMER", context.customer)
    result = _text_filter(result, "LoadStatus", context.load_status)
    result = _row_status_filter(result, context.row_status)
    result = _eta_month_filter(result, context.eta_month)
    result = _eta_year_filter(result, context.eta_year)
    return result


def apply_history_filters(
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    periods: HistoryPeriodContext | None = None,
    current_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Apply shared identity filters and Timestamp-derived history periods.

    Current-only dimensions such as SVC and CUSTOMER are applied through the
    matching authoritative WEEKLY RowIDs when current_df is supplied.
    """

    result = ensure_history_periods(history_df)
    if result.empty:
        return result

    if context is not None:
        result = _history_text_filter(result, "Vessel", context.vessel)
        result = _history_text_filter(result, "Voyage", context.voyage)
        result = _history_numeric_filter(result, "Week", context.week)

        if current_df is not None and _needs_current_crosswalk(context):
            eligible = apply_current_filters(current_df, context)
            if "RowID" not in result.columns or "RowID" not in eligible.columns:
                result = result.iloc[0:0].copy()
            else:
                row_ids = {normalize_text(value) for value in eligible["RowID"].tolist() if normalize_text(value)}
                result = result[result["RowID"].map(normalize_text).isin(row_ids)].copy()

    if periods is not None:
        result = _history_month_filter(result, periods.month)
        result = _text_filter(result, "History Quarter", periods.quarter)
        result = _numeric_filter(result, "History Year", periods.year)
    return result


def ensure_history_periods(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    if "Timestamp" not in result.columns:
        return result
    timestamps = pd.to_datetime(result["Timestamp"], errors="coerce")
    result["History Year"] = timestamps.dt.year.astype("Int64")
    result["History Month"] = timestamps.dt.month.astype("Int64")
    result["History Month Label"] = timestamps.dt.strftime("%Y-%m").fillna("Unknown")
    result["History Quarter"] = timestamps.map(
        lambda value: f"{value.year} Q{((value.month - 1) // 3) + 1}" if not pd.isna(value) else "Unknown"
    )
    return result


def eta_period_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    eta = pd.to_datetime(result.get("ETA", pd.Series(pd.NaT, index=result.index)), errors="coerce")
    result["ETA Year"] = eta.dt.year.astype("Int64")
    result["ETA Month"] = eta.dt.strftime("%Y-%m").fillna("Unknown")
    result["ETA Month Number"] = eta.dt.month.astype("Int64")
    return result


def _needs_current_crosswalk(context: FilterContext) -> bool:
    return any(
        value is not None
        for value in [
            context.eta_month,
            context.eta_year,
            context.svc,
            context.pol,
            context.pod,
            context.customer,
            context.load_status,
            context.row_status,
        ]
    )


def _text_filter(df: pd.DataFrame, column: str, accepted: FilterValue) -> pd.DataFrame:
    if accepted is None:
        return df
    if column not in df.columns:
        return df.iloc[0:0].copy()
    allowed = {normalize_text(value) for value in _as_list(accepted)}
    return df[df[column].map(normalize_text).isin(allowed)].copy()


def _numeric_filter(df: pd.DataFrame, column: str, accepted: FilterValue) -> pd.DataFrame:
    if accepted is None:
        return df
    if column not in df.columns:
        return df.iloc[0:0].copy()
    allowed = pd.to_numeric(pd.Series(_as_list(accepted), dtype=object), errors="coerce").dropna().tolist()
    if not allowed:
        return df.iloc[0:0].copy()
    return df[pd.to_numeric(df[column], errors="coerce").isin(allowed)].copy()


def _history_text_filter(df: pd.DataFrame, column: str, accepted: FilterValue) -> pd.DataFrame:
    if accepted is None:
        return df
    if column not in df.columns:
        return df.iloc[0:0].copy()
    values = df[column].astype(object)
    current_column = f"Current {column}"
    if current_column in df.columns and IDENTITY_RESOLUTION_COLUMN in df.columns:
        resolved = df[IDENTITY_RESOLUTION_COLUMN].eq(IDENTITY_RESOLVED)
        values = values.where(~resolved, df[current_column].astype(object))
    allowed = {normalize_text(value) for value in _as_list(accepted)}
    return df[values.map(normalize_text).isin(allowed)].copy()


def _history_numeric_filter(df: pd.DataFrame, column: str, accepted: FilterValue) -> pd.DataFrame:
    if accepted is None:
        return df
    if column not in df.columns:
        return df.iloc[0:0].copy()
    values = df[column].astype(object)
    current_column = f"Current {column}"
    if current_column in df.columns and IDENTITY_RESOLUTION_COLUMN in df.columns:
        resolved = df[IDENTITY_RESOLUTION_COLUMN].eq(IDENTITY_RESOLVED)
        values = values.where(~resolved, df[current_column].astype(object))
    allowed = pd.to_numeric(pd.Series(_as_list(accepted), dtype=object), errors="coerce").dropna().tolist()
    if not allowed:
        return df.iloc[0:0].copy()
    return df[pd.to_numeric(values, errors="coerce").isin(allowed)].copy()


def _row_status_filter(df: pd.DataFrame, accepted: FilterValue) -> pd.DataFrame:
    if accepted is None:
        return df
    if "RowStatus" not in df.columns:
        return df.iloc[0:0].copy()
    allowed = {normalize_text(value) for value in _as_list(accepted)}
    normalized = df["RowStatus"].map(normalize_text)
    mask = normalized.isin(allowed)
    if "active" in allowed:
        mask |= normalized.eq("")
    return df[mask].copy()


def _eta_year_filter(df: pd.DataFrame, accepted: FilterValue) -> pd.DataFrame:
    if accepted is None:
        return df
    enriched = eta_period_columns(df)
    return _numeric_filter(enriched, "ETA Year", accepted)


def _eta_month_filter(df: pd.DataFrame, accepted: FilterValue) -> pd.DataFrame:
    if accepted is None:
        return df
    enriched = eta_period_columns(df)
    values = _as_list(accepted)
    numeric = pd.to_numeric(pd.Series(values, dtype=object), errors="coerce")
    allowed_numbers = {int(value) for value in numeric.dropna().tolist() if 1 <= int(value) <= 12}
    allowed_labels = {normalize_text(value) for value in values if pd.isna(pd.to_numeric(value, errors="coerce"))}
    mask = enriched["ETA Month Number"].isin(allowed_numbers)
    if allowed_labels:
        mask |= enriched["ETA Month"].map(normalize_text).isin(allowed_labels)
    return enriched[mask].copy()


def _history_month_filter(df: pd.DataFrame, accepted: FilterValue) -> pd.DataFrame:
    if accepted is None:
        return df
    values = _as_list(accepted)
    numeric = pd.to_numeric(pd.Series(values, dtype=object), errors="coerce")
    allowed_numbers = {int(value) for value in numeric.dropna().tolist() if 1 <= int(value) <= 12}
    allowed_labels = {normalize_text(value) for value in values if pd.isna(pd.to_numeric(value, errors="coerce"))}
    mask = df["History Month"].isin(allowed_numbers)
    if allowed_labels:
        mask |= df["History Month Label"].map(normalize_text).isin(allowed_labels)
    return df[mask].copy()


def _as_list(value: FilterValue) -> list[Any]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        return [value]
    return list(value)
