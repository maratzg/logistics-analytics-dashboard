from __future__ import annotations

import pandas as pd

from .analytical_filters import FilterContext, HistoryPeriodContext, apply_history_filters
from .history_processing import deduplicate_voyage_events
from .operational_analytics import aggregate_current


CURRENT_PERIODS = {"week": "Week", "eta month": "ETA Month", "eta year": "ETA Year"}
HISTORY_PERIODS = {"history month": "History Month Label", "history quarter": "History Quarter", "history year": "History Year"}


def current_period_aggregation(
    weekly_df: pd.DataFrame,
    period: str,
    context: FilterContext | None = None,
    *,
    trailing_window: int | None = None,
) -> pd.DataFrame:
    column = _period_column(period, CURRENT_PERIODS)
    frame = aggregate_current(weekly_df, column, context)
    if frame.empty:
        return frame
    frame = frame.sort_values(column, kind="mergesort").reset_index(drop=True)
    if trailing_window is not None and trailing_window > 1:
        for metric in ["Total Containers", "Total TEU", "Total GWT", "Loaded Containers", "Empty Containers", "Cancelled rows"]:
            if metric in frame.columns:
                values = pd.to_numeric(frame[metric], errors="coerce")
                frame[f"{metric} {trailing_window}-Period Average"] = values.rolling(trailing_window, min_periods=trailing_window).mean()
    return frame


def history_period_aggregation(
    history_df: pd.DataFrame,
    period: str,
    context: FilterContext | None = None,
    *,
    periods: HistoryPeriodContext | None = None,
    current_df: pd.DataFrame | None = None,
    voyage_events: bool = False,
) -> pd.DataFrame:
    column = _period_column(period, HISTORY_PERIODS)
    history = apply_history_filters(history_df, context, periods=periods, current_df=current_df)
    if voyage_events:
        history = deduplicate_voyage_events(history)
    if history.empty or column not in history.columns:
        return pd.DataFrame(columns=[column, "History Events"])
    usable = history[history[column].notna()].copy()
    return usable.groupby(column, dropna=False).size().reset_index(name="History Events").sort_values(column, kind="mergesort").reset_index(drop=True)


def _period_column(period: str, available: dict[str, str]) -> str:
    normalized = " ".join(period.strip().casefold().split())
    if normalized not in available:
        raise ValueError(f"Unsupported period {period!r}; expected one of: {', '.join(available.values())}.")
    return available[normalized]
