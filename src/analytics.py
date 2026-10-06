from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from .date_utils import days_between, is_meaningful_value, normalize_text, parse_schedule_date
from .history_processing import history_with_current_context, is_legacy_unavailable
from .operational_calculations import cancelled_mask, operational_mask
from .filters import (
    REVISION_TRACKED_FIELDS,
    SCHEDULE_FIELDS,
    filter_history,
    filter_weekly,
    normalize_field_name,
)
from .models import (
    FieldReconstruction,
    MetricsHistory,
    MetricsWeekly,
    ScheduleMovement,
    VesselSummary,
    VoyageSummary,
)
from .schema import EXPANDED_HISTORY_FIELDS


TIMELINE_COLUMNS = [
    "Timestamp",
    "User",
    "BlockID",
    "RowID",
    "Vessel",
    "Voyage",
    "Booking number",
    "Field",
    "OldValue",
    "NewValue",
]


def calculate_weekly_metrics(df: pd.DataFrame) -> MetricsWeekly:
    if df.empty or "_is_operational" not in df.columns:
        return MetricsWeekly(0, 0, 0, 0.0, 0.0, 0.0)

    operational = df[operational_mask(df)].copy()
    cancelled = cancelled_mask(operational)
    active = operational[~cancelled].copy()
    return MetricsWeekly(
        valid_operational_rows=int(len(operational)),
        cancelled_rows=int(cancelled.sum()),
        unique_block_count=int(operational["BlockID"].dropna().nunique()) if "BlockID" in operational.columns else 0,
        total_summary=_sum_column(active, "Summary"),
        total_teu=_sum_column(active, "TEU"),
        total_ts=_sum_column(active, "TS"),
        active_rows=int(len(active)),
        loaded_containers=_sum_column(active, "Loaded Containers"),
        empty_containers=_sum_column(active, "Empty Containers"),
        unclassified_containers=_sum_column(active, "Unclassified Containers"),
        total_containers=_sum_column(active, "Total Containers"),
        loaded_percent=_safe_ratio(_sum_column(active, "Loaded Containers"), _sum_column(active, "Total Containers")),
        empty_percent=_safe_ratio(_sum_column(active, "Empty Containers"), _sum_column(active, "Total Containers")),
        loaded_20ft=_sum_column(active, "Loaded 20ft"),
        empty_20ft=_sum_column(active, "Empty 20ft"),
        total_20ft=_sum_column(active, "Total 20ft"),
        loaded_40ft=_sum_column(active, "Loaded 40ft"),
        empty_40ft=_sum_column(active, "Empty 40ft"),
        total_40ft=_sum_column(active, "Total 40ft"),
        loaded_teu=_sum_column(active, "Loaded TEU"),
        empty_teu=_sum_column(active, "Empty TEU"),
        unclassified_teu=_sum_column(active, "Unclassified TEU"),
        loaded_gwt=_sum_column(active, "Loaded GWT"),
        empty_gwt=_sum_column(active, "Empty GWT"),
        unclassified_gwt=_sum_column(active, "Unclassified GWT"),
        total_gwt=_sum_column(active, "Total GWT"),
    )


def calculate_history_metrics(df: pd.DataFrame) -> MetricsHistory:
    if df.empty or "Field" not in df.columns:
        return MetricsHistory(0, 0, 0, 0, 0, 0, 0)

    records = df[df.notna().any(axis=1)]
    fields = records["Field"].map(normalize_field_name)
    field_changes = {field: _count_field(fields, field) for field in EXPANDED_HISTORY_FIELDS}
    return MetricsHistory(
        history_records=int(len(records)),
        eta_changes=_count_field(fields, "ETA"),
        etd_changes=_count_field(fields, "ETD"),
        cut_off_changes=_count_field(fields, "Cut-Off"),
        vessel_changes=_count_field(fields, "Vessel"),
        voyage_changes=_count_field(fields, "Voyage"),
        eta_ts_changes=_count_field(fields, "ETA T/S"),
        field_changes=field_changes,
    )


def get_chronological_timeline(
    history_df: pd.DataFrame,
    *,
    row_id: Any | Iterable[Any] | None = None,
    voyage: Any | Iterable[Any] | None = None,
    vessel: Any | Iterable[Any] | None = None,
    block_id: Any | Iterable[Any] | None = None,
    booking_number: Any | Iterable[Any] | None = None,
    field: Any | Iterable[Any] | None = None,
) -> pd.DataFrame:
    """Return a LOG_HISTORY timeline sorted oldest-to-newest."""

    filtered = filter_history(
        history_df,
        row_id=row_id,
        voyage=voyage,
        vessel=vessel,
        block_id=block_id,
        booking_number=booking_number,
        field=field,
    )
    return _timeline_from_filtered_history(filtered)


def reconstruct_field_value(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    field_name: str,
    *,
    row_id: Any | Iterable[Any] | None = None,
    voyage: Any | Iterable[Any] | None = None,
    vessel: Any | Iterable[Any] | None = None,
    block_id: Any | Iterable[Any] | None = None,
    booking_number: Any | Iterable[Any] | None = None,
) -> FieldReconstruction:
    """Reconstruct original/current value for a tracked field.

    Original value is the earliest meaningful OldValue in history. Current value
    comes from matching WEEKLY rows where available; latest history NewValue is
    only an analytical fallback when no matching WEEKLY row is available.
    """

    canonical_field = normalize_field_name(field_name)
    identity = _identity_dict(
        row_id=row_id,
        voyage=voyage,
        vessel=vessel,
        block_id=block_id,
        booking_number=booking_number,
    )
    weekly_subset = _matching_weekly(weekly_df, identity)
    field_history = filter_history(history_df, field=canonical_field, **_history_filter_kwargs(identity))
    field_history = _sort_history(field_history)

    warnings: list[str] = []
    material_revision_count, _, material_warnings = _material_revision_stats(field_history, canonical_field)
    warnings.extend(material_warnings)

    current_raw, current_source, current_warnings = _current_value_from_weekly(weekly_subset, canonical_field)
    warnings.extend(current_warnings)
    latest_history_raw, latest_history_warnings = _history_value(field_history, canonical_field, "NewValue", newest=True)
    warnings.extend(latest_history_warnings)

    if current_source == "NONE" and latest_history_raw is not None:
        current_raw = latest_history_raw
        current_source = "HISTORY_FALLBACK"

    original_raw, original_warnings = _history_value(field_history, canonical_field, "OldValue", newest=False)
    warnings.extend(original_warnings)
    if original_raw is None:
        original_raw = current_raw if is_meaningful_value(current_raw) else latest_history_raw

    original_parsed = None
    current_parsed = None
    if canonical_field in SCHEDULE_FIELDS:
        original_result = parse_schedule_date(original_raw, field_name=canonical_field)
        current_result = parse_schedule_date(current_raw, field_name=canonical_field)
        original_parsed = original_result.parsed
        current_parsed = current_result.parsed
        warnings.extend(warning for warning in [original_result.warning, current_result.warning] if warning)

    return FieldReconstruction(
        field_name=canonical_field,
        identity=identity,
        original_raw=original_raw,
        current_raw=current_raw,
        latest_history_raw=latest_history_raw,
        current_source=current_source,
        history_event_count=int(len(field_history)),
        material_revision_count=material_revision_count,
        original_parsed=original_parsed,
        current_parsed=current_parsed,
        warnings=_dedupe_strings(warnings),
    )


def calculate_schedule_movement(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    field_name: str,
    *,
    row_id: Any | Iterable[Any] | None = None,
    voyage: Any | Iterable[Any] | None = None,
    vessel: Any | Iterable[Any] | None = None,
    block_id: Any | Iterable[Any] | None = None,
    booking_number: Any | Iterable[Any] | None = None,
) -> ScheduleMovement:
    canonical_field = normalize_field_name(field_name)
    if canonical_field not in SCHEDULE_FIELDS:
        raise ValueError(f"Schedule movement only supports {', '.join(SCHEDULE_FIELDS)}; got {field_name!r}.")

    reconstruction = reconstruct_field_value(
        weekly_df,
        history_df,
        canonical_field,
        row_id=row_id,
        voyage=voyage,
        vessel=vessel,
        block_id=block_id,
        booking_number=booking_number,
    )
    field_history = filter_history(history_df, field=canonical_field, **_history_filter_kwargs(reconstruction.identity))
    field_history = _sort_history(field_history)
    _, deltas, movement_warnings = _material_revision_stats(field_history, canonical_field)

    net_movement = days_between(reconstruction.original_parsed, reconstruction.current_parsed)
    if reconstruction.original_parsed is not None and reconstruction.current_parsed is not None:
        cumulative_movement = float(sum(abs(delta) for delta in deltas))
    else:
        cumulative_movement = None

    return ScheduleMovement(
        field_name=canonical_field,
        identity=reconstruction.identity,
        original_raw=reconstruction.original_raw,
        current_raw=reconstruction.current_raw,
        current_source=reconstruction.current_source,
        history_event_count=reconstruction.history_event_count,
        material_revision_count=reconstruction.material_revision_count,
        net_movement_days=net_movement,
        cumulative_movement_days=cumulative_movement,
        original_date=reconstruction.original_parsed,
        current_date=reconstruction.current_parsed,
        warnings=_dedupe_strings(reconstruction.warnings + movement_warnings),
    )


def calculate_eta_movement(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    *,
    row_id: Any | Iterable[Any] | None = None,
    voyage: Any | Iterable[Any] | None = None,
    vessel: Any | Iterable[Any] | None = None,
    block_id: Any | Iterable[Any] | None = None,
    booking_number: Any | Iterable[Any] | None = None,
) -> ScheduleMovement:
    return calculate_schedule_movement(
        weekly_df,
        history_df,
        "ETA",
        row_id=row_id,
        voyage=voyage,
        vessel=vessel,
        block_id=block_id,
        booking_number=booking_number,
    )


def calculate_revision_counts(
    history_df: pd.DataFrame,
    group_by: str,
    fields: Iterable[str] = REVISION_TRACKED_FIELDS,
) -> pd.DataFrame:
    """Calculate event and material revision counts per RowID, Voyage, or Vessel."""

    canonical_fields = [normalize_field_name(field) for field in fields]
    columns = [group_by, "total_history_events"]
    for field in canonical_fields:
        safe_name = _field_column_name(field)
        columns.extend([f"{safe_name}_events", f"{safe_name}_revisions"])

    if history_df.empty or group_by not in history_df.columns:
        return pd.DataFrame(columns=columns)

    records = history_df[history_df[group_by].map(is_meaningful_value)].copy()
    if records.empty:
        return pd.DataFrame(columns=columns)

    records["_group_key"] = records[group_by].map(normalize_text)
    rows: list[dict[str, Any]] = []
    for _, group in records.groupby("_group_key", sort=True):
        row: dict[str, Any] = {
            group_by: _first_meaningful(group[group_by]),
            "total_history_events": int(len(group)),
        }
        for field in canonical_fields:
            field_events = _events_for_field(group, field)
            material_count, _, _ = _material_revision_stats(field_events, field)
            safe_name = _field_column_name(field)
            row[f"{safe_name}_events"] = int(len(field_events))
            row[f"{safe_name}_revisions"] = int(material_count)
        rows.append(row)

    return pd.DataFrame(rows, columns=columns).sort_values(by=[group_by], kind="mergesort").reset_index(drop=True)


def revision_counts_by_row_id(history_df: pd.DataFrame) -> pd.DataFrame:
    return calculate_revision_counts(history_df, "RowID")


def revision_counts_by_voyage(history_df: pd.DataFrame) -> pd.DataFrame:
    return calculate_revision_counts(history_df, "Voyage")


def revision_counts_by_vessel(history_df: pd.DataFrame) -> pd.DataFrame:
    return calculate_revision_counts(history_df, "Vessel")


def get_voyage_summary(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    voyage: Any,
    *,
    vessel: Any | None = None,
    block_id: Any | None = None,
) -> VoyageSummary:
    history_df = history_with_current_context(history_df)
    weekly_subset = filter_weekly(weekly_df, voyage=voyage, vessel=vessel, block_id=block_id)
    history_subset = filter_history(history_df, voyage=voyage, vessel=vessel, block_id=block_id)
    candidate_groups = _candidate_groups(weekly_subset, history_subset, default_voyage=voyage)
    ambiguity_reason = _voyage_ambiguity_reason(candidate_groups, vessel=vessel, block_id=block_id)
    timeline = _timeline_from_filtered_history(history_subset)

    if ambiguity_reason:
        return VoyageSummary(
            vessel=str(vessel).strip() if vessel is not None else None,
            voyage=str(voyage).strip() if voyage is not None else None,
            block_ids=_unique_values_from_frames([weekly_subset, history_subset], "BlockID"),
            current_operational_row_count=0,
            cancelled_row_count=0,
            total_summary=0.0,
            total_teu=0.0,
            total_ts=0.0,
            original_eta=None,
            current_eta=None,
            net_eta_movement_days=None,
            cumulative_eta_movement_days=None,
            eta_revision_count=0,
            etd_revision_count=0,
            cut_off_revision_count=0,
            eta_ts_revision_count=0,
            total_history_events=int(len(history_subset)),
            affected_row_ids=_unique_values_from_frames([weekly_subset, history_subset], "RowID"),
            timeline=timeline,
            is_ambiguous=True,
            ambiguity_reason=ambiguity_reason,
            candidate_groups=candidate_groups,
        )

    active_rows = _active_weekly_rows(weekly_subset)
    cancelled_rows = _cancelled_weekly_rows(weekly_subset)
    eta_movement = calculate_eta_movement(weekly_subset, history_subset, voyage=voyage, vessel=vessel, block_id=block_id)

    return VoyageSummary(
        vessel=_single_or_none(_unique_values_from_frames([weekly_subset, history_subset], "Vessel")),
        voyage=str(voyage).strip() if voyage is not None else None,
        block_ids=_unique_values_from_frames([weekly_subset, history_subset], "BlockID"),
        current_operational_row_count=int(len(active_rows)),
        cancelled_row_count=int(len(cancelled_rows)),
        total_summary=_sum_column(active_rows, "Summary"),
        total_teu=_sum_column(active_rows, "TEU"),
        total_ts=_sum_column(active_rows, "TS"),
        original_eta=eta_movement.original_raw,
        current_eta=eta_movement.current_raw,
        net_eta_movement_days=eta_movement.net_movement_days,
        cumulative_eta_movement_days=eta_movement.cumulative_movement_days,
        eta_revision_count=eta_movement.material_revision_count,
        etd_revision_count=_material_revision_count_for_field(history_subset, "ETD"),
        cut_off_revision_count=_material_revision_count_for_field(history_subset, "Cut-Off"),
        eta_ts_revision_count=_material_revision_count_for_field(history_subset, "ETA T/S"),
        total_history_events=int(len(history_subset)),
        affected_row_ids=_unique_values_from_frames([weekly_subset, history_subset], "RowID"),
        timeline=timeline,
        warnings=eta_movement.warnings,
    )


def get_vessel_summary(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    vessel: Any,
) -> VesselSummary:
    history_df = history_with_current_context(history_df)
    weekly_subset = filter_weekly(weekly_df, vessel=vessel)
    history_subset = filter_history(history_df, vessel=vessel)
    active_rows = _active_weekly_rows(weekly_subset)
    cancelled_rows = _cancelled_weekly_rows(weekly_subset)

    return VesselSummary(
        vessel=str(vessel).strip() if vessel is not None else None,
        voyages=_unique_values_from_frames([weekly_subset, history_subset], "Voyage"),
        operational_rows=int(len(active_rows)),
        cancelled_rows=int(len(cancelled_rows)),
        total_summary=_sum_column(active_rows, "Summary"),
        total_teu=_sum_column(active_rows, "TEU"),
        total_ts=_sum_column(active_rows, "TS"),
        history_event_count=int(len(history_subset)),
        eta_revision_count=_material_revision_count_for_field(history_subset, "ETA"),
        etd_revision_count=_material_revision_count_for_field(history_subset, "ETD"),
        cut_off_revision_count=_material_revision_count_for_field(history_subset, "Cut-Off"),
        voyage_revision_count=_material_revision_count_for_field(history_subset, "Voyage"),
        affected_row_ids=_unique_values_from_frames([weekly_subset, history_subset], "RowID"),
        affected_block_ids=_unique_values_from_frames([weekly_subset, history_subset], "BlockID"),
    )


def rank_vessels_by_history_events(history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _rank_by_metric(calculate_revision_counts(history_df, "Vessel"), "Vessel", "total_history_events", limit=limit)


def rank_vessels_by_eta_revisions(history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _rank_by_metric(calculate_revision_counts(history_df, "Vessel"), "Vessel", "ETA_revisions", limit=limit)


def rank_voyages_by_history_events(history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _rank_by_metric(calculate_revision_counts(history_df, "Voyage"), "Voyage", "total_history_events", limit=limit)


def rank_voyages_by_eta_revisions(history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _rank_by_metric(calculate_revision_counts(history_df, "Voyage"), "Voyage", "ETA_revisions", limit=limit)


def _timeline_from_filtered_history(history_df: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in TIMELINE_COLUMNS if column in history_df.columns]
    if history_df.empty:
        return pd.DataFrame(columns=columns or TIMELINE_COLUMNS)
    timeline = history_df.copy()
    if "Timestamp" in timeline.columns:
        timeline["_timestamp_sort"] = pd.to_datetime(timeline["Timestamp"], errors="coerce")
        timeline = timeline.sort_values(by="_timestamp_sort", kind="mergesort", na_position="last")
        timeline = timeline.drop(columns=["_timestamp_sort"])
    return timeline[columns].reset_index(drop=True)


def _matching_weekly(weekly_df: pd.DataFrame, identity: dict[str, Any]) -> pd.DataFrame:
    return filter_weekly(
        weekly_df,
        row_id=identity.get("row_id"),
        voyage=identity.get("voyage"),
        vessel=identity.get("vessel"),
        block_id=identity.get("block_id"),
    )


def _history_filter_kwargs(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": identity.get("row_id"),
        "voyage": identity.get("voyage"),
        "vessel": identity.get("vessel"),
        "block_id": identity.get("block_id"),
        "booking_number": identity.get("booking_number"),
    }


def _identity_dict(
    *,
    row_id: Any | Iterable[Any] | None = None,
    voyage: Any | Iterable[Any] | None = None,
    vessel: Any | Iterable[Any] | None = None,
    block_id: Any | Iterable[Any] | None = None,
    booking_number: Any | Iterable[Any] | None = None,
) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "voyage": voyage,
        "vessel": vessel,
        "block_id": block_id,
        "booking_number": booking_number,
    }


def _current_value_from_weekly(weekly_df: pd.DataFrame, field_name: str) -> tuple[Any | None, str, list[str]]:
    if weekly_df.empty or field_name not in weekly_df.columns:
        return None, "NONE", []

    values = [value for value in weekly_df[field_name].tolist() if is_meaningful_value(value)]
    if not values:
        return None, "WEEKLY", []

    warnings: list[str] = []
    unique_by_key: dict[Any, Any] = {}
    for value in values:
        key, key_warning = _comparison_key(field_name, value)
        if key_warning:
            warnings.append(key_warning)
        unique_by_key.setdefault(key, value)

    if len(unique_by_key) > 1:
        return (
            None,
            "AMBIGUOUS",
            _dedupe_strings(warnings + [f"Multiple current WEEKLY values found for {field_name}."]),
        )
    return next(iter(unique_by_key.values())), "WEEKLY", _dedupe_strings(warnings)


def _history_value(
    history_df: pd.DataFrame,
    field_name: str,
    value_column: str,
    *,
    newest: bool,
) -> tuple[Any | None, list[str]]:
    if history_df.empty or value_column not in history_df.columns:
        return None, []

    rows = history_df.iloc[::-1] if newest else history_df
    warnings: list[str] = []
    for _, row in rows.iterrows():
        value = row.get(value_column)
        if is_legacy_unavailable(value):
            warnings.append(f"Legacy [bulk edit] value is unavailable for {field_name}.")
            continue
        if not is_meaningful_value(value):
            continue
        if field_name in SCHEDULE_FIELDS:
            parsed = parse_schedule_date(value, field_name=field_name)
            if parsed.warning:
                warnings.append(parsed.warning)
                continue
        return value, _dedupe_strings(warnings)
    return None, _dedupe_strings(warnings)


def _material_revision_count_for_field(history_df: pd.DataFrame, field_name: str) -> int:
    field_events = _events_for_field(history_df, field_name)
    material_count, _, _ = _material_revision_stats(field_events, normalize_field_name(field_name))
    return material_count


def _events_for_field(history_df: pd.DataFrame, field_name: str) -> pd.DataFrame:
    if history_df.empty or "Field" not in history_df.columns:
        return history_df.iloc[0:0].copy()
    canonical_field = normalize_field_name(field_name)
    return history_df[history_df["Field"].map(normalize_field_name) == canonical_field].copy()


def _material_revision_stats(history_df: pd.DataFrame, field_name: str) -> tuple[int, list[float], list[str]]:
    if history_df.empty:
        return 0, [], []

    canonical_field = normalize_field_name(field_name)
    count = 0
    deltas: list[float] = []
    warnings: list[str] = []
    for _, row in _sort_history(history_df).iterrows():
        old_value = row.get("OldValue")
        new_value = row.get("NewValue")
        material, delta, event_warnings = _material_revision_event(canonical_field, old_value, new_value)
        warnings.extend(event_warnings)
        if material:
            count += 1
            if delta is not None:
                deltas.append(delta)
    return count, deltas, _dedupe_strings(warnings)


def _material_revision_event(field_name: str, old_value: Any, new_value: Any) -> tuple[bool, float | None, list[str]]:
    if is_legacy_unavailable(old_value) or is_legacy_unavailable(new_value):
        return False, None, [f"Legacy [bulk edit] value is unavailable for {field_name}."]
    if not is_meaningful_value(old_value) or not is_meaningful_value(new_value):
        return False, None, []

    if field_name in SCHEDULE_FIELDS:
        old_parsed = parse_schedule_date(old_value, field_name=field_name)
        new_parsed = parse_schedule_date(new_value, field_name=field_name)
        warnings = [warning for warning in [old_parsed.warning, new_parsed.warning] if warning]
        if warnings or old_parsed.parsed is None or new_parsed.parsed is None:
            return False, None, warnings
        delta = days_between(old_parsed.parsed, new_parsed.parsed)
        if delta is None or delta == 0:
            return False, delta, []
        return True, delta, []

    old_normalized = normalize_text(old_value)
    new_normalized = normalize_text(new_value)
    return old_normalized != new_normalized, None, []


def _comparison_key(field_name: str, value: Any) -> tuple[Any, str | None]:
    if field_name in SCHEDULE_FIELDS:
        parsed = parse_schedule_date(value, field_name=field_name)
        if parsed.parsed is not None:
            return ("date", parsed.parsed.isoformat()), parsed.warning
        return ("raw", normalize_text(value)), parsed.warning
    return ("text", normalize_text(value)), None


def _sort_history(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty:
        return history_df.copy()
    sorted_df = history_df.copy()
    if "Timestamp" in sorted_df.columns:
        sorted_df["_timestamp_sort"] = pd.to_datetime(sorted_df["Timestamp"], errors="coerce")
        sorted_df = sorted_df.sort_values(by="_timestamp_sort", kind="mergesort", na_position="last")
        sorted_df = sorted_df.drop(columns=["_timestamp_sort"])
    return sorted_df.reset_index(drop=True)


def _active_weekly_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    operational = _operational_mask(df)
    active = operational & ~_is_cancelled_series(df)
    return df[active].copy()


def _cancelled_weekly_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    operational = _operational_mask(df)
    return df[operational & _is_cancelled_series(df)].copy()


def _operational_mask(df: pd.DataFrame) -> pd.Series:
    if "_is_operational" in df.columns:
        return df["_is_operational"].fillna(False).astype(bool)
    return operational_mask(df)


def _candidate_groups(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    *,
    default_voyage: Any | None = None,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    _add_candidate_rows(groups, weekly_df, source="weekly", default_voyage=default_voyage)
    _add_candidate_rows(groups, history_df, source="history", default_voyage=default_voyage)
    return sorted(groups.values(), key=lambda item: (normalize_text(item.get("Vessel")), normalize_text(item.get("BlockID"))))


def _add_candidate_rows(
    groups: dict[tuple[str, str], dict[str, Any]],
    df: pd.DataFrame,
    *,
    source: str,
    default_voyage: Any | None,
) -> None:
    if df.empty:
        return
    for _, row in df.iterrows():
        vessel = row.get("Vessel") if "Vessel" in df.columns else None
        block_id = row.get("BlockID") if "BlockID" in df.columns else None
        voyage = row.get("Voyage") if "Voyage" in df.columns else default_voyage
        key = (normalize_text(vessel), normalize_text(block_id))
        groups.setdefault(
            key,
            {
                "Vessel": vessel if is_meaningful_value(vessel) else None,
                "Voyage": voyage if is_meaningful_value(voyage) else default_voyage,
                "BlockID": block_id if is_meaningful_value(block_id) else None,
                "weekly_rows": 0,
                "history_events": 0,
            },
        )
        if source == "weekly":
            groups[key]["weekly_rows"] += 1
        else:
            groups[key]["history_events"] += 1


def _voyage_ambiguity_reason(
    candidate_groups: list[dict[str, Any]],
    *,
    vessel: Any | None,
    block_id: Any | None,
) -> str | None:
    if len(candidate_groups) <= 1:
        return None

    vessels = _unique_meaningful_values([candidate.get("Vessel") for candidate in candidate_groups])
    block_ids = _unique_meaningful_values([candidate.get("BlockID") for candidate in candidate_groups])

    if vessel is None and len(vessels) > 1:
        return f"Voyage matches multiple vessels: {', '.join(vessels)}. Provide Vessel to disambiguate."
    if block_id is None and len(block_ids) > 1:
        return f"Voyage matches multiple BlockIDs: {', '.join(block_ids)}. Provide BlockID to disambiguate."
    return None


def _unique_values_from_frames(frames: list[pd.DataFrame], column: str) -> list[str]:
    values: list[Any] = []
    for frame in frames:
        if column in frame.columns:
            values.extend(frame[column].tolist())
    return _unique_meaningful_values(values)


def _unique_meaningful_values(values: Iterable[Any]) -> list[str]:
    by_key: dict[str, str] = {}
    for value in values:
        if is_meaningful_value(value):
            by_key.setdefault(normalize_text(value), str(value).strip())
    return sorted(by_key.values(), key=lambda item: normalize_text(item))


def _single_or_none(values: list[str]) -> str | None:
    return values[0] if len(values) == 1 else None


def _first_meaningful(values: Iterable[Any]) -> Any | None:
    for value in values:
        if is_meaningful_value(value):
            return value
    return None


def _rank_by_metric(df: pd.DataFrame, label_column: str, metric_column: str, *, limit: int | None) -> pd.DataFrame:
    columns = ["rank", label_column, metric_column]
    if df.empty or label_column not in df.columns or metric_column not in df.columns:
        return pd.DataFrame(columns=columns)

    ranked = df[[label_column, metric_column]].copy()
    ranked[metric_column] = pd.to_numeric(ranked[metric_column], errors="coerce").fillna(0).astype(int)
    ranked = ranked.sort_values(by=[metric_column, label_column], ascending=[False, True], kind="mergesort")
    ranked["rank"] = ranked[metric_column].rank(method="dense", ascending=False).astype(int)
    ranked = ranked[columns].reset_index(drop=True)
    if limit is not None:
        ranked = ranked.head(limit).copy()
    return ranked


def _field_column_name(field_name: str) -> str:
    return field_name.replace("-", "_").replace("/", "_").replace(" ", "_")


def _sum_column(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _count_field(fields: pd.Series, value: str) -> int:
    return int((fields == normalize_field_name(value)).sum())


def _is_cancelled_series(df: pd.DataFrame) -> pd.Series:
    return cancelled_mask(df)


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped
