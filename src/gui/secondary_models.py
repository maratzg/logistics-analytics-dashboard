from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from src.analytical_filters import FilterContext, apply_current_filters, apply_history_filters
from src.comparison_analytics import comparison_candidates, compare_voyage_instances
from src.date_utils import is_meaningful_value, normalize_text, parse_schedule_date
from src.entity_analytics import customer_analytics, service_analytics
from src.history_processing import effective_history_identity_key, is_legacy_unavailable
from src.operational_analytics import aggregate_current, voyage_identity_key
from src.schedule_analytics import (
    aggregate_schedule_reliability,
    aggregate_week_rollover,
    schedule_reliability_by_voyage,
    week_rollover_by_voyage,
)
from src.time_analytics import current_period_aggregation

from .operational_models import build_voyage_browser_model, quality_for_context
from .presentation import format_date


EntityKind = Literal["vessel", "service", "customer"]
UNASSIGNED_LABEL = "Unassigned"
UNASSIGNED_KEY = "__unassigned__"


@dataclass(frozen=True, slots=True)
class EntityAnalyticsPageModel:
    kind: EntityKind
    label_column: str
    overview: pd.DataFrame
    selected_key: str | None
    selected_label: str | None
    summary: dict[str, Any]
    voyages: pd.DataFrame
    pod_breakdown: pd.DataFrame
    customer_breakdown: pd.DataFrame
    service_breakdown: pd.DataFrame
    trend: pd.DataFrame
    empty_message: str | None = None
    detail_message: str | None = None


@dataclass(frozen=True, slots=True)
class ComparisonPageModel:
    candidates: pd.DataFrame
    selected_keys: tuple[str, ...]
    rows: pd.DataFrame
    empty_message: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class DataQualityPageModel:
    rows: pd.DataFrame
    scope_count: int
    counts: dict[str, int]
    affected_rows: int
    affected_voyages: int
    severities: list[str]
    categories: list[str]
    empty_message: str | None = None


ENTITY_COLUMNS = {"vessel": "Vessel", "service": "SVC", "customer": "CUSTOMER"}
SCHEDULE_COLUMNS = [
    "Median Net ETA Movement",
    "Median ETA Revision Count",
    "Median Cumulative ETA Movement",
    "Largest Observed ETA Revision",
]
ROLLOVER_COLUMNS = ["% Voyages Moved Week"]


def build_entity_analytics_model(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    kind: EntityKind,
    context: FilterContext | None = None,
    *,
    selected_key: str | None = None,
) -> EntityAnalyticsPageModel:
    if kind not in ENTITY_COLUMNS:
        raise ValueError(f"Unsupported entity analytics kind: {kind!r}")
    label_column = ENTITY_COLUMNS[kind]
    current = apply_current_filters(weekly_df, context)
    scoped_history = apply_history_filters(history_df, context, current_df=weekly_df)
    overview = _entity_overview(weekly_df, history_df, kind, context)
    empty_message = f"No {kind} values match the shared filters." if overview.empty else None

    if selected_key is None:
        return EntityAnalyticsPageModel(
            kind, label_column, overview, None, None, {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), empty_message
        )

    selected = overview[overview.get("_EntityKey", pd.Series(index=overview.index, dtype=object)).eq(selected_key)]
    if selected.empty:
        return EntityAnalyticsPageModel(
            kind,
            label_column,
            overview,
            None,
            None,
            {},
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            empty_message,
            "The selected value is no longer available in the current filter scope.",
        )

    selected_row = selected.iloc[0]
    selected_label = str(selected_row.get(label_column, UNASSIGNED_LABEL))
    selected_current = _matching_entity(current, label_column, selected_key)
    selected_history = _history_for_current_rows(scoped_history, selected_current)
    selected_quality = _quality_for_current_rows(quality_df, selected_current)
    voyages = build_voyage_browser_model(selected_current, selected_history, selected_quality).rows
    pod_breakdown = _breakdown(selected_current, "POD")
    customer_breakdown = _breakdown(selected_current, "CUSTOMER")
    service_breakdown = _breakdown(selected_current, "SVC")
    trend = current_period_aggregation(selected_current, "ETA Month")

    detail_notes: list[str] = []
    if kind in {"vessel", "service"} and all(pd.isna(selected_row.get(column)) for column in SCHEDULE_COLUMNS):
        detail_notes.append("Comparable ETA history is unavailable for this selection; schedule values are not shown as zero.")
    if kind == "customer" and len(trend) < 2:
        detail_notes.append("There are not enough ETA periods for a meaningful customer trend.")

    return EntityAnalyticsPageModel(
        kind=kind,
        label_column=label_column,
        overview=overview,
        selected_key=selected_key,
        selected_label=selected_label,
        summary=_summary_dict(selected_row),
        voyages=voyages,
        pod_breakdown=pod_breakdown,
        customer_breakdown=customer_breakdown,
        service_breakdown=service_breakdown,
        trend=trend,
        empty_message=empty_message,
        detail_message=" ".join(detail_notes) or None,
    )


def build_comparison_page_model(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    selected_keys: list[str] | tuple[str, ...] | None = None,
) -> ComparisonPageModel:
    candidates = _comparison_candidates(weekly_df, history_df, context)
    requested = [str(value) for value in (selected_keys or []) if is_meaningful_value(value)]
    if len(requested) != len(set(requested)):
        return ComparisonPageModel(candidates, tuple(requested), pd.DataFrame(), error_message="Select each voyage instance only once.")
    if not requested:
        return ComparisonPageModel(candidates, (), pd.DataFrame(), empty_message="Select 2 to 5 voyage instances to compare.")
    if len(requested) < 2:
        return ComparisonPageModel(candidates, tuple(requested), pd.DataFrame(), empty_message="Select at least two voyage instances to compare.")
    if len(requested) > 5:
        return ComparisonPageModel(candidates, tuple(requested), pd.DataFrame(), error_message="A comparison can contain no more than five voyage instances.")
    try:
        # Keep Phase C's comparison validation and safe composite identity rules authoritative.
        core = compare_voyage_instances(weekly_df, history_df, requested, context, candidates_df=candidates)
    except ValueError as exc:
        return ComparisonPageModel(candidates, tuple(requested), pd.DataFrame(), error_message=str(exc))

    order = {key: position for position, key in enumerate(core["IdentityKey"].tolist())}
    rows = candidates[candidates["IdentityKey"].isin(order)].copy()
    rows["_SelectionOrder"] = rows["IdentityKey"].map(order)
    rows = rows.sort_values("_SelectionOrder", kind="mergesort").drop(columns="_SelectionOrder").reset_index(drop=True)
    return ComparisonPageModel(candidates, tuple(requested), rows)


def build_data_quality_page_model(
    weekly_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    severity: Any | None = None,
    category: Any | None = None,
    search: str | None = None,
) -> DataQualityPageModel:
    current = apply_current_filters(weekly_df, context)
    scoped = quality_for_context(quality_df, current, context)
    scoped = _add_quality_context(scoped, weekly_df)
    severities = _options(scoped, "Severity")
    categories = _options(scoped, "Category")
    rows = scoped.copy()
    if _specific_filter(severity):
        rows = rows[rows["Severity"].map(normalize_text).eq(normalize_text(severity))].copy()
    if _specific_filter(category):
        rows = rows[rows["Category"].map(normalize_text).eq(normalize_text(category))].copy()
    if is_meaningful_value(search):
        needle = normalize_text(search)
        mask = pd.Series(False, index=rows.index)
        for column in ["Severity", "Category", "Message", "Vessel", "Voyage", "Booking number", "Field", "Raw Value", "Suggested Correction", "RowID", "BlockID"]:
            if column in rows.columns:
                mask |= rows[column].map(normalize_text).str.contains(needle, regex=False, na=False)
        rows = rows[mask].copy()

    severity_counts = {name: 0 for name in ["Critical", "Warning", "Information"]}
    if not rows.empty and "Severity" in rows.columns:
        counts = rows["Severity"].map(normalize_text).value_counts()
        for name in severity_counts:
            severity_counts[name] = int(counts.get(normalize_text(name), 0))
    affected_rows = len({normalize_text(value) for value in rows.get("RowID", pd.Series(dtype=object)) if normalize_text(value)})
    affected_voyages = len({value for value in rows.get("IdentityKey", pd.Series(dtype=object)).tolist() if is_meaningful_value(value)})
    empty = "No issues found for the current filters." if rows.empty else None
    return DataQualityPageModel(
        rows=rows.reset_index(drop=True),
        scope_count=len(scoped),
        counts=severity_counts,
        affected_rows=affected_rows,
        affected_voyages=affected_voyages,
        severities=severities,
        categories=categories,
        empty_message=empty,
    )


def identity_for_quality_issue(issue: pd.Series | dict[str, Any] | None) -> str | None:
    if issue is None or normalize_text(issue.get("Category")) == "ambiguous history identity":
        return None
    if not all(is_meaningful_value(issue.get(column)) for column in ["Vessel", "Voyage", "BlockID"]):
        return None
    return voyage_identity_key(issue.get("Vessel"), issue.get("Voyage"), issue.get("BlockID"))


def _entity_overview(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    kind: EntityKind,
    context: FilterContext | None,
) -> pd.DataFrame:
    column = ENTITY_COLUMNS[kind]
    if kind == "service":
        base = service_analytics(weekly_df, history_df, context)
        operational = aggregate_current(weekly_df, "SVC", context, include_blank=True)
        base = _merge_missing_metrics(base, operational, "SVC")
    elif kind == "customer":
        base = customer_analytics(weekly_df, context)
        operational = aggregate_current(weekly_df, "CUSTOMER", context, include_blank=True)
        base = _merge_missing_metrics(base, operational, "CUSTOMER")
    else:
        base = aggregate_current(weekly_df, "Vessel", context)
    if base.empty:
        return base.assign(_EntityKey=pd.Series(dtype=object))

    base = base.copy()
    base[column] = base[column].map(_entity_label)
    base["_EntityKey"] = base[column].map(_entity_key)
    base["Cancellation Count"] = _numeric_column(base, "Cancelled rows")
    base["20ft"] = _numeric_column(base, "Total 20ft")
    base["40ft"] = _numeric_column(base, "Total 40ft")
    if kind == "customer":
        if "Share of Overall TEU" in base.columns:
            base["Share of Total TEU"] = base["Share of Overall TEU"]
    else:
        schedule = _available_schedule_summary(weekly_df, history_df, context, column)
        drop = [name for name in SCHEDULE_COLUMNS + ROLLOVER_COLUMNS + ["Schedule Volatility"] if name in base.columns]
        base = base.drop(columns=drop).merge(schedule, on="_EntityKey", how="left")
        base["Median Schedule Volatility"] = base.get("Median Cumulative ETA Movement")
        base["Week Rollover %"] = base.get("% Voyages Moved Week")
    return base.sort_values(["Total TEU", column], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def _merge_missing_metrics(base: pd.DataFrame, operational: pd.DataFrame, column: str) -> pd.DataFrame:
    if base.empty:
        return operational
    left = base.copy()
    right = operational.copy()
    left["_merge_key"] = left[column].map(_entity_key)
    right["_merge_key"] = right[column].map(_entity_key)
    desired = [
        "Loaded Containers", "Empty Containers", "Unclassified Containers", "Total 20ft", "Total 40ft",
        "Cancelled rows", "Booking/Row Count", "Active rows",
    ]
    additions = [name for name in desired if name in right.columns and name not in left.columns]
    if additions:
        left = left.merge(right[["_merge_key"] + additions], on="_merge_key", how="left")
    return left.drop(columns="_merge_key")


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _available_schedule_summary(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    context: FilterContext | None,
    group_column: str,
) -> pd.DataFrame:
    scoped_history = apply_history_filters(history_df, context, current_df=weekly_df)
    schedule = schedule_reliability_by_voyage(weekly_df, history_df, context)
    rollover = week_rollover_by_voyage(weekly_df, history_df, context)
    eta_keys = _comparable_history_keys(scoped_history, "ETA")
    week_keys = _comparable_history_keys(scoped_history, "Week")
    eta_summary = aggregate_schedule_reliability(schedule[schedule["IdentityKey"].isin(eta_keys)], group_column)
    week_summary = aggregate_week_rollover(rollover[rollover["IdentityKey"].isin(week_keys)], group_column)
    frames: list[pd.DataFrame] = []
    for source, columns in [(eta_summary, SCHEDULE_COLUMNS), (week_summary, ROLLOVER_COLUMNS)]:
        if source.empty:
            continue
        part = source[[group_column] + [name for name in columns if name in source.columns]].copy()
        part["_EntityKey"] = part[group_column].map(_entity_key)
        frames.append(part.drop(columns=group_column))
    if not frames:
        return pd.DataFrame(columns=["_EntityKey"] + SCHEDULE_COLUMNS + ROLLOVER_COLUMNS)
    result = frames[0]
    for frame in frames[1:]:
        result = result.merge(frame, on="_EntityKey", how="outer")
    return result


def _comparable_history_keys(history: pd.DataFrame, field: str) -> set[str]:
    if history.empty or "Field" not in history.columns:
        return set()
    events = history[history["Field"].map(normalize_text).eq(normalize_text(field))]
    keys: set[str] = set()
    for _, event in events.iterrows():
        if bool(event.get("_legacy_bulk_edit", False)) or is_legacy_unavailable(event.get("_raw_OldValue")):
            continue
        old_value, new_value = event.get("OldValue"), event.get("NewValue")
        if field == "ETA":
            comparable = (
                parse_schedule_date(old_value, field_name="ETA").parsed is not None
                and parse_schedule_date(new_value, field_name="ETA").parsed is not None
            )
        else:
            comparable = _valid_week(old_value) is not None and _valid_week(new_value) is not None
        if comparable:
            identity_key = effective_history_identity_key(event)
            if identity_key:
                keys.add(identity_key)
    return keys


def _comparison_candidates(weekly_df: pd.DataFrame, history_df: pd.DataFrame, context: FilterContext | None) -> pd.DataFrame:
    core = comparison_candidates(weekly_df, history_df, context)
    if core.empty:
        return core.assign(Label=pd.Series(dtype=object))
    scoped_history = apply_history_filters(history_df, context, current_df=weekly_df)
    eta_keys = _comparable_history_keys(scoped_history, "ETA")
    week_keys = _comparable_history_keys(scoped_history, "Week")
    result = core.copy()
    unavailable_eta = ~result["IdentityKey"].isin(eta_keys)
    for column in ["ETA Revision Count", "Net ETA Movement", "Cumulative ETA Movement", "Largest Single ETA Revision"]:
        if column in result.columns:
            result.loc[unavailable_eta, column] = pd.NA
    if "Week Change Count" in result.columns:
        result.loc[~result["IdentityKey"].isin(week_keys), "Week Change Count"] = pd.NA
    result["Cancellations"] = result.get("Cancelled rows")
    result["GWT / Loaded TEU"] = result.get("Loaded GWT / Loaded TEU")
    result["Largest ETA Revision"] = result.get("Largest Single ETA Revision")
    result["Label"] = [
        f"{_entity_label(row.get('Vessel'))} | {_entity_label(row.get('Voyage'))} | Week {_week_label(row.get('Week'))} | ETA {format_date(row.get('ETA'))}"
        for _, row in result.iterrows()
    ]
    result["Label"] = _disambiguate_labels(result["Label"])
    columns = [
        "IdentityKey", "Label", "Vessel", "Voyage", "BlockID", "Week", "ETA", "Total Containers",
        "Loaded Containers", "Empty Containers", "Loaded %", "Empty %", "Total 20ft", "Total 40ft",
        "Total TEU", "Loaded TEU", "Empty TEU", "Total GWT", "Loaded GWT", "Empty GWT",
        "GWT / Loaded TEU", "ETA Revision Count", "Net ETA Movement",
        "Cumulative ETA Movement", "Largest ETA Revision", "Week Change Count", "Cancellations",
    ]
    return result[[name for name in columns if name in result.columns]].reset_index(drop=True)


def _add_quality_context(issues: pd.DataFrame, weekly_df: pd.DataFrame) -> pd.DataFrame:
    result = issues.copy()
    if result.empty:
        result["Week"] = pd.Series(dtype=object)
        result["IdentityKey"] = pd.Series(dtype=object)
        return result
    week_by_row: dict[str, Any] = {}
    if "RowID" in weekly_df.columns and "Week" in weekly_df.columns:
        for _, row in weekly_df.iterrows():
            key = normalize_text(row.get("RowID"))
            if key and key not in week_by_row:
                week_by_row[key] = row.get("Week")
    result["Week"] = result.get("RowID", pd.Series(index=result.index, dtype=object)).map(lambda value: week_by_row.get(normalize_text(value), pd.NA))
    result["IdentityKey"] = result.apply(identity_for_quality_issue, axis=1)
    return result


def _breakdown(current: pd.DataFrame, column: str) -> pd.DataFrame:
    result = aggregate_current(current, column, include_blank=True)
    if result.empty:
        return result
    result[column] = result[column].map(_entity_label)
    columns = [column, "Voyage Count", "Booking/Row Count", "Total Containers", "Loaded Containers", "Empty Containers", "Total TEU", "Total GWT"]
    return result[[name for name in columns if name in result.columns]].sort_values("Total TEU", ascending=False, kind="mergesort").reset_index(drop=True)


def _matching_entity(frame: pd.DataFrame, column: str, key: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame.iloc[0:0].copy()
    if key == UNASSIGNED_KEY:
        return frame[~frame[column].map(is_meaningful_value)].copy()
    return frame[frame[column].map(normalize_text).eq(key)].copy()


def _history_for_current_rows(history: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    if history.empty or current.empty or "RowID" not in history.columns or "RowID" not in current.columns:
        return history.iloc[0:0].copy()
    keys = {normalize_text(value) for value in current["RowID"].tolist() if normalize_text(value)}
    return history[history["RowID"].map(normalize_text).isin(keys)].copy()


def _quality_for_current_rows(quality: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    if quality.empty or current.empty or "RowID" not in quality.columns or "RowID" not in current.columns:
        return quality.iloc[0:0].copy()
    keys = {normalize_text(value) for value in current["RowID"].tolist() if normalize_text(value)}
    return quality[quality["RowID"].map(normalize_text).isin(keys)].copy()


def _summary_dict(row: pd.Series) -> dict[str, Any]:
    names = [
        "Voyage Count", "Booking/Row Count", "Total Containers", "Loaded Containers", "Empty Containers",
        "Unclassified Containers", "Loaded %", "Empty %", "Total TEU", "Total GWT", "20ft", "40ft",
        "Cancellation Count", "Cancellation Rate", "Average Booking Size", "Share of Total TEU",
        "Median Net ETA Movement", "Median ETA Revision Count", "Median Schedule Volatility", "Week Rollover %",
        "Customer Count",
    ]
    return {name: row.get(name) for name in names}


def _entity_label(value: Any) -> str:
    if not is_meaningful_value(value) or normalize_text(value) in {"unspecified", "unassigned"}:
        return UNASSIGNED_LABEL
    return str(value).strip()


def _entity_key(value: Any) -> str:
    return UNASSIGNED_KEY if _entity_label(value) == UNASSIGNED_LABEL else normalize_text(value)


def _week_label(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "—"
    return str(int(numeric)) if float(numeric).is_integer() else str(value).strip()


def _valid_week(value: Any) -> int | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric) or float(numeric) % 1:
        return None
    week = int(numeric)
    return week if 1 <= week <= 53 else None


def _disambiguate_labels(labels: pd.Series) -> list[str]:
    totals = labels.value_counts()
    seen: dict[str, int] = {}
    output: list[str] = []
    for label in labels.tolist():
        seen[label] = seen.get(label, 0) + 1
        output.append(f"{label} | Instance {seen[label]}/{totals[label]}" if totals[label] > 1 else label)
    return output


def _specific_filter(value: Any) -> bool:
    return is_meaningful_value(value) and normalize_text(value) != "all"


def _options(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return ["All"]
    values: dict[str, str] = {}
    for value in frame[column].tolist():
        key = normalize_text(value)
        if key:
            values.setdefault(key, str(value).strip())
    return ["All"] + sorted(values.values(), key=str.casefold)
