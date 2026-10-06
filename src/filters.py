from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import pandas as pd

from .analytical_filters import FilterContext, HistoryPeriodContext, apply_current_filters, apply_history_filters
from .date_utils import normalize_text
from .schema import EXPANDED_HISTORY_FIELDS, SCHEDULE_FIELDS


FIELD_ALIASES = {
    "eta": "ETA",
    "etd": "ETD",
    "cut off": "Cut-Off",
    "cut-off": "Cut-Off",
    "cutoff": "Cut-Off",
    "eta t/s": "ETA T/S",
    "eta ts": "ETA T/S",
    "eta t s": "ETA T/S",
    "vessel": "Vessel",
    "voyage": "Voyage",
    "week": "Week",
    "booking status": "Booking status",
    "loadstatus": "LoadStatus",
    "load status": "LoadStatus",
    "cntr amt": "CNTR AMT",
    "size": "SIZE",
    "type": "TYPE",
    "gwt": "GWT",
    "rowstatus": "RowStatus",
    "row status": "RowStatus",
    "cancelreason": "CancelReason",
    "cancel reason": "CancelReason",
}

REVISION_TRACKED_FIELDS = EXPANDED_HISTORY_FIELDS


def filter_weekly(
    df: pd.DataFrame,
    *,
    vessel: Any | Iterable[Any] | None = None,
    voyage: Any | Iterable[Any] | None = None,
    week: Any | Iterable[Any] | None = None,
    month: Any | Iterable[Any] | None = None,
    year: Any | Iterable[Any] | None = None,
    row_status: Any | Iterable[Any] | None = None,
    block_id: Any | Iterable[Any] | None = None,
    row_id: Any | Iterable[Any] | None = None,
) -> pd.DataFrame:
    """Return a filtered copy of WEEKLY data without mutating the source frame."""

    result = apply_current_filters(
        df,
        FilterContext(vessel=vessel, voyage=voyage, week=week, eta_month=month, eta_year=year, row_status=row_status),
        operational_only=False,
    )
    result = _apply_text_filter(result, "BlockID", block_id)
    result = _apply_text_filter(result, "RowID", row_id)
    return result


def filter_history(
    df: pd.DataFrame,
    *,
    vessel: Any | Iterable[Any] | None = None,
    voyage: Any | Iterable[Any] | None = None,
    week: Any | Iterable[Any] | None = None,
    month: Any | Iterable[Any] | None = None,
    year: Any | Iterable[Any] | None = None,
    user: Any | Iterable[Any] | None = None,
    field: Any | Iterable[Any] | None = None,
    block_id: Any | Iterable[Any] | None = None,
    row_id: Any | Iterable[Any] | None = None,
    booking_number: Any | Iterable[Any] | None = None,
    quarter: Any | Iterable[Any] | None = None,
) -> pd.DataFrame:
    """Return a filtered copy of LOG_HISTORY without mutating the source frame."""

    result = apply_history_filters(
        df,
        FilterContext(vessel=vessel, voyage=voyage, week=week),
        periods=HistoryPeriodContext(month=month, quarter=quarter, year=year),
    )
    result = _apply_text_filter(result, "User", user)
    result = _apply_text_filter(result, "BlockID", block_id)
    result = _apply_text_filter(result, "RowID", row_id)
    result = _apply_text_filter(result, "Booking number", booking_number)

    if field is not None:
        if "Field" not in result.columns:
            return result.iloc[0:0].copy()
        allowed = {normalize_field_name(value) for value in _as_list(field)}
        mask = result["Field"].map(normalize_field_name).isin(allowed)
        result = result[mask].copy()

    return result


def filter_weekly_by_vessel(df: pd.DataFrame, vessel: Any) -> pd.DataFrame:
    return filter_weekly(df, vessel=vessel)


def filter_weekly_by_voyage(df: pd.DataFrame, voyage: Any) -> pd.DataFrame:
    return filter_weekly(df, voyage=voyage)


def filter_history_by_row_id(df: pd.DataFrame, row_id: Any) -> pd.DataFrame:
    return filter_history(df, row_id=row_id)


def filter_history_by_voyage(df: pd.DataFrame, voyage: Any) -> pd.DataFrame:
    return filter_history(df, voyage=voyage)


def filter_history_by_vessel(df: pd.DataFrame, vessel: Any) -> pd.DataFrame:
    return filter_history(df, vessel=vessel)


def normalize_field_name(value: Any) -> str:
    normalized = normalize_text(value)
    normalized_without_punctuation = re.sub(r"[-_]+", " ", normalized)
    normalized_without_punctuation = " ".join(normalized_without_punctuation.split())
    return FIELD_ALIASES.get(normalized, FIELD_ALIASES.get(normalized_without_punctuation, str(value or "").strip()))


def _apply_text_filter(df: pd.DataFrame, column: str, accepted: Any | Iterable[Any] | None) -> pd.DataFrame:
    if accepted is None:
        return df
    if column not in df.columns:
        return df.iloc[0:0].copy()
    allowed = {normalize_text(value) for value in _as_list(accepted)}
    mask = df[column].map(normalize_text).isin(allowed)
    return df[mask].copy()


def _as_list(value: Any | Iterable[Any]) -> list[Any]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]
