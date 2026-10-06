from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from typing import Any, Literal

import pandas as pd

from src.analytical_filters import FilterContext, apply_current_filters, apply_history_filters
from src.analytics import calculate_weekly_metrics
from src.anomaly_detection import detect_explainable_anomalies
from src.date_utils import is_meaningful_value, normalize_text, parse_schedule_date
from src.history_processing import (
    IDENTITY_RESOLUTION_COLUMN,
    IDENTITY_RESOLVED,
    deduplicate_voyage_events,
    effective_history_identity_key,
    is_legacy_unavailable,
    match_history_to_current_identity,
)
from src.models import MetricsWeekly
from src.operational_analytics import aggregate_current, voyage_identity_key, voyage_load_profiles
from src.schedule_analytics import schedule_reliability_by_voyage, week_rollover_by_voyage

from .presentation import (
    MISSING_TEXT,
    UNAVAILABLE_TEXT,
    format_date,
    format_history_value,
    format_timestamp,
    format_voyage_identity,
    history_change_message,
)


HistoryMode = Literal["grouped", "raw"]
HISTORY_FIELDS = {
    "Vessel",
    "Voyage",
    "ETA",
    "ETD",
    "Cut-Off",
    "ETA T/S",
    "Week",
    "CNTR AMT",
    "SIZE",
    "TYPE",
    "GWT",
    "POL",
    "POD",
    "RowStatus",
    "CancelReason",
    "LoadStatus",
    "Booking status",
}
BOOKING_COLUMNS = [
    "Booking number",
    "CUSTOMER",
    "CNTR AMT",
    "SIZE",
    "TYPE",
    "LoadStatus",
    "GWT",
    "POD",
    "Booking status",
    "RowStatus",
    "CancelReason",
    "RowID",
]
HISTORY_DISPLAY_COLUMNS = [
    "Timestamp",
    "Vessel",
    "Voyage",
    "Week",
    "Booking number",
    "Field",
    "Old Value",
    "New Value",
    "User",
    "Raw Events",
]


@dataclass(frozen=True, slots=True)
class RecentChange:
    timestamp: str
    vessel: str
    voyage: str
    field: str
    message: str
    identity_key: str | None
    raw_event_count: int


@dataclass(frozen=True, slots=True)
class AttentionItem:
    severity: str
    title: str
    reason: str
    identity_key: str | None = None


@dataclass(frozen=True, slots=True)
class OperationalDashboardModel:
    metrics: MetricsWeekly
    has_rows: bool
    empty_message: str | None
    voyage_composition: pd.DataFrame
    equipment_mix: pd.DataFrame
    teu_by_vessel: pd.DataFrame
    chart_limit_note: str | None
    recent_changes: list[RecentChange]
    attention_items: list[AttentionItem]
    quality_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class VoyageBrowserModel:
    rows: pd.DataFrame
    voyage_count: int
    empty_message: str | None = None


@dataclass(frozen=True, slots=True)
class VoyageDetailModel:
    identity_key: str
    available: bool
    empty_message: str | None
    vessel: str = MISSING_TEXT
    voyage: str = MISSING_TEXT
    block_id: str = MISSING_TEXT
    week: str = MISSING_TEXT
    svc: str = MISSING_TEXT
    route: str = MISSING_TEXT
    eta: str = MISSING_TEXT
    etd: str = MISSING_TEXT
    cut_off: str = MISSING_TEXT
    metrics: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    bookings: pd.DataFrame = field(default_factory=pd.DataFrame)
    grouped_timeline: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_timeline: pd.DataFrame = field(default_factory=pd.DataFrame)
    quality_issues: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass(frozen=True, slots=True)
class OperationalHistoryModel:
    rows: pd.DataFrame
    mode: HistoryMode
    matching_count: int
    source_event_count: int
    fields: list[str]
    users: list[str]
    empty_message: str | None = None
    input_warning: str | None = None


def build_dashboard_model(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    voyage_chart_limit: int = 10,
    recent_limit: int = 8,
    attention_limit: int = 8,
) -> OperationalDashboardModel:
    current = apply_current_filters(weekly_df, context)
    metrics = calculate_weekly_metrics(current)
    history = apply_history_filters(history_df, context, current_df=weekly_df)
    grouped_history = deduplicate_voyage_events(history)
    profiles = voyage_load_profiles(weekly_df, context)
    scoped_quality = quality_for_context(quality_df, current, context)

    composition = _voyage_chart_frame(profiles, ["Loaded Containers", "Empty Containers", "Unclassified Containers"], voyage_chart_limit)
    equipment = _voyage_chart_frame(profiles, ["Total 20ft", "Total 40ft"], voyage_chart_limit)
    vessels = aggregate_current(weekly_df, "Vessel", context)
    teu_all = vessels[["Vessel", "Total TEU"]].sort_values("Total TEU", ascending=False, kind="mergesort").reset_index(drop=True) if not vessels.empty else pd.DataFrame(columns=["Vessel", "Total TEU"])
    teu = teu_all.head(12).copy()
    chart_notes: list[str] = []
    if len(profiles) > voyage_chart_limit:
        chart_notes.append(f"Voyage charts show the {voyage_chart_limit} largest by containers; {len(profiles) - voyage_chart_limit} additional voyage instances remain available on Voyages.")
    if len(teu_all) > 12:
        chart_notes.append(f"The TEU chart shows the 12 largest vessels; {len(teu_all) - 12} additional vessels remain available through filters and voyage rows.")

    recent = recent_changes(grouped_history, limit=recent_limit)
    attention = build_attention_items(profiles, weekly_df, history_df, scoped_quality, context, limit=attention_limit)
    quality_counts = _quality_counts(scoped_quality)
    empty = "No current operational rows match the shared filters." if current.empty else None
    return OperationalDashboardModel(
        metrics=metrics,
        has_rows=not current.empty,
        empty_message=empty,
        voyage_composition=composition,
        equipment_mix=equipment,
        teu_by_vessel=teu,
        chart_limit_note=" ".join(chart_notes) or None,
        recent_changes=recent,
        attention_items=attention,
        quality_counts=quality_counts,
    )


def build_voyage_browser_model(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    context: FilterContext | None = None,
) -> VoyageBrowserModel:
    profiles = voyage_load_profiles(weekly_df, context)
    if profiles.empty:
        return VoyageBrowserModel(pd.DataFrame(), 0, "No safely identified voyage instances match the shared filters.")
    schedule = schedule_reliability_by_voyage(weekly_df, history_df, context)
    result = profiles.merge(
        schedule[["IdentityKey", "ETA Revision Count", "Net ETA Movement", "Week Change Count"]],
        on="IdentityKey",
        how="left",
    )
    result["Quality Issues"] = result.apply(lambda row: len(quality_for_identity(quality_df, row)), axis=1)
    result["Attention"] = result.apply(_voyage_attention_label, axis=1)
    result = _disambiguate_visible_voyages(result)
    columns = [
        "IdentityKey",
        "BlockID",
        "Vessel",
        "Voyage",
        "Week",
        "ETA",
        "ETD",
        "POL",
        "POD",
        "SVC",
        "Total Containers",
        "Loaded Containers",
        "Empty Containers",
        "Unclassified Containers",
        "Total TEU",
        "Total GWT",
        "ETA Revision Count",
        "Net ETA Movement",
        "Week Change Count",
        "Cancelled rows",
        "Quality Issues",
        "Attention",
    ]
    result = result[[column for column in columns if column in result.columns]].copy()
    result = result.sort_values(["ETA", "Vessel", "Voyage"], na_position="last", kind="mergesort").reset_index(drop=True)
    return VoyageBrowserModel(result, len(result))


def build_voyage_detail_model(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    identity_key: str,
) -> VoyageDetailModel:
    # An explicitly opened voyage is resolved against the complete snapshot.
    # It deliberately ignores subsequent global Voyage selections until the
    # user returns to the browser.
    profiles = voyage_load_profiles(weekly_df)
    profile_rows = profiles[profiles.get("IdentityKey", pd.Series(index=profiles.index, dtype=object)).eq(identity_key)]
    if profile_rows.empty:
        return VoyageDetailModel(identity_key, False, "This voyage is no longer available in the current workbook snapshot.")
    profile = profile_rows.iloc[0]
    identity = {column: profile.get(column) for column in ["Vessel", "Voyage", "BlockID"]}
    current = _match_identity(apply_current_filters(weekly_df), identity)
    raw_history = match_history_to_current_identity(
        history_df,
        vessel=identity["Vessel"],
        voyage=identity["Voyage"],
        block_id=identity["BlockID"],
    )
    grouped_history = deduplicate_voyage_events(raw_history)
    schedule_rows = schedule_reliability_by_voyage(weekly_df, history_df)
    schedule_matches = schedule_rows[schedule_rows.get("IdentityKey", pd.Series(index=schedule_rows.index, dtype=object)).eq(identity_key)]
    schedule_row = schedule_matches.iloc[0] if not schedule_matches.empty else pd.Series(dtype=object)
    rollover_rows = week_rollover_by_voyage(weekly_df, history_df)
    rollover_matches = rollover_rows[rollover_rows.get("IdentityKey", pd.Series(index=rollover_rows.index, dtype=object)).eq(identity_key)]
    rollover_row = rollover_matches.iloc[0] if not rollover_matches.empty else pd.Series(dtype=object)

    bookings = current[[column for column in BOOKING_COLUMNS if column in current.columns]].copy()
    if "RowStatus" in bookings.columns:
        bookings["RowStatus"] = bookings["RowStatus"].map(lambda value: str(value).strip() if is_meaningful_value(value) else "Active")
    bookings = bookings.rename(columns={"CUSTOMER": "Customer"}).reset_index(drop=True)
    metrics = {name: profile.get(name) for name in [
        "Total Containers", "Loaded Containers", "Empty Containers", "Unclassified Containers",
        "Total TEU", "Total GWT", "Total 20ft", "Total 40ft", "Loaded %", "Empty %",
        "Loaded GWT / Loaded TEU", "Cancelled rows",
    ]}
    original_eta_available = _original_eta_is_supported(raw_history)
    schedule = {
        "Original ETA": format_date(schedule_row.get("Original ETA"), unavailable=not original_eta_available),
        "Current ETA": format_date(schedule_row.get("Current ETA")),
        "Net ETA Movement": schedule_row.get("Net ETA Movement") if original_eta_available else None,
        "Cumulative ETA Movement": schedule_row.get("Cumulative ETA Movement") if original_eta_available else None,
        "ETA Revision Count": schedule_row.get("ETA Revision Count", 0),
        "Largest ETA Revision": schedule_row.get("Largest Single ETA Revision"),
        "Week Change Count": rollover_row.get("Week Change Count", schedule_row.get("Week Change Count", 0)),
        "Original Week": rollover_row.get("Original Week"),
        "Current Week": rollover_row.get("Current Week", profile.get("Week")),
    }
    pol = _display(profile.get("POL"))
    pod = _display(profile.get("POD"))
    route = " → ".join(value for value in [pol, pod] if value != MISSING_TEXT) or MISSING_TEXT
    return VoyageDetailModel(
        identity_key=identity_key,
        available=True,
        empty_message=None,
        vessel=_display(profile.get("Vessel")),
        voyage=_display(profile.get("Voyage")),
        block_id=_display(profile.get("BlockID")),
        week=_week_display(profile.get("Week")),
        svc=_display(profile.get("SVC")),
        route=route,
        eta=format_date(profile.get("ETA")),
        etd=format_date(profile.get("ETD")),
        cut_off=format_date(profile.get("Cut-Off")),
        metrics=metrics,
        schedule=schedule,
        bookings=bookings,
        grouped_timeline=present_history_events(grouped_history, "grouped"),
        raw_timeline=present_history_events(raw_history, "raw"),
        quality_issues=quality_for_identity(quality_df, profile).reset_index(drop=True),
    )


def build_history_model(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    mode: HistoryMode = "grouped",
    field_name: Any | None = None,
    user: Any | None = None,
    start_date: Any | None = None,
    end_date: Any | None = None,
    search: str | None = None,
) -> OperationalHistoryModel:
    if mode not in {"grouped", "raw"}:
        raise ValueError("History mode must be 'grouped' or 'raw'.")
    scoped = apply_history_filters(history_df, context, current_df=weekly_df)
    scoped = _add_customer_context(scoped, weekly_df)
    available_fields = _unique_options(scoped, "Field")
    available_users = _unique_options(scoped, "User")
    events = deduplicate_voyage_events(scoped) if mode == "grouped" else scoped.copy()

    if is_meaningful_value(field_name) and normalize_text(field_name) != "all":
        events = _text_match(events, "Field", field_name)
    if is_meaningful_value(user) and normalize_text(user) != "all":
        events = _text_match(events, "User", user)

    warning_parts: list[str] = []
    start, start_error = _parse_filter_date(start_date, "start")
    end, end_error = _parse_filter_date(end_date, "end")
    if start_error:
        warning_parts.append(start_error)
    if end_error:
        warning_parts.append(end_error)
    timestamps = pd.to_datetime(events.get("Timestamp", pd.Series(index=events.index, dtype=object)), errors="coerce")
    if start is not None:
        events = events[timestamps.dt.normalize() >= start.normalize()].copy()
        timestamps = pd.to_datetime(events.get("Timestamp"), errors="coerce")
    if end is not None:
        events = events[timestamps.dt.normalize() <= end.normalize()].copy()
    if search and normalize_text(search):
        events = _search_history(events, search)

    rows = present_history_events(events, mode)
    source_count = int(pd.to_numeric(rows.get("Raw Events", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not rows.empty else 0
    empty = "No history events match the selected filters and search." if rows.empty else None
    return OperationalHistoryModel(
        rows=rows,
        mode=mode,
        matching_count=len(rows),
        source_event_count=source_count,
        fields=available_fields,
        users=available_users,
        empty_message=empty,
        input_warning=" ".join(warning_parts) or None,
    )


def present_history_events(events: pd.DataFrame, mode: HistoryMode) -> pd.DataFrame:
    columns = HISTORY_DISPLAY_COLUMNS + [
        "RowID",
        "BlockID",
        "IdentityKey",
        "Mode",
        "_TimestampSort",
        "Customer",
        "Current Vessel",
        "Current Voyage",
        "Current Week",
        "Current BlockID",
        IDENTITY_RESOLUTION_COLUMN,
    ]
    if events.empty:
        return pd.DataFrame(columns=columns)
    working = events.copy()
    working["_TimestampSort"] = pd.to_datetime(working.get("Timestamp"), errors="coerce")
    working = working.sort_values("_TimestampSort", ascending=False, na_position="last", kind="mergesort")
    output: list[dict[str, Any]] = []
    for _, event in working.iterrows():
        field_name = event.get("Field")
        legacy = _old_value_unavailable(event)
        raw_count = int(pd.to_numeric(pd.Series([event.get("_source_event_count", 1)]), errors="coerce").fillna(1).iloc[0])
        effective_identity = effective_history_identity_key(event)
        output.append(
            {
                "Timestamp": format_timestamp(event.get("Timestamp")),
                "Vessel": _display(event.get("Vessel")),
                "Voyage": _display(event.get("Voyage")),
                "Week": _week_display(event.get("Week")),
                "Booking number": _display(event.get("Booking number")),
                "Field": _display(field_name),
                "Old Value": format_history_value(field_name, event.get("OldValue"), unavailable=legacy),
                "New Value": format_history_value(field_name, event.get("NewValue")),
                "User": _display(event.get("User")),
                "Raw Events": raw_count,
                "RowID": _display(event.get("RowID")),
                "BlockID": _display(event.get("BlockID")),
                "IdentityKey": effective_identity or "",
                "Mode": "Grouped / Operational" if mode == "grouped" else "Raw Row Event",
                "_TimestampSort": event.get("_TimestampSort"),
                "Customer": _display(event.get("Customer")),
                "Current Vessel": _display(event.get("Current Vessel")),
                "Current Voyage": _display(event.get("Current Voyage")),
                "Current Week": _week_display(event.get("Current Week")),
                "Current BlockID": _display(event.get("Current BlockID")),
                IDENTITY_RESOLUTION_COLUMN: _display(event.get(IDENTITY_RESOLUTION_COLUMN)),
            }
        )
    return pd.DataFrame(output, columns=columns).reset_index(drop=True)


def recent_changes(grouped_history: pd.DataFrame, *, limit: int = 8) -> list[RecentChange]:
    if grouped_history.empty:
        return []
    working = grouped_history.copy()
    working["_timestamp"] = pd.to_datetime(working.get("Timestamp"), errors="coerce")
    working = working[working.get("Field", pd.Series(index=working.index, dtype=object)).map(lambda value: normalize_text(value) in {normalize_text(item) for item in HISTORY_FIELDS})]
    working = working.sort_values("_timestamp", ascending=False, na_position="last", kind="mergesort").head(limit)
    output: list[RecentChange] = []
    for _, event in working.iterrows():
        legacy = _old_value_unavailable(event)
        identity = effective_history_identity_key(event)
        resolved = normalize_text(event.get(IDENTITY_RESOLUTION_COLUMN)) == normalize_text(IDENTITY_RESOLVED)
        vessel = event.get("Current Vessel") if resolved else event.get("Vessel")
        voyage = event.get("Current Voyage") if resolved else event.get("Voyage")
        output.append(
            RecentChange(
                timestamp=format_timestamp(event.get("Timestamp")),
                vessel=_display(vessel),
                voyage=_display(voyage),
                field=_display(event.get("Field")),
                message=history_change_message(event.get("Field"), event.get("OldValue"), event.get("NewValue"), old_unavailable=legacy),
                identity_key=identity,
                raw_event_count=int(event.get("_source_event_count", 1) or 1),
            )
        )
    return output


def build_attention_items(
    profiles: pd.DataFrame,
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    context: FilterContext | None,
    *,
    limit: int = 8,
) -> list[AttentionItem]:
    output: list[AttentionItem] = []
    severity_order = {"critical": 0, "warning": 1, "watch": 2, "information": 3}
    if not quality_df.empty:
        ordered = quality_df.copy()
        ordered["_order"] = ordered.get("Severity", pd.Series(index=ordered.index, dtype=object)).map(lambda value: severity_order.get(normalize_text(value), 3))
        warning_level = ordered[ordered.get("Severity", pd.Series(index=ordered.index, dtype=object)).map(normalize_text).isin({"critical", "warning"})]
        shown_quality = warning_level.sort_values("_order", kind="mergesort").head(3)
        for _, issue in shown_quality.iterrows():
            label = _identity_title(issue)
            output.append(AttentionItem(normalize_text(issue.get("Severity")) or "warning", label, _display(issue.get("Message")), _issue_identity_key(issue)))
        remaining_quality = len(warning_level) - len(shown_quality)
        if remaining_quality > 0:
            output.append(AttentionItem("warning", "Additional data-quality warnings", f"{remaining_quality} more warning-level issue{'s' if remaining_quality != 1 else ''} remain available in the structured quality results."))

    for _, profile in profiles.iterrows():
        identity = profile.get("IdentityKey")
        title = _identity_title(profile)
        unclassified = _number(profile.get("Unclassified Containers"))
        cancelled = int(_number(profile.get("Cancelled rows")))
        if unclassified > 0:
            output.append(AttentionItem("warning", title, f"{unclassified:g} containers have an unclassified LoadStatus.", identity))
        if cancelled > 0:
            output.append(AttentionItem("information", title, f"{cancelled} cancelled booking row{'s' if cancelled != 1 else ''} remain visible for audit.", identity))

    reliability = schedule_reliability_by_voyage(weekly_df, history_df, context)
    rollover = week_rollover_by_voyage(weekly_df, history_df, context)
    for _, row in reliability.iterrows():
        revisions = int(_number(row.get("ETA Revision Count")))
        movement = row.get("Net ETA Movement")
        if revisions >= 2:
            output.append(AttentionItem("watch", _identity_title(row), f"ETA was materially revised {revisions} times; net movement is {_movement_reason(movement)}.", row.get("IdentityKey")))
    for _, row in rollover.iterrows():
        changes = int(_number(row.get("Week Change Count")))
        if changes > 0:
            original = _week_display(row.get("Original Week"))
            current = _week_display(row.get("Current Week"))
            output.append(AttentionItem("watch", _identity_title(row), f"Week changed {changes} time{'s' if changes != 1 else ''}: {original} → {current}.", row.get("IdentityKey")))

    if not profiles.empty:
        analytical = profiles.merge(
            reliability[["IdentityKey", "ETA Revision Count", "Cumulative ETA Movement", "Week Change Count"]],
            on="IdentityKey",
            how="left",
        )
        anomalies = detect_explainable_anomalies(analytical, minimum_sample=8)
        label_by_key = {row["IdentityKey"]: _identity_title(row) for _, row in profiles.iterrows()}
        for _, anomaly in anomalies.iterrows():
            key = anomaly.get("Entity")
            output.append(AttentionItem(normalize_text(anomaly.get("Severity")) or "watch", label_by_key.get(key, "Voyage attention"), _display(anomaly.get("Reason")), key))

    unique: dict[tuple[str, str], AttentionItem] = {}
    for item in output:
        unique.setdefault((item.title, item.reason), item)
    return sorted(unique.values(), key=lambda item: (severity_order.get(item.severity, 3), item.title.casefold(), item.reason.casefold()))[:limit]


def quality_for_context(quality_df: pd.DataFrame, current_df: pd.DataFrame, context: FilterContext | None) -> pd.DataFrame:
    if quality_df.empty or not _context_active(context):
        return quality_df.copy()
    row_ids = {normalize_text(value) for value in current_df.get("RowID", pd.Series(dtype=object)).tolist() if normalize_text(value)}
    if "RowID" not in quality_df.columns:
        return quality_df.iloc[0:0].copy()
    return quality_df[quality_df["RowID"].map(normalize_text).isin(row_ids)].copy()


def quality_for_identity(quality_df: pd.DataFrame, identity: pd.Series | dict[str, Any]) -> pd.DataFrame:
    if quality_df.empty:
        return quality_df.copy()
    return _match_identity(quality_df, {column: identity.get(column) for column in ["Vessel", "Voyage", "BlockID"]})


def _voyage_chart_frame(profiles: pd.DataFrame, values: list[str], limit: int) -> pd.DataFrame:
    columns = ["IdentityKey", "Label"] + values
    if profiles.empty:
        return pd.DataFrame(columns=columns)
    output = profiles.copy()
    output["Label"] = output.apply(
        lambda row: format_voyage_identity(vessel=row.get("Vessel"), voyage=row.get("Voyage"), week=row.get("Week")), axis=1
    )
    output = output.sort_values("Total Containers", ascending=False, kind="mergesort").head(limit)
    return output[[column for column in columns if column in output.columns]].reset_index(drop=True)


def _voyage_attention_label(row: pd.Series) -> str:
    labels: list[str] = []
    if _number(row.get("Cancelled rows")) > 0:
        labels.append("Cancelled")
    if _number(row.get("Unclassified Containers")) > 0:
        labels.append("Unclassified cargo")
    if _number(row.get("Week Change Count")) > 0:
        labels.append("Week changed")
    if _number(row.get("ETA Revision Count")) > 1:
        labels.append("Multiple ETA revisions")
    if _number(row.get("Quality Issues")) > 0:
        labels.append(f"{int(_number(row.get('Quality Issues')))} data issues")
    return ", ".join(labels) if labels else "—"


def _disambiguate_visible_voyages(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["_Voyage"] = result["Voyage"]
    keys = result[["Vessel", "Voyage"]].astype(str).agg("||".join, axis=1)
    counts = keys.value_counts()
    seen: dict[str, int] = {}
    labels: list[str] = []
    for key, value in zip(keys, result["Voyage"], strict=False):
        seen[key] = seen.get(key, 0) + 1
        labels.append(f"{value} · {seen[key]}/{counts[key]}" if counts[key] > 1 else str(value))
    result["Voyage"] = labels
    return result


def _match_identity(frame: pd.DataFrame, identity: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    mask = pd.Series(True, index=frame.index)
    for column in ["Vessel", "Voyage", "BlockID"]:
        if column not in frame.columns:
            return frame.iloc[0:0].copy()
        mask &= frame[column].map(normalize_text).eq(normalize_text(identity.get(column)))
    return frame[mask].copy()


def _identity_title(row: pd.Series | dict[str, Any]) -> str:
    vessel = _display(row.get("Vessel"), "Unknown vessel")
    voyage = _display(row.get("Voyage"), "Unknown voyage")
    return f"{vessel} / {voyage}"


def _issue_identity_key(issue: pd.Series) -> str | None:
    if not all(is_meaningful_value(issue.get(column)) for column in ["Vessel", "Voyage", "BlockID"]):
        return None
    return voyage_identity_key(issue.get("Vessel"), issue.get("Voyage"), issue.get("BlockID"))


def _quality_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = {"Critical": 0, "Warning": 0, "Information": 0}
    if frame.empty or "Severity" not in frame.columns:
        return counts
    values = frame["Severity"].map(normalize_text).value_counts()
    for name in counts:
        counts[name] = int(values.get(normalize_text(name), 0))
    return counts


def _add_customer_context(history: pd.DataFrame, weekly: pd.DataFrame) -> pd.DataFrame:
    result = history.copy()
    result["Customer"] = pd.NA
    if result.empty or "RowID" not in result.columns or "RowID" not in weekly.columns or "CUSTOMER" not in weekly.columns:
        return result
    crosswalk: dict[str, Any] = {}
    for _, row in weekly.iterrows():
        key = normalize_text(row.get("RowID"))
        if key and key not in crosswalk and is_meaningful_value(row.get("CUSTOMER")):
            crosswalk[key] = row.get("CUSTOMER")
    result["Customer"] = result["RowID"].map(lambda value: crosswalk.get(normalize_text(value), pd.NA))
    return result


def _search_history(events: pd.DataFrame, search: str) -> pd.DataFrame:
    needle = normalize_text(search)
    searchable = [
        "Vessel",
        "Voyage",
        "Week",
        "Booking number",
        "Customer",
        "Field",
        "OldValue",
        "NewValue",
        "User",
        "RowID",
        "BlockID",
        "Current Vessel",
        "Current Voyage",
        "Current Week",
        "Current BlockID",
        "Current Booking number",
        "Current CUSTOMER",
    ]
    mask = pd.Series(False, index=events.index)
    for column in searchable:
        if column in events.columns:
            mask |= events[column].map(normalize_text).str.contains(needle, regex=False, na=False)
    return events[mask].copy()


def _text_match(frame: pd.DataFrame, column: str, value: Any) -> pd.DataFrame:
    if column not in frame.columns:
        return frame.iloc[0:0].copy()
    return frame[frame[column].map(normalize_text).eq(normalize_text(value))].copy()


def _parse_filter_date(value: Any, label: str) -> tuple[pd.Timestamp | None, str | None]:
    if not is_meaningful_value(value):
        return None, None
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value), None
    text = str(value).strip()
    for dayfirst in [True, False]:
        parsed = pd.to_datetime(text, errors="coerce", dayfirst=dayfirst)
        if not pd.isna(parsed):
            return pd.Timestamp(parsed), None
    return None, f"The {label} date is invalid; use DD.MM.YYYY."


def _unique_options(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return ["All"]
    values: dict[str, str] = {}
    for value in frame[column].tolist():
        key = normalize_text(value)
        if key:
            values.setdefault(key, str(value).strip())
    return ["All"] + sorted(values.values(), key=str.casefold)


def _context_active(context: FilterContext | None) -> bool:
    return context is not None and any(getattr(context, item.name) is not None for item in fields(FilterContext))


def _display(value: Any, fallback: str = MISSING_TEXT) -> str:
    return str(value).strip() if is_meaningful_value(value) else fallback


def _week_display(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return MISSING_TEXT
    return str(int(numeric)) if float(numeric).is_integer() else str(value).strip()


def _number(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return 0.0 if pd.isna(numeric) else float(numeric)


def _movement_reason(value: Any) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return UNAVAILABLE_TEXT.lower()
    if float(number) > 0:
        return f"+{float(number):g} days later"
    if float(number) < 0:
        return f"{float(number):g} days earlier"
    return "0 days"


def _original_eta_is_supported(history: pd.DataFrame) -> bool:
    if history.empty or "Field" not in history.columns:
        return False
    eta_events = history[history["Field"].map(normalize_text).eq("eta")]
    for _, event in eta_events.iterrows():
        if bool(event.get("_legacy_bulk_edit", False)) or is_legacy_unavailable(event.get("_raw_OldValue")):
            continue
        old_value = event.get("OldValue")
        if is_meaningful_value(old_value) and parse_schedule_date(old_value, field_name="ETA").parsed is not None:
            return True
    return False


def _old_value_unavailable(event: pd.Series) -> bool:
    if "_raw_OldValue" in event.index:
        return is_legacy_unavailable(event.get("_raw_OldValue"))
    return bool(event.get("_legacy_bulk_edit", False)) and not is_meaningful_value(event.get("OldValue"))
