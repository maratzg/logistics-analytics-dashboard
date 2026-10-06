from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from .analytical_filters import FilterContext, HistoryPeriodContext, apply_current_filters, apply_history_filters, ensure_history_periods, eta_period_columns
from .date_utils import is_meaningful_value, normalize_text
from .history_processing import deduplicate_voyage_events, history_with_current_context, is_legacy_unavailable
from .operational_analytics import aggregate_current
from .operational_calculations import cancelled_mask


CHURN_FIELDS = ["CNTR AMT", "Week", "ETA", "ETD", "Cut-Off", "RowStatus", "LoadStatus", "SIZE", "GWT"]


def booking_churn(
    history_df: pd.DataFrame,
    *,
    level: str = "RowID",
    context: FilterContext | None = None,
    current_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return explainable revision counts without combining them into a score."""

    canonical_level = _canonical_level(level)
    history = apply_history_filters(history_df, context, current_df=current_df)
    if canonical_level == "Voyage":
        history = history_with_current_context(deduplicate_voyage_events(history))
        group_columns = ["Vessel", "Voyage", "BlockID"]
    else:
        group_columns = [canonical_level]

    columns = group_columns + ["Total History Events", "Material Revisions"] + [f"{field} Revisions" for field in CHURN_FIELDS] + ["Cancellation Events"]
    if history.empty or not all(column in history.columns for column in group_columns):
        return pd.DataFrame(columns=columns)

    working = history.copy()
    for column in group_columns:
        working[f"_group_{column}"] = working[column].map(normalize_text)
    keys = [f"_group_{column}" for column in group_columns]
    working = working[working[keys].apply(lambda row: any(bool(value) for value in row), axis=1)].copy()
    output: list[dict[str, Any]] = []
    for _, group in working.groupby(keys, dropna=False, sort=True):
        material = group.apply(_is_material_change, axis=1)
        fields = group.get("Field", pd.Series(index=group.index, dtype=object)).map(normalize_text)
        row = {column: _first(group, column) for column in group_columns}
        row["Total History Events"] = int(len(group))
        row["Material Revisions"] = int(material.sum())
        for field in CHURN_FIELDS:
            row[f"{field} Revisions"] = int((material & fields.eq(normalize_text(field))).sum())
        row["Cancellation Events"] = int(group.apply(_is_cancellation_event, axis=1).sum())
        output.append(row)
    return pd.DataFrame(output, columns=columns)


def booking_event_timeline(
    history_df: pd.DataFrame,
    *,
    row_id: Any | None = None,
    booking_number: Any | None = None,
    vessel: Any | None = None,
    voyage: Any | None = None,
    block_id: Any | None = None,
) -> pd.DataFrame:
    result = history_with_current_context(history_df)
    for column, value in [
        ("RowID", row_id),
        ("Booking number", booking_number),
        ("Vessel", vessel),
        ("Voyage", voyage),
        ("BlockID", block_id),
    ]:
        if value is not None:
            if column not in result.columns:
                return result.iloc[0:0].copy()
            result = result[result[column].map(normalize_text).eq(normalize_text(value))].copy()
    if "Timestamp" in result.columns:
        result["_sort_timestamp"] = pd.to_datetime(result["Timestamp"], errors="coerce")
        result = result.sort_values("_sort_timestamp", kind="mergesort").drop(columns="_sort_timestamp")
    return result.reset_index(drop=True)


def cancellation_events(
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    periods: HistoryPeriodContext | None = None,
    current_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    history = apply_history_filters(history_df, context, periods=periods, current_df=current_df)
    if history.empty:
        return history.copy()
    mask = history.apply(_is_cancellation_event, axis=1)
    return history[mask].copy().reset_index(drop=True)


def cancellation_summary_by(
    weekly_df: pd.DataFrame,
    by: str | Iterable[str],
    context: FilterContext | None = None,
) -> pd.DataFrame:
    grouped = aggregate_current(weekly_df, by, context, include_blank=True)
    group_columns = [by] if isinstance(by, str) else list(by)
    columns = group_columns + ["Booking/Row Count", "Cancelled rows", "Cancellation Rate"]
    return grouped[[column for column in columns if column in grouped.columns]].copy()


def cancellation_reasons(
    weekly_df: pd.DataFrame,
    context: FilterContext | None = None,
) -> pd.DataFrame:
    current = apply_current_filters(weekly_df, context)
    cancelled = current[cancelled_mask(current)].copy()
    if cancelled.empty:
        return pd.DataFrame(columns=["CancelReason", "Cancelled rows"])
    reasons = cancelled.get("CancelReason", pd.Series(index=cancelled.index, dtype=object)).map(
        lambda value: str(value).strip() if is_meaningful_value(value) else "Unspecified"
    )
    return reasons.value_counts(dropna=False).rename_axis("CancelReason").reset_index(name="Cancelled rows")


def current_cancellation_trend(
    weekly_df: pd.DataFrame,
    *,
    period: str = "Week",
    context: FilterContext | None = None,
) -> pd.DataFrame:
    current = eta_period_columns(apply_current_filters(weekly_df, context))
    cancelled = current[cancelled_mask(current)].copy()
    period_column = _current_period_column(period)
    if cancelled.empty or period_column not in cancelled.columns:
        return pd.DataFrame(columns=[period_column, "Current Cancelled Rows"])
    return cancelled.groupby(period_column, dropna=False).size().reset_index(name="Current Cancelled Rows")


def historical_cancellation_trend(
    history_df: pd.DataFrame,
    *,
    period: str = "History Month",
    context: FilterContext | None = None,
    current_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    events = ensure_history_periods(cancellation_events(history_df, context, current_df=current_df))
    period_column = _history_period_column(period)
    if events.empty or period_column not in events.columns:
        return pd.DataFrame(columns=[period_column, "Cancellation Events"])
    return events.groupby(period_column, dropna=False).size().reset_index(name="Cancellation Events")


def _is_material_change(row: pd.Series) -> bool:
    old_value = row.get("OldValue")
    new_value = row.get("NewValue")
    if is_legacy_unavailable(row.get("_raw_OldValue", old_value)) or is_legacy_unavailable(row.get("_raw_NewValue", new_value)):
        return False
    if not is_meaningful_value(old_value) or not is_meaningful_value(new_value):
        return False
    return normalize_text(old_value) != normalize_text(new_value)


def _is_cancellation_event(row: pd.Series) -> bool:
    field = "".join(character for character in normalize_text(row.get("Field")) if character.isalnum())
    return field == "rowstatus" and normalize_text(row.get("NewValue")) == "cancelled" and normalize_text(row.get("OldValue")) != "cancelled"


def _canonical_level(level: str) -> str:
    lookup = {"rowid": "RowID", "booking": "Booking number", "booking number": "Booking number", "voyage": "Voyage"}
    key = normalize_text(level)
    if key not in lookup:
        raise ValueError("level must be RowID, Booking number, or Voyage")
    return lookup[key]


def _first(df: pd.DataFrame, column: str) -> Any:
    if column not in df.columns:
        return None
    for value in df[column].tolist():
        if is_meaningful_value(value):
            return value
    return None


def _current_period_column(period: str) -> str:
    lookup = {"week": "Week", "eta month": "ETA Month", "eta year": "ETA Year"}
    key = normalize_text(period)
    if key not in lookup:
        raise ValueError("Current cancellation period must be Week, ETA Month, or ETA Year")
    return lookup[key]


def _history_period_column(period: str) -> str:
    lookup = {"history month": "History Month Label", "history quarter": "History Quarter", "history year": "History Year"}
    key = normalize_text(period)
    if key not in lookup:
        raise ValueError("Historical cancellation period must be History Month, History Quarter, or History Year")
    return lookup[key]
