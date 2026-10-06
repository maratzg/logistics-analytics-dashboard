from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .analytical_filters import FilterContext
from .operational_analytics import voyage_load_profiles
from .schedule_analytics import schedule_reliability_by_voyage, week_rollover_by_voyage


COMPARISON_COLUMNS = [
    "IdentityKey",
    "Vessel",
    "Voyage",
    "BlockID",
    "Week",
    "ETA",
    "Total Containers",
    "Loaded Containers",
    "Empty Containers",
    "Loaded %",
    "Empty %",
    "Total 20ft",
    "Total 40ft",
    "Total TEU",
    "Loaded TEU",
    "Empty TEU",
    "Total GWT",
    "Loaded GWT",
    "Empty GWT",
    "Loaded GWT / Loaded TEU",
    "ETA Revision Count",
    "Net ETA Movement",
    "Cumulative ETA Movement",
    "Largest Single ETA Revision",
    "Week Change Count",
    "Cancelled rows",
]


def comparison_candidates(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
) -> pd.DataFrame:
    profiles = voyage_load_profiles(weekly_df, context)
    schedule = schedule_reliability_by_voyage(weekly_df, history_df, context)
    rollover = week_rollover_by_voyage(weekly_df, history_df, context)
    if profiles.empty:
        return pd.DataFrame(columns=COMPARISON_COLUMNS)
    result = profiles.merge(
        schedule[["IdentityKey", "ETA Revision Count", "Net ETA Movement", "Cumulative ETA Movement", "Largest Single ETA Revision"]],
        on="IdentityKey",
        how="left",
    )
    result = result.merge(rollover[["IdentityKey", "Week Change Count"]], on="IdentityKey", how="left", suffixes=("", " Rollover"))
    if "Week Change Count Rollover" in result.columns:
        result["Week Change Count"] = result["Week Change Count Rollover"].combine_first(result.get("Week Change Count"))
    return result[[column for column in COMPARISON_COLUMNS if column in result.columns]].copy()


def compare_voyage_instances(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    identity_keys: Iterable[str],
    context: FilterContext | None = None,
    *,
    candidates_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    selected = list(dict.fromkeys(str(value) for value in identity_keys))
    if not 2 <= len(selected) <= 5:
        raise ValueError("Comparison requires 2 to 5 distinct voyage IdentityKey values.")
    candidates = candidates_df.copy() if candidates_df is not None else comparison_candidates(weekly_df, history_df, context)
    result = candidates[candidates["IdentityKey"].isin(selected)].copy()
    missing = [key for key in selected if key not in set(result["IdentityKey"])]
    if missing:
        raise ValueError(f"Unknown or unavailable voyage IdentityKey value(s): {', '.join(missing)}")
    order = {key: index for index, key in enumerate(selected)}
    result["_selection_order"] = result["IdentityKey"].map(order)
    return result.sort_values("_selection_order", kind="mergesort").drop(columns="_selection_order").reset_index(drop=True)
