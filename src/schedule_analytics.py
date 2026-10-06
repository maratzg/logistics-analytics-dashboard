from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from .analytical_filters import FilterContext, apply_current_filters, apply_history_filters, eta_period_columns
from .analytics import calculate_eta_movement
from .date_utils import is_meaningful_value, normalize_text, parse_schedule_date
from .history_processing import deduplicate_voyage_events, history_with_current_context
from .operational_analytics import VOYAGE_IDENTITY_COLUMNS, voyage_identity_key, voyage_load_profiles


SCHEDULE_RELIABILITY_COLUMNS = [
    "IdentityKey",
    "Vessel",
    "Voyage",
    "BlockID",
    "Week",
    "SVC",
    "POL",
    "POD",
    "ETA Month",
    "ETA Year",
    "Original ETA",
    "Current ETA",
    "Net ETA Movement",
    "Cumulative ETA Movement",
    "ETA Revision Count",
    "Largest Single ETA Revision",
    "Largest Single ETA Revision Absolute",
    "First ETA Revision Timestamp",
    "Last ETA Revision Timestamp",
    "Week Change Count",
]

WEEK_ROLLOVER_COLUMNS = [
    "IdentityKey",
    "Vessel",
    "Voyage",
    "BlockID",
    "Week",
    "SVC",
    "ETA Month",
    "ETA Year",
    "Original Week",
    "Current Week",
    "Week Change Count",
    "Net Week Movement",
    "First Week Change Timestamp",
    "Last Week Change Timestamp",
    "Unavailable Week Events",
]


def material_schedule_events(history_df: pd.DataFrame, field_name: str = "ETA") -> pd.DataFrame:
    events = deduplicate_voyage_events(history_with_current_context(history_df))
    if events.empty or "Field" not in events.columns:
        return pd.DataFrame(columns=list(events.columns) + ["Material Revision", "Movement Days", "Revision Classification"])
    events = events[events["Field"].map(normalize_text) == normalize_text(field_name)].copy()
    material: list[bool] = []
    movements: list[float | None] = []
    classifications: list[str] = []
    for _, row in events.iterrows():
        old_value = row.get("OldValue")
        new_value = row.get("NewValue")
        if bool(row.get("_legacy_bulk_edit", False)):
            material.append(False)
            movements.append(None)
            classifications.append("Legacy old/new value unavailable")
            continue
        if not is_meaningful_value(old_value) and is_meaningful_value(new_value):
            material.append(False)
            movements.append(None)
            classifications.append("Initial population")
            continue
        if is_meaningful_value(old_value) and not is_meaningful_value(new_value):
            material.append(False)
            movements.append(None)
            classifications.append("Value cleared")
            continue
        old_date = parse_schedule_date(old_value, field_name=field_name).parsed
        new_date = parse_schedule_date(new_value, field_name=field_name).parsed
        if old_date is None or new_date is None:
            material.append(False)
            movements.append(None)
            classifications.append("Invalid or unavailable date")
            continue
        delta = float((new_date - old_date).days)
        material.append(delta != 0)
        movements.append(delta if delta != 0 else 0.0)
        classifications.append("Material revision" if delta != 0 else "No material change")
    events["Material Revision"] = material
    events["Movement Days"] = movements
    events["Revision Classification"] = classifications
    return events.reset_index(drop=True)


def schedule_reliability_by_voyage(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    rollover_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    weekly = eta_period_columns(apply_current_filters(weekly_df, context))
    history = history_with_current_context(apply_history_filters(history_df, context, current_df=weekly_df))
    history = deduplicate_voyage_events(history)
    profiles = voyage_load_profiles(weekly, None)
    identities = _identity_records(profiles, history)
    if not identities:
        return pd.DataFrame(columns=SCHEDULE_RELIABILITY_COLUMNS)

    rollover = rollover_df if rollover_df is not None else week_rollover_by_voyage(weekly, history, None)
    rollover_by_key = rollover.set_index("IdentityKey") if not rollover.empty else pd.DataFrame()
    output: list[dict[str, Any]] = []
    for identity in identities:
        current = _match_identity(weekly, identity)
        events = _match_identity(history, identity)
        eta_events = material_schedule_events(events, "ETA")
        material_eta = eta_events[eta_events["Material Revision"].fillna(False).astype(bool)].copy() if not eta_events.empty else eta_events
        movement = calculate_eta_movement(current, events)
        largest_signed, largest_absolute = _largest_signed_movement(material_eta)
        timestamps = pd.to_datetime(material_eta.get("Timestamp", pd.Series(dtype=object)), errors="coerce").dropna()
        metadata = _profile_metadata(current, profiles, identity)
        identity_key = voyage_identity_key(identity["Vessel"], identity["Voyage"], identity["BlockID"])
        week_change_count = 0
        if not rollover.empty and identity_key in rollover_by_key.index:
            week_change_count = int(rollover_by_key.at[identity_key, "Week Change Count"])
        output.append(
            {
                "IdentityKey": identity_key,
                **identity,
                **metadata,
                "Original ETA": movement.original_date,
                "Current ETA": movement.current_date,
                "Net ETA Movement": movement.net_movement_days,
                "Cumulative ETA Movement": movement.cumulative_movement_days,
                "ETA Revision Count": movement.material_revision_count,
                "Largest Single ETA Revision": largest_signed,
                "Largest Single ETA Revision Absolute": largest_absolute,
                "First ETA Revision Timestamp": timestamps.min() if not timestamps.empty else pd.NaT,
                "Last ETA Revision Timestamp": timestamps.max() if not timestamps.empty else pd.NaT,
                "Week Change Count": week_change_count,
            }
        )
    return pd.DataFrame(output, columns=SCHEDULE_RELIABILITY_COLUMNS).sort_values("IdentityKey", kind="mergesort").reset_index(drop=True)


def week_rollover_by_voyage(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
) -> pd.DataFrame:
    weekly = eta_period_columns(apply_current_filters(weekly_df, context))
    history = deduplicate_voyage_events(
        history_with_current_context(apply_history_filters(history_df, context, current_df=weekly_df))
    )
    profiles = voyage_load_profiles(weekly, None)
    identities = _identity_records(profiles, history)
    output: list[dict[str, Any]] = []
    for identity in identities:
        current = _match_identity(weekly, identity)
        events = _match_identity(history, identity)
        week_events = events[events.get("Field", pd.Series(index=events.index, dtype=object)).map(normalize_text) == "week"].copy()
        week_events["_timestamp"] = pd.to_datetime(week_events.get("Timestamp"), errors="coerce")
        week_events = week_events.sort_values("_timestamp", kind="mergesort")

        current_week = _single_numeric_week(current.get("Week", pd.Series(dtype=object)))
        original_week = None
        fallback_initial_week = None
        changes: list[tuple[pd.Timestamp, int]] = []
        unavailable = 0
        for _, event in week_events.iterrows():
            old_raw = event.get("OldValue")
            new_raw = event.get("NewValue")
            old_week = _parse_week(event.get("OldValue"))
            new_week = _parse_week(event.get("NewValue"))
            if original_week is None and old_week is not None:
                original_week = old_week
            if fallback_initial_week is None and new_week is not None:
                fallback_initial_week = new_week
            if bool(event.get("_legacy_bulk_edit", False)):
                unavailable += 1
                continue
            if not is_meaningful_value(old_raw) and new_week is not None:
                continue
            if old_week is None or new_week is None:
                unavailable += 1
                continue
            if old_week != new_week:
                changes.append((event.get("_timestamp"), new_week - old_week))
        if original_week is None:
            original_week = fallback_initial_week if fallback_initial_week is not None else current_week
        if current_week is None and changes:
            current_week = _parse_week(week_events.iloc[-1].get("NewValue"))
        net = float(current_week - original_week) if current_week is not None and original_week is not None else None
        timestamps = pd.to_datetime(pd.Series([timestamp for timestamp, _ in changes], dtype=object), errors="coerce").dropna()
        metadata = _profile_metadata(current, profiles, identity)
        output.append(
            {
                "IdentityKey": voyage_identity_key(identity["Vessel"], identity["Voyage"], identity["BlockID"]),
                **identity,
                **metadata,
                "Original Week": original_week,
                "Current Week": current_week,
                "Week Change Count": len(changes),
                "Net Week Movement": net,
                "First Week Change Timestamp": timestamps.min() if not timestamps.empty else pd.NaT,
                "Last Week Change Timestamp": timestamps.max() if not timestamps.empty else pd.NaT,
                "Unavailable Week Events": unavailable,
            }
        )
    if not output:
        return pd.DataFrame(columns=WEEK_ROLLOVER_COLUMNS)
    return pd.DataFrame(output, columns=WEEK_ROLLOVER_COLUMNS).sort_values("IdentityKey", kind="mergesort").reset_index(drop=True)


def aggregate_schedule_reliability(
    reliability_df: pd.DataFrame,
    by: str | Iterable[str],
) -> pd.DataFrame:
    group_columns = [by] if isinstance(by, str) else list(by)
    columns = group_columns + [
        "Voyage Count",
        "% Voyages Delayed",
        "Median Net ETA Movement",
        "Mean Net ETA Movement",
        "Median ETA Revision Count",
        "Median Cumulative ETA Movement",
        "Largest Observed ETA Revision",
    ]
    if reliability_df.empty or not all(column in reliability_df.columns for column in group_columns):
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for key, group in reliability_df.groupby(group_columns, dropna=False, sort=True):
        values = key if isinstance(key, tuple) else (key,)
        net = pd.to_numeric(group["Net ETA Movement"], errors="coerce").dropna()
        revisions = pd.to_numeric(group["ETA Revision Count"], errors="coerce").dropna()
        cumulative = pd.to_numeric(group["Cumulative ETA Movement"], errors="coerce").dropna()
        largest = pd.to_numeric(group["Largest Single ETA Revision Absolute"], errors="coerce").dropna()
        row = dict(zip(group_columns, values, strict=False))
        row.update(
            {
                "Voyage Count": int(len(group)),
                "% Voyages Delayed": float((net > 0).sum() / len(net)) if len(net) else None,
                "Median Net ETA Movement": float(net.median()) if len(net) else None,
                "Mean Net ETA Movement": float(net.mean()) if len(net) else None,
                "Median ETA Revision Count": float(revisions.median()) if len(revisions) else None,
                "Median Cumulative ETA Movement": float(cumulative.median()) if len(cumulative) else None,
                "Largest Observed ETA Revision": float(largest.max()) if len(largest) else None,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def aggregate_week_rollover(rollover_df: pd.DataFrame, by: str | Iterable[str]) -> pd.DataFrame:
    group_columns = [by] if isinstance(by, str) else list(by)
    columns = group_columns + [
        "Voyage Count",
        "% Voyages Moved Week",
        "% Moved One Week",
        "% Moved Multiple Weeks",
        "Median Week Change Count",
        "Unavailable Week Events",
    ]
    if rollover_df.empty or not all(column in rollover_df.columns for column in group_columns):
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for key, group in rollover_df.groupby(group_columns, dropna=False, sort=True):
        values = key if isinstance(key, tuple) else (key,)
        count = pd.to_numeric(group["Week Change Count"], errors="coerce").fillna(0)
        net = pd.to_numeric(group["Net Week Movement"], errors="coerce")
        denominator = int(len(group))
        row = dict(zip(group_columns, values, strict=False))
        row.update(
            {
                "Voyage Count": denominator,
                "% Voyages Moved Week": float((count > 0).sum() / denominator) if denominator else None,
                "% Moved One Week": float((net.abs() == 1).sum() / denominator) if denominator else None,
                "% Moved Multiple Weeks": float((net.abs() > 1).sum() / denominator) if denominator else None,
                "Median Week Change Count": float(count.median()) if denominator else None,
                "Unavailable Week Events": int(pd.to_numeric(group["Unavailable Week Events"], errors="coerce").fillna(0).sum()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def _identity_records(profiles: pd.DataFrame, history: pd.DataFrame) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for frame in [profiles, history]:
        if frame.empty or not all(column in frame.columns for column in VOYAGE_IDENTITY_COLUMNS):
            continue
        for _, row in frame.iterrows():
            identity = {column: row.get(column) for column in VOYAGE_IDENTITY_COLUMNS}
            # Incomplete identities are deliberately not grouped. Combining
            # them would risk merging unrelated voyages that merely share one
            # visible label. The quality report identifies these records.
            if not all(is_meaningful_value(identity[column]) for column in VOYAGE_IDENTITY_COLUMNS):
                continue
            key = voyage_identity_key(identity["Vessel"], identity["Voyage"], identity["BlockID"])
            records.setdefault(key, identity)
    return [records[key] for key in sorted(records)]


def _match_identity(df: pd.DataFrame, identity: dict[str, Any]) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = pd.Series(True, index=df.index)
    for column in VOYAGE_IDENTITY_COLUMNS:
        if column not in df.columns:
            return df.iloc[0:0].copy()
        mask &= df[column].map(normalize_text).eq(normalize_text(identity[column]))
    return df[mask].copy()


def _profile_metadata(current: pd.DataFrame, profiles: pd.DataFrame, identity: dict[str, Any]) -> dict[str, Any]:
    profile = _match_identity(profiles, identity)
    source = profile if not profile.empty else current
    return {
        "Week": _first(source, "Week"),
        "SVC": _first(source, "SVC"),
        "POL": _first(source, "POL"),
        "POD": _first(source, "POD"),
        "ETA Month": _first(source, "ETA Month") or _eta_month(_first(source, "ETA")),
        "ETA Year": _first(source, "ETA Year") or _eta_year(_first(source, "ETA")),
    }


def _first(df: pd.DataFrame, column: str) -> Any:
    if column not in df.columns:
        return None
    for value in df[column].tolist():
        if is_meaningful_value(value):
            return value
    return None


def _eta_month(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%Y-%m") if not pd.isna(parsed) else "Unknown"


def _eta_year(value: Any) -> int | str:
    parsed = pd.to_datetime(value, errors="coerce")
    return int(parsed.year) if not pd.isna(parsed) else "Unknown"


def _largest_signed_movement(events: pd.DataFrame) -> tuple[float | None, float | None]:
    if events.empty or "Movement Days" not in events.columns:
        return None, None
    movements = pd.to_numeric(events["Movement Days"], errors="coerce").dropna()
    if movements.empty:
        return None, None
    position = movements.abs().idxmax()
    value = float(movements.loc[position])
    return value, abs(value)


def _parse_week(value: Any) -> int | None:
    if not is_meaningful_value(value):
        return None
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric) or float(numeric) % 1 != 0:
        return None
    week = int(numeric)
    return week if 1 <= week <= 53 else None


def _single_numeric_week(values: pd.Series) -> int | None:
    parsed = [_parse_week(value) for value in values.tolist()]
    meaningful = [value for value in parsed if value is not None]
    return meaningful[0] if meaningful else None
