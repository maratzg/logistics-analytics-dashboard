from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from .analytical_filters import FilterContext, apply_current_filters, eta_period_columns
from .anomaly_detection import distribution_summary
from .analytics import calculate_weekly_metrics
from .date_utils import is_meaningful_value, normalize_text
from .operational_calculations import cancelled_mask


VOYAGE_IDENTITY_COLUMNS = ["Vessel", "Voyage", "BlockID"]
PROFILE_METRIC_COLUMNS = [
    "Active rows",
    "Cancelled rows",
    "Cancellation Rate",
    "Total Containers",
    "Loaded Containers",
    "Empty Containers",
    "Unclassified Containers",
    "Loaded %",
    "Empty %",
    "Classified Containers",
    "Empty Container Ratio",
    "Total 20ft",
    "Loaded 20ft",
    "Empty 20ft",
    "Total 40ft",
    "Loaded 40ft",
    "Empty 40ft",
    "Total TEU",
    "Loaded TEU",
    "Empty TEU",
    "Unclassified TEU",
    "Classified TEU",
    "Empty TEU Ratio",
    "Total GWT",
    "Loaded GWT",
    "Empty GWT",
    "Unclassified GWT",
    "Loaded GWT / Loaded TEU",
    "Loaded GWT / Loaded Container",
    "Total GWT / Total TEU",
    "Total 20ft Share",
    "Total 40ft Share",
    "Loaded 20ft Share",
    "Loaded 40ft Share",
    "Empty 20ft Share",
    "Empty 40ft Share",
]


def current_operational_metrics(weekly_df: pd.DataFrame, context: FilterContext | None = None):
    return calculate_weekly_metrics(apply_current_filters(weekly_df, context))


def voyage_load_profiles(weekly_df: pd.DataFrame, context: FilterContext | None = None) -> pd.DataFrame:
    rows = apply_current_filters(weekly_df, context)
    identity_columns = VOYAGE_IDENTITY_COLUMNS
    output_columns = identity_columns + ["IdentityKey", "Week", "SVC", "POL", "POD", "ETA", "ETD", "Cut-Off"] + PROFILE_METRIC_COLUMNS
    if rows.empty or not all(column in rows.columns for column in identity_columns):
        return pd.DataFrame(columns=output_columns)

    # Voyage-level analytics must never merge records whose composite identity
    # is incomplete. Those rows remain in current totals and are surfaced by
    # the quality engine, but cannot be assigned safely to a voyage instance.
    working = rows[_complete_voyage_identity_mask(rows)].copy()
    if working.empty:
        return pd.DataFrame(columns=output_columns)
    for column in identity_columns:
        working[f"_identity_{column}"] = working[column].map(normalize_text)

    profiles: list[dict[str, Any]] = []
    keys = [f"_identity_{column}" for column in identity_columns]
    for _, group in working.groupby(keys, dropna=False, sort=True):
        row = _metric_row(group)
        row.update(
            {
                "Vessel": _first_meaningful(group, "Vessel"),
                "Voyage": _first_meaningful(group, "Voyage"),
                "BlockID": _first_meaningful(group, "BlockID"),
                "Week": _first_meaningful(group, "Week"),
                "SVC": _first_meaningful(group, "SVC"),
                "POL": _first_meaningful(group, "POL"),
                "POD": _first_meaningful(group, "POD"),
                "ETA": _first_meaningful(group, "ETA"),
                "ETD": _first_meaningful(group, "ETD"),
                "Cut-Off": _first_meaningful(group, "Cut-Off"),
            }
        )
        row["IdentityKey"] = voyage_identity_key(row["Vessel"], row["Voyage"], row["BlockID"])
        profiles.append(row)
    return pd.DataFrame(profiles, columns=output_columns).sort_values(identity_columns, kind="mergesort").reset_index(drop=True)


def aggregate_current(
    weekly_df: pd.DataFrame,
    by: str | Iterable[str],
    context: FilterContext | None = None,
    *,
    include_blank: bool = False,
) -> pd.DataFrame:
    group_columns = [by] if isinstance(by, str) else list(by)
    rows = eta_period_columns(apply_current_filters(weekly_df, context))
    output_columns = group_columns + ["Voyage Count", "Booking/Row Count"] + PROFILE_METRIC_COLUMNS
    if rows.empty or not all(column in rows.columns for column in group_columns):
        return pd.DataFrame(columns=output_columns)

    working = rows.copy()
    keys = []
    for position, column in enumerate(group_columns):
        key = f"_group_{position}"
        if pd.api.types.is_numeric_dtype(working[column]):
            working[key] = pd.to_numeric(working[column], errors="coerce")
        else:
            working[key] = working[column].map(normalize_text)
        keys.append(key)
    if not include_blank:
        mask = pd.Series(True, index=working.index)
        for key in keys:
            mask &= working[key].map(is_meaningful_value)
        working = working[mask].copy()
    if working.empty:
        return pd.DataFrame(columns=output_columns)

    output: list[dict[str, Any]] = []
    for _, group in working.groupby(keys, dropna=False, sort=True):
        row = {column: _first_meaningful(group, column) for column in group_columns}
        row["Voyage Count"] = _voyage_count(group)
        row["Booking/Row Count"] = int(len(group))
        row.update(_metric_row(group))
        output.append(row)
    return pd.DataFrame(output, columns=output_columns).sort_values(group_columns, kind="mergesort").reset_index(drop=True)


def empty_container_analytics(weekly_df: pd.DataFrame, by: str | Iterable[str], context: FilterContext | None = None) -> pd.DataFrame:
    frame = aggregate_current(weekly_df, by, context)
    columns = ([by] if isinstance(by, str) else list(by)) + [
        "Voyage Count",
        "Classified Containers",
        "Empty Containers",
        "Empty Container Ratio",
        "Unclassified Containers",
        "Classified TEU",
        "Empty TEU",
        "Empty TEU Ratio",
        "Unclassified TEU",
    ]
    return frame[[column for column in columns if column in frame.columns]].copy()


def highest_empty_ratio_voyages(
    weekly_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    limit: int = 10,
) -> pd.DataFrame:
    profiles = voyage_load_profiles(weekly_df, context)
    profiles = profiles[profiles["Empty TEU Ratio"].notna()].copy()
    return profiles.sort_values(["Empty TEU Ratio", "IdentityKey"], ascending=[False, True], kind="mergesort").head(limit).reset_index(drop=True)


def equipment_mix(
    weekly_df: pd.DataFrame,
    by: str | Iterable[str],
    context: FilterContext | None = None,
) -> pd.DataFrame:
    frame = aggregate_current(weekly_df, by, context)
    group_columns = [by] if isinstance(by, str) else list(by)
    columns = group_columns + [
        "Total 20ft",
        "Total 40ft",
        "Total 20ft Share",
        "Total 40ft Share",
        "Loaded 20ft",
        "Loaded 40ft",
        "Loaded 20ft Share",
        "Loaded 40ft Share",
        "Empty 20ft",
        "Empty 40ft",
        "Empty 20ft Share",
        "Empty 40ft Share",
    ]
    return frame[[column for column in columns if column in frame.columns]].copy()


def weight_intensity_profiles(
    weekly_df: pd.DataFrame,
    context: FilterContext | None = None,
) -> pd.DataFrame:
    frame = voyage_load_profiles(weekly_df, context)
    columns = VOYAGE_IDENTITY_COLUMNS + [
        "IdentityKey",
        "SVC",
        "Loaded GWT / Loaded TEU",
        "Loaded GWT / Loaded Container",
        "Total GWT / Total TEU",
    ]
    return frame[[column for column in columns if column in frame.columns]].copy()


def weight_intensity_distribution(
    weekly_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    group_by: str | None = None,
    minimum_sample: int = 5,
) -> pd.DataFrame:
    profiles = voyage_load_profiles(weekly_df, context)
    columns = ([group_by] if group_by else []) + ["Metric", "Sample Size", "P10", "P25", "Median", "P75", "P90", "IQR"]
    if profiles.empty:
        return pd.DataFrame(columns=columns)
    groups = list(profiles.groupby(group_by, dropna=False, sort=True)) if group_by and group_by in profiles.columns else [(None, profiles)]
    output: list[dict[str, Any]] = []
    for group_value, group in groups:
        for metric in ["Loaded GWT / Loaded TEU", "Loaded GWT / Loaded Container", "Total GWT / Total TEU"]:
            summary = distribution_summary(group[metric], minimum_sample=minimum_sample)
            if summary is None:
                continue
            row = {"Metric": metric, **summary}
            if group_by:
                row[group_by] = group_value
            output.append(row)
    return pd.DataFrame(output, columns=columns)


def voyage_identity_key(vessel: Any, voyage: Any, block_id: Any) -> str:
    return "||".join(normalize_text(value) for value in [vessel, voyage, block_id])


def safe_divide(numerator: Any, denominator: Any) -> float | None:
    numerator_value = pd.to_numeric(pd.Series([numerator]), errors="coerce").iloc[0]
    denominator_value = pd.to_numeric(pd.Series([denominator]), errors="coerce").iloc[0]
    if pd.isna(numerator_value) or pd.isna(denominator_value) or float(denominator_value) == 0:
        return None
    return float(numerator_value) / float(denominator_value)


def _metric_row(rows: pd.DataFrame) -> dict[str, Any]:
    metrics = calculate_weekly_metrics(rows)
    classified_containers = metrics.loaded_containers + metrics.empty_containers
    classified_teu = metrics.loaded_teu + metrics.empty_teu
    total_known_equipment = metrics.total_20ft + metrics.total_40ft
    loaded_known_equipment = metrics.loaded_20ft + metrics.loaded_40ft
    empty_known_equipment = metrics.empty_20ft + metrics.empty_40ft
    return {
        "Active rows": metrics.active_rows,
        "Cancelled rows": metrics.cancelled_rows,
        "Cancellation Rate": safe_divide(metrics.cancelled_rows, metrics.valid_operational_rows),
        "Total Containers": metrics.total_containers,
        "Loaded Containers": metrics.loaded_containers,
        "Empty Containers": metrics.empty_containers,
        "Unclassified Containers": metrics.unclassified_containers,
        "Loaded %": safe_divide(metrics.loaded_containers, metrics.total_containers),
        "Empty %": safe_divide(metrics.empty_containers, metrics.total_containers),
        "Classified Containers": classified_containers,
        "Empty Container Ratio": safe_divide(metrics.empty_containers, classified_containers),
        "Total 20ft": metrics.total_20ft,
        "Loaded 20ft": metrics.loaded_20ft,
        "Empty 20ft": metrics.empty_20ft,
        "Total 40ft": metrics.total_40ft,
        "Loaded 40ft": metrics.loaded_40ft,
        "Empty 40ft": metrics.empty_40ft,
        "Total TEU": metrics.total_teu,
        "Loaded TEU": metrics.loaded_teu,
        "Empty TEU": metrics.empty_teu,
        "Unclassified TEU": metrics.unclassified_teu,
        "Classified TEU": classified_teu,
        "Empty TEU Ratio": safe_divide(metrics.empty_teu, classified_teu),
        "Total GWT": metrics.total_gwt,
        "Loaded GWT": metrics.loaded_gwt,
        "Empty GWT": metrics.empty_gwt,
        "Unclassified GWT": metrics.unclassified_gwt,
        "Loaded GWT / Loaded TEU": safe_divide(metrics.loaded_gwt, metrics.loaded_teu),
        "Loaded GWT / Loaded Container": safe_divide(metrics.loaded_gwt, metrics.loaded_containers),
        "Total GWT / Total TEU": safe_divide(metrics.total_gwt, metrics.total_teu),
        "Total 20ft Share": safe_divide(metrics.total_20ft, total_known_equipment),
        "Total 40ft Share": safe_divide(metrics.total_40ft, total_known_equipment),
        "Loaded 20ft Share": safe_divide(metrics.loaded_20ft, loaded_known_equipment),
        "Loaded 40ft Share": safe_divide(metrics.loaded_40ft, loaded_known_equipment),
        "Empty 20ft Share": safe_divide(metrics.empty_20ft, empty_known_equipment),
        "Empty 40ft Share": safe_divide(metrics.empty_40ft, empty_known_equipment),
    }


def _first_meaningful(df: pd.DataFrame, column: str) -> Any:
    if column not in df.columns:
        return None
    for value in df[column].tolist():
        if is_meaningful_value(value):
            return value
    return None


def _voyage_count(df: pd.DataFrame) -> int:
    if not all(column in df.columns for column in VOYAGE_IDENTITY_COLUMNS):
        return 0
    keys = {
        voyage_identity_key(row.get("Vessel"), row.get("Voyage"), row.get("BlockID"))
        for _, row in df.iterrows()
        if all(is_meaningful_value(row.get(column)) for column in VOYAGE_IDENTITY_COLUMNS)
    }
    return len(keys)


def _complete_voyage_identity_mask(df: pd.DataFrame) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    for column in VOYAGE_IDENTITY_COLUMNS:
        mask &= df[column].map(is_meaningful_value)
    return mask
