from __future__ import annotations

from typing import Any

import pandas as pd

from .analytical_filters import FilterContext, apply_current_filters
from .date_utils import is_meaningful_value, normalize_text
from .operational_analytics import aggregate_current, safe_divide
from .schedule_analytics import aggregate_schedule_reliability, aggregate_week_rollover, schedule_reliability_by_voyage, week_rollover_by_voyage


def customer_analytics(weekly_df: pd.DataFrame, context: FilterContext | None = None) -> pd.DataFrame:
    grouped = aggregate_current(weekly_df, "CUSTOMER", context, include_blank=True)
    if grouped.empty:
        return grouped
    grouped["CUSTOMER"] = grouped["CUSTOMER"].map(_display_or_unspecified)
    total_teu = pd.to_numeric(grouped["Total TEU"], errors="coerce").fillna(0).sum()
    grouped["Average Booking Size"] = [safe_divide(containers, rows) for containers, rows in zip(grouped["Total Containers"], grouped["Active rows"], strict=False)]
    grouped["Share of Overall TEU"] = [safe_divide(value, total_teu) for value in grouped["Total TEU"]]
    columns = [
        "CUSTOMER",
        "Voyage Count",
        "Booking/Row Count",
        "Active rows",
        "Cancelled rows",
        "Cancellation Rate",
        "Total Containers",
        "Loaded Containers",
        "Empty Containers",
        "Unclassified Containers",
        "Total TEU",
        "Total GWT",
        "Total 20ft Share",
        "Total 40ft Share",
        "Loaded %",
        "Empty %",
        "Average Booking Size",
        "Share of Overall TEU",
    ]
    return grouped[columns].sort_values(["Total TEU", "CUSTOMER"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def customer_pod_distribution(weekly_df: pd.DataFrame, context: FilterContext | None = None) -> pd.DataFrame:
    frame = aggregate_current(weekly_df, ["CUSTOMER", "POD"], context, include_blank=True)
    if frame.empty:
        return frame
    frame["CUSTOMER"] = frame["CUSTOMER"].map(_display_or_unspecified)
    frame["POD"] = frame["POD"].map(_display_or_unspecified)
    return frame[["CUSTOMER", "POD", "Voyage Count", "Total Containers", "Total TEU"]]


def customer_voyage_distribution(weekly_df: pd.DataFrame, context: FilterContext | None = None) -> pd.DataFrame:
    frame = aggregate_current(weekly_df, ["CUSTOMER", "Vessel", "Voyage", "BlockID"], context, include_blank=True)
    if frame.empty:
        return frame
    frame["CUSTOMER"] = frame["CUSTOMER"].map(_display_or_unspecified)
    return frame[["CUSTOMER", "Vessel", "Voyage", "BlockID", "Booking/Row Count", "Total Containers", "Total TEU"]]


def customer_trend(weekly_df: pd.DataFrame, context: FilterContext | None = None) -> pd.DataFrame:
    frame = aggregate_current(weekly_df, ["CUSTOMER", "ETA Month"], context, include_blank=True)
    if frame.empty:
        return frame
    frame["CUSTOMER"] = frame["CUSTOMER"].map(_display_or_unspecified)
    return frame[["CUSTOMER", "ETA Month", "Total Containers", "Total TEU", "Total GWT", "Voyage Count"]]


def service_analytics(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
) -> pd.DataFrame:
    operational = aggregate_current(weekly_df, "SVC", context, include_blank=True)
    if operational.empty:
        return operational
    operational["SVC"] = operational["SVC"].map(_display_or_unspecified)
    current = apply_current_filters(weekly_df, context)
    schedule = schedule_reliability_by_voyage(weekly_df, history_df, context)
    schedule_summary = aggregate_schedule_reliability(schedule, "SVC")
    rollover = week_rollover_by_voyage(weekly_df, history_df, context)
    rollover_summary = aggregate_week_rollover(rollover, "SVC")

    schedule_columns = ["SVC", "Mean Net ETA Movement", "Median Net ETA Movement", "Median ETA Revision Count", "Median Cumulative ETA Movement"]
    rollover_columns = ["SVC", "% Voyages Moved Week"]
    result = operational.merge(schedule_summary[[column for column in schedule_columns if column in schedule_summary.columns]], on="SVC", how="left")
    result = result.merge(rollover_summary[[column for column in rollover_columns if column in rollover_summary.columns]], on="SVC", how="left")
    result["Schedule Volatility"] = result.get("Median Cumulative ETA Movement")
    result["Customer Count"] = result["SVC"].map(lambda service: _distinct_count(current, "CUSTOMER", "SVC", service))
    result["Major PODs"] = result["SVC"].map(lambda service: _major_values(current, "POD", "SVC", service))
    columns = [
        "SVC",
        "Voyage Count",
        "Total Containers",
        "Total TEU",
        "Total GWT",
        "Loaded %",
        "Empty %",
        "Total 20ft Share",
        "Total 40ft Share",
        "Cancellation Rate",
        "Mean Net ETA Movement",
        "Median Net ETA Movement",
        "Median ETA Revision Count",
        "Median Cumulative ETA Movement",
        "Schedule Volatility",
        "% Voyages Moved Week",
        "Customer Count",
        "Major PODs",
    ]
    return result[[column for column in columns if column in result.columns]].sort_values("SVC", kind="mergesort").reset_index(drop=True)


def service_voyage_drilldown(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    service: Any,
) -> pd.DataFrame:
    context = FilterContext(svc=service)
    load = aggregate_current(weekly_df, ["SVC", "Vessel", "Voyage", "BlockID"], context)
    schedule = schedule_reliability_by_voyage(weekly_df, history_df, context)
    if load.empty:
        return load
    return load.merge(schedule, on=["Vessel", "Voyage", "BlockID"], how="left", suffixes=("", " Schedule"))


def route_destination_analytics(weekly_df: pd.DataFrame, context: FilterContext | None = None) -> pd.DataFrame:
    result = aggregate_current(weekly_df, ["POD", "POD CODE"], context, include_blank=True)
    if result.empty:
        return result
    result["POD"] = result["POD"].map(_display_or_unspecified)
    result["POD CODE"] = result["POD CODE"].map(_display_or_unspecified)
    current = apply_current_filters(weekly_df, context)
    result["Service Mix"] = result["POD"].map(lambda pod: _major_values(current, "SVC", "POD", pod, limit=5))
    columns = [
        "POD",
        "POD CODE",
        "Voyage Count",
        "Total Containers",
        "Loaded Containers",
        "Empty Containers",
        "Unclassified Containers",
        "Total TEU",
        "Total GWT",
        "Total 20ft Share",
        "Total 40ft Share",
        "Service Mix",
    ]
    return result[columns].sort_values(["Total TEU", "POD"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def _display_or_unspecified(value: Any) -> str:
    return str(value).strip() if is_meaningful_value(value) else "Unspecified"


def _matching(df: pd.DataFrame, filter_column: str, value: Any) -> pd.DataFrame:
    if filter_column not in df.columns:
        return df.iloc[0:0].copy()
    if normalize_text(value) == "unspecified":
        return df[~df[filter_column].map(is_meaningful_value)].copy()
    return df[df[filter_column].map(normalize_text).eq(normalize_text(value))].copy()


def _distinct_count(df: pd.DataFrame, target_column: str, filter_column: str, value: Any) -> int:
    subset = _matching(df, filter_column, value)
    if target_column not in subset.columns:
        return 0
    return len({normalize_text(item) for item in subset[target_column].tolist() if normalize_text(item)})


def _major_values(df: pd.DataFrame, target_column: str, filter_column: str, value: Any, *, limit: int = 3) -> str:
    subset = _matching(df, filter_column, value)
    if target_column not in subset.columns or subset.empty:
        return ""
    values = subset[target_column].map(lambda item: str(item).strip() if is_meaningful_value(item) else "Unspecified")
    counts = values.value_counts()
    return ", ".join(counts.head(limit).index.tolist())
