from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from .analytics import calculate_eta_movement, calculate_revision_counts, get_vessel_summary, get_voyage_summary
from .date_utils import is_meaningful_value, normalize_text
from .filters import filter_history, filter_weekly
from .history_processing import history_with_current_context


IDENTITY_COLUMNS = ["Vessel", "Voyage", "BlockID"]


def operational_by_vessel(weekly_df: pd.DataFrame) -> pd.DataFrame:
    return _aggregate_operational(weekly_df, ["Vessel"])


def operational_by_voyage(weekly_df: pd.DataFrame) -> pd.DataFrame:
    return _aggregate_operational(weekly_df, IDENTITY_COLUMNS)


def teu_by_vessel(weekly_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _top_metric(operational_by_vessel(weekly_df), "Vessel", "TEU", limit=limit)


def ts_by_vessel(weekly_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _top_metric(operational_by_vessel(weekly_df), "Vessel", "TS", limit=limit)


def summary_by_vessel(weekly_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _top_metric(operational_by_vessel(weekly_df), "Vessel", "Summary", limit=limit)


def teu_by_voyage(weekly_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    frame = operational_by_voyage(weekly_df)
    frame = _add_voyage_label(frame)
    return _top_metric(frame, "Label", "TEU", limit=limit)


def ts_by_voyage(weekly_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    frame = operational_by_voyage(weekly_df)
    frame = _add_voyage_label(frame)
    return _top_metric(frame, "Label", "TS", limit=limit)


def summary_by_voyage(weekly_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    frame = operational_by_voyage(weekly_df)
    frame = _add_voyage_label(frame)
    return _top_metric(frame, "Label", "Summary", limit=limit)


def cancellations_by_vessel(weekly_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _aggregate_cancellations(weekly_df, ["Vessel"], limit=limit)


def cancellations_by_voyage(weekly_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    frame = _aggregate_cancellations(weekly_df, IDENTITY_COLUMNS, limit=None)
    frame = _add_voyage_label(frame)
    return _rank(frame, "Cancelled rows", label_columns=["Label", "Vessel", "Voyage", "BlockID"], limit=limit)


def cancellations_by_week(weekly_df: pd.DataFrame) -> pd.DataFrame:
    cancelled = _cancelled_weekly_rows(weekly_df)
    if cancelled.empty:
        return pd.DataFrame(columns=["Week", "Cancelled rows"])

    if "Week" in cancelled.columns:
        usable = cancelled[cancelled["Week"].map(is_meaningful_value)].copy()
        grouped = _group_and_count(usable, ["Week"], "Cancelled rows")
        return grouped.sort_values("Week", kind="mergesort").reset_index(drop=True)

    return pd.DataFrame(columns=["Week", "Cancelled rows"])


def history_events_by_vessel(history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    return _history_event_counts(history_df, ["Vessel"], limit=limit)


def history_events_by_voyage(history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    frame = _history_event_counts(history_df, IDENTITY_COLUMNS, limit=None)
    frame = _add_voyage_label(frame)
    return _rank(frame, "History events", label_columns=["Label", "Vessel", "Voyage", "BlockID"], limit=limit)


def history_events_by_month(history_df: pd.DataFrame) -> pd.DataFrame:
    return history_events_over_time(history_df, period="Month")


def history_events_by_quarter(history_df: pd.DataFrame) -> pd.DataFrame:
    return history_events_over_time(history_df, period="Quarter")


def history_events_by_year(history_df: pd.DataFrame) -> pd.DataFrame:
    return history_events_over_time(history_df, period="Year")


def history_events_by_week(history_df: pd.DataFrame) -> pd.DataFrame:
    return history_events_over_time(history_df, period="Week")


def history_events_over_time(history_df: pd.DataFrame, *, period: str = "Month") -> pd.DataFrame:
    enriched = add_history_time_columns(history_df)
    period_column = _period_column(period)
    if enriched.empty or period_column not in enriched.columns:
        return pd.DataFrame(columns=[period_column, "History events"])

    usable = enriched[enriched[period_column].map(is_meaningful_value)].copy()
    if usable.empty:
        return pd.DataFrame(columns=[period_column, "History events"])

    grouped = usable.groupby(period_column, dropna=False).size().reset_index(name="History events")
    sort_column = f"_{period_column}_sort"
    if sort_column in usable.columns:
        order = usable[[period_column, sort_column]].drop_duplicates().sort_values(sort_column, kind="mergesort")
        grouped = order[[period_column]].merge(grouped, on=period_column, how="left")
    return grouped.reset_index(drop=True)


def add_history_time_columns(history_df: pd.DataFrame) -> pd.DataFrame:
    result = history_df.copy()
    if result.empty or "Timestamp" not in result.columns:
        for column in ["History Week", "History Month", "History Quarter", "History Year"]:
            result[column] = pd.Series(dtype=object)
        return result

    timestamps = pd.to_datetime(result["Timestamp"], errors="coerce")
    iso_calendar = timestamps.dt.isocalendar()
    result["History Year"] = timestamps.dt.year.astype("Int64").astype(str).replace("<NA>", "")
    result["History Month"] = timestamps.dt.strftime("%Y-%m").fillna("")
    result["History Quarter"] = timestamps.map(lambda value: _quarter_label(value) if not pd.isna(value) else "")
    result["History Week"] = [
        f"{int(year)}-W{int(week):02d}" if not pd.isna(year) and not pd.isna(week) else ""
        for year, week in zip(iso_calendar["year"], iso_calendar["week"], strict=False)
    ]
    result["_History Month_sort"] = timestamps.dt.to_period("M").astype(str).replace("NaT", "")
    result["_History Quarter_sort"] = timestamps.map(lambda value: f"{value.year}Q{((value.month - 1) // 3) + 1}" if not pd.isna(value) else "")
    result["_History Year_sort"] = timestamps.dt.year.fillna(0).astype(int)
    result["_History Week_sort"] = [
        int(year) * 100 + int(week) if not pd.isna(year) and not pd.isna(week) else 0
        for year, week in zip(iso_calendar["year"], iso_calendar["week"], strict=False)
    ]
    return result


def material_revisions_by_vessel(history_df: pd.DataFrame, field_name: str = "ETA", *, limit: int | None = None) -> pd.DataFrame:
    return _material_revisions_by(history_with_current_context(history_df), "Vessel", field_name, limit=limit)


def material_revisions_by_voyage(history_df: pd.DataFrame, field_name: str = "ETA", *, limit: int | None = None) -> pd.DataFrame:
    history_df = history_with_current_context(history_df)
    counts = calculate_revision_counts(history_df, "RowID", fields=[field_name])
    if counts.empty or "RowID" not in counts.columns:
        return pd.DataFrame(columns=["Label", "Vessel", "Voyage", "BlockID", f"{field_name} revisions"])

    identity = _history_identity_by_row(history_df)
    merged = identity.merge(counts[["RowID", f"{_field_column_name(field_name)}_revisions"]], on="RowID", how="left")
    metric = f"{field_name} revisions"
    merged[metric] = pd.to_numeric(merged[f"{_field_column_name(field_name)}_revisions"], errors="coerce").fillna(0)
    grouped = merged.groupby(IDENTITY_COLUMNS, dropna=False, as_index=False)[metric].sum()
    grouped = _add_voyage_label(grouped)
    return _rank(grouped, metric, label_columns=["Label", "Vessel", "Voyage", "BlockID"], limit=limit)


def voyage_instance_options(weekly_df: pd.DataFrame, history_df: pd.DataFrame) -> pd.DataFrame:
    rows: dict[str, dict[str, Any]] = {}
    _collect_voyage_instances(rows, weekly_df, source="weekly")
    _collect_voyage_instances(rows, history_with_current_context(history_df), source="history")
    if not rows:
        return pd.DataFrame(columns=["IdentityKey", "Label", "Vessel", "Voyage", "BlockID", "weekly_rows", "history_events"])
    frame = pd.DataFrame(rows.values())
    frame = frame.sort_values(["Vessel", "Voyage", "BlockID"], kind="mergesort").reset_index(drop=True)
    return frame[["IdentityKey", "Label", "Vessel", "Voyage", "BlockID", "weekly_rows", "history_events"]]


def voyage_performance_table(weekly_df: pd.DataFrame, history_df: pd.DataFrame, *, vessel: Any | None = None) -> pd.DataFrame:
    history_df = history_with_current_context(history_df)
    options = voyage_instance_options(weekly_df, history_df)
    if vessel is not None:
        options = options[options["Vessel"].map(normalize_text) == normalize_text(vessel)].copy()
    if options.empty:
        return _empty_voyage_performance_frame()

    rows = [_voyage_summary_row(weekly_df, history_df, option) for _, option in options.iterrows()]
    return pd.DataFrame(rows, columns=_empty_voyage_performance_frame().columns)


def vessel_schedule_performance(weekly_df: pd.DataFrame, history_df: pd.DataFrame) -> pd.DataFrame:
    voyage_table = voyage_performance_table(weekly_df, history_df)
    columns = [
        "Vessel",
        "Voyages",
        "Average net ETA movement",
        "Average absolute ETA movement",
        "Average ETA revisions per Voyage",
        "Maximum delay",
        "Maximum early movement",
        "Most revised Voyage",
    ]
    if voyage_table.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for vessel, group in voyage_table.groupby("Vessel", dropna=False, sort=True):
        net_values = pd.to_numeric(group["Net ETA movement"], errors="coerce").dropna()
        revision_values = pd.to_numeric(group["ETA revisions"], errors="coerce").fillna(0)
        max_delay = net_values.max() if not net_values.empty else None
        max_early = net_values.min() if not net_values.empty else None
        most_revised = group.sort_values(["ETA revisions", "Label"], ascending=[False, True], kind="mergesort").iloc[0]
        rows.append(
            {
                "Vessel": vessel,
                "Voyages": int(len(group)),
                "Average net ETA movement": float(net_values.mean()) if not net_values.empty else None,
                "Average absolute ETA movement": float(net_values.abs().mean()) if not net_values.empty else None,
                "Average ETA revisions per Voyage": float(revision_values.mean()) if not revision_values.empty else 0.0,
                "Maximum delay": float(max_delay) if max_delay is not None and not pd.isna(max_delay) else None,
                "Maximum early movement": float(max_early) if max_early is not None and not pd.isna(max_early) else None,
                "Most revised Voyage": most_revised["Label"] if not group.empty else "",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def most_unstable_voyages_by_eta_revisions(weekly_df: pd.DataFrame, history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    table = voyage_performance_table(weekly_df, history_df)
    return _rank(table, "ETA revisions", label_columns=["Label", "Vessel", "Voyage", "BlockID"], limit=limit)


def largest_eta_movement_voyages(weekly_df: pd.DataFrame, history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    table = voyage_performance_table(weekly_df, history_df)
    if table.empty:
        return pd.DataFrame(columns=["Label", "Vessel", "Voyage", "BlockID", "Original ETA", "Current ETA", "Net ETA movement", "Abs net ETA movement"])
    ranked = table.copy()
    ranked["Abs net ETA movement"] = pd.to_numeric(ranked["Net ETA movement"], errors="coerce").abs()
    ranked = ranked[ranked["Abs net ETA movement"].fillna(0) > 0]
    if ranked.empty:
        return pd.DataFrame(columns=["Label", "Vessel", "Voyage", "BlockID", "Original ETA", "Current ETA", "Net ETA movement", "Abs net ETA movement"])
    ranked = ranked.sort_values(["Abs net ETA movement", "Label"], ascending=[False, True], kind="mergesort")
    if limit is not None:
        ranked = ranked.head(limit).copy()
    return ranked[["Label", "Vessel", "Voyage", "BlockID", "Original ETA", "Current ETA", "Net ETA movement", "Abs net ETA movement"]].reset_index(drop=True)


def largest_cumulative_eta_movement_voyages(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    *,
    limit: int | None = None,
) -> pd.DataFrame:
    table = voyage_performance_table(weekly_df, history_df)
    return _rank(table, "Cumulative ETA movement", label_columns=["Label", "Vessel", "Voyage", "BlockID"], limit=limit)


def most_unstable_vessels_by_eta_revisions(weekly_df: pd.DataFrame, history_df: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    _ = weekly_df
    return material_revisions_by_vessel(history_df, "ETA", limit=limit)


def voyage_comparison_table(weekly_df: pd.DataFrame, history_df: pd.DataFrame, identity_keys: Iterable[str]) -> pd.DataFrame:
    history_df = history_with_current_context(history_df)
    options = voyage_instance_options(weekly_df, history_df)
    selected_keys = _dedupe_keys(identity_keys)
    if len(selected_keys) < 2 or options.empty:
        return _empty_comparison_frame()

    selected = options[options["IdentityKey"].isin(selected_keys)].copy()
    if len(selected) < 2:
        return _empty_comparison_frame()

    rows = [_comparison_row(weekly_df, history_df, option) for _, option in selected.iterrows()]
    return pd.DataFrame(rows, columns=_empty_comparison_frame().columns)


def prepare_chart_series(
    frame: pd.DataFrame,
    *,
    label_column: str,
    value_column: str,
    limit: int | None = None,
    keep_zero: bool = False,
) -> pd.DataFrame:
    if frame.empty or label_column not in frame.columns or value_column not in frame.columns:
        return pd.DataFrame(columns=["Label", "Value"])

    series = frame[[label_column, value_column]].copy()
    series = series.rename(columns={label_column: "Label", value_column: "Value"})
    series["Value"] = pd.to_numeric(series["Value"], errors="coerce").fillna(0.0)
    series["Label"] = series["Label"].astype(str).str.strip()
    series = series[series["Label"] != ""]
    if not keep_zero:
        series = series[series["Value"] != 0]
    if series.empty:
        return pd.DataFrame(columns=["Label", "Value"])
    series = series.sort_values(["Value", "Label"], ascending=[False, True], kind="mergesort")
    if limit is not None:
        series = series.head(limit).copy()
    return series.reset_index(drop=True)


def _aggregate_operational(weekly_df: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    active = _active_weekly_rows(weekly_df)
    columns = group_columns + ["operational rows", "Summary", "TEU", "TS"]
    if active.empty or not all(column in active.columns for column in group_columns):
        return pd.DataFrame(columns=columns)

    values = active.copy()
    for column in ["Summary", "TEU", "TS"]:
        values[column] = pd.to_numeric(values[column], errors="coerce").fillna(0.0) if column in values.columns else 0.0
    grouped = values.groupby(group_columns, dropna=False, as_index=False).agg(
        **{
            "operational rows": ("RowID", "count") if "RowID" in values.columns else (group_columns[0], "size"),
            "Summary": ("Summary", "sum"),
            "TEU": ("TEU", "sum"),
            "TS": ("TS", "sum"),
        }
    )
    return grouped[columns].sort_values(group_columns, kind="mergesort").reset_index(drop=True)


def _aggregate_cancellations(weekly_df: pd.DataFrame, group_columns: list[str], *, limit: int | None = None) -> pd.DataFrame:
    cancelled = _cancelled_weekly_rows(weekly_df)
    columns = group_columns + ["Cancelled rows"]
    if cancelled.empty or not all(column in cancelled.columns for column in group_columns):
        return pd.DataFrame(columns=columns)
    grouped = _group_and_count(cancelled, group_columns, "Cancelled rows")
    return _rank(grouped, "Cancelled rows", label_columns=group_columns, limit=limit)


def _history_event_counts(history_df: pd.DataFrame, group_columns: list[str], *, limit: int | None = None) -> pd.DataFrame:
    columns = group_columns + ["History events"]
    if history_df.empty or not all(column in history_df.columns for column in group_columns):
        return pd.DataFrame(columns=columns)
    records = history_df[history_df.notna().any(axis=1)].copy()
    if records.empty:
        return pd.DataFrame(columns=columns)
    grouped = _group_and_count(records, group_columns, "History events")
    return _rank(grouped, "History events", label_columns=group_columns, limit=limit)


def _material_revisions_by(history_df: pd.DataFrame, group_by: str, field_name: str, *, limit: int | None = None) -> pd.DataFrame:
    safe_field = _field_column_name(field_name)
    metric = f"{field_name} revisions"
    columns = [group_by, metric]
    counts = calculate_revision_counts(history_df, group_by, fields=[field_name])
    revision_column = f"{safe_field}_revisions"
    if counts.empty or revision_column not in counts.columns:
        return pd.DataFrame(columns=columns)
    result = counts[[group_by, revision_column]].rename(columns={revision_column: metric})
    return _rank(result, metric, label_columns=[group_by], limit=limit)


def _history_identity_by_row(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty or "RowID" not in history_df.columns:
        return pd.DataFrame(columns=["RowID"] + IDENTITY_COLUMNS)
    rows = []
    for row_id, group in history_df.groupby("RowID", dropna=False, sort=True):
        rows.append(
            {
                "RowID": row_id,
                "Vessel": _first_meaningful(group.get("Vessel", pd.Series(dtype=object))),
                "Voyage": _first_meaningful(group.get("Voyage", pd.Series(dtype=object))),
                "BlockID": _first_meaningful(group.get("BlockID", pd.Series(dtype=object))),
            }
        )
    return pd.DataFrame(rows, columns=["RowID"] + IDENTITY_COLUMNS)


def _voyage_summary_row(weekly_df: pd.DataFrame, history_df: pd.DataFrame, option: pd.Series) -> dict[str, Any]:
    summary = get_voyage_summary(
        weekly_df,
        history_df,
        option["Voyage"],
        vessel=option["Vessel"],
        block_id=option["BlockID"],
    )
    return {
        "IdentityKey": option["IdentityKey"],
        "Label": option["Label"],
        "Vessel": option["Vessel"],
        "Voyage": option["Voyage"],
        "BlockID": option["BlockID"],
        "operational rows": summary.current_operational_row_count,
        "cancelled rows": summary.cancelled_row_count,
        "Summary": summary.total_summary,
        "TEU": summary.total_teu,
        "TS": summary.total_ts,
        "Original ETA": summary.original_eta,
        "Current ETA": summary.current_eta,
        "Net ETA movement": summary.net_eta_movement_days,
        "Cumulative ETA movement": summary.cumulative_eta_movement_days,
        "ETA revisions": summary.eta_revision_count,
        "ETD revisions": summary.etd_revision_count,
        "Cut-Off revisions": summary.cut_off_revision_count,
        "ETA T/S revisions": summary.eta_ts_revision_count,
        "Total history events": summary.total_history_events,
    }


def _comparison_row(weekly_df: pd.DataFrame, history_df: pd.DataFrame, option: pd.Series) -> dict[str, Any]:
    row = _voyage_summary_row(weekly_df, history_df, option)
    return {column: row.get(column) for column in _empty_comparison_frame().columns}


def _empty_voyage_performance_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "IdentityKey",
            "Label",
            "Vessel",
            "Voyage",
            "BlockID",
            "operational rows",
            "cancelled rows",
            "Summary",
            "TEU",
            "TS",
            "Original ETA",
            "Current ETA",
            "Net ETA movement",
            "Cumulative ETA movement",
            "ETA revisions",
            "ETD revisions",
            "Cut-Off revisions",
            "ETA T/S revisions",
            "Total history events",
        ]
    )


def _empty_comparison_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "Label",
            "Vessel",
            "Voyage",
            "BlockID",
            "operational rows",
            "cancelled rows",
            "Summary",
            "TEU",
            "TS",
            "Original ETA",
            "Current ETA",
            "Net ETA movement",
            "Cumulative ETA movement",
            "ETA revisions",
            "ETD revisions",
            "Cut-Off revisions",
            "ETA T/S revisions",
            "Total history events",
        ]
    )


def _active_weekly_rows(weekly_df: pd.DataFrame) -> pd.DataFrame:
    if weekly_df.empty:
        return weekly_df.copy()
    operational = weekly_df["_is_operational"].fillna(False).astype(bool) if "_is_operational" in weekly_df.columns else pd.Series(True, index=weekly_df.index)
    cancelled = _is_cancelled_series(weekly_df)
    return weekly_df[operational & ~cancelled].copy()


def _cancelled_weekly_rows(weekly_df: pd.DataFrame) -> pd.DataFrame:
    if weekly_df.empty:
        return weekly_df.copy()
    operational = weekly_df["_is_operational"].fillna(False).astype(bool) if "_is_operational" in weekly_df.columns else pd.Series(True, index=weekly_df.index)
    return weekly_df[operational & _is_cancelled_series(weekly_df)].copy()


def _is_cancelled_series(df: pd.DataFrame) -> pd.Series:
    if "RowStatus" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["RowStatus"].astype(str).str.strip().str.upper() == "CANCELLED"


def _collect_voyage_instances(rows: dict[str, dict[str, Any]], df: pd.DataFrame, *, source: str) -> None:
    if df.empty or "Voyage" not in df.columns:
        return

    for _, row in df.iterrows():
        voyage = _safe_text(row.get("Voyage"))
        if not voyage:
            continue
        vessel = _safe_text(row.get("Vessel"))
        block_id = _safe_text(row.get("BlockID"))
        key = _identity_key(vessel, voyage, block_id)
        rows.setdefault(
            key,
            {
                "IdentityKey": key,
                "Label": _voyage_label(vessel, voyage, block_id),
                "Vessel": vessel,
                "Voyage": voyage,
                "BlockID": block_id,
                "weekly_rows": 0,
                "history_events": 0,
            },
        )
        if source == "weekly":
            rows[key]["weekly_rows"] += 1
        else:
            rows[key]["history_events"] += 1


def _identity_key(vessel: str, voyage: str, block_id: str) -> str:
    return "||".join([normalize_text(vessel), normalize_text(voyage), normalize_text(block_id)])


def _voyage_label(vessel: str, voyage: str, block_id: str) -> str:
    parts = [part for part in [vessel, voyage, block_id] if part]
    return " | ".join(parts) if parts else "Unknown voyage"


def _add_voyage_label(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        frame = frame.copy()
        if "Label" not in frame.columns:
            frame["Label"] = pd.Series(dtype=object)
        return frame
    result = frame.copy()
    result["Label"] = [_voyage_label(_safe_text(row.get("Vessel")), _safe_text(row.get("Voyage")), _safe_text(row.get("BlockID"))) for _, row in result.iterrows()]
    return result


def _top_metric(frame: pd.DataFrame, label_column: str, metric_column: str, *, limit: int | None) -> pd.DataFrame:
    return _rank(frame, metric_column, label_columns=[label_column], limit=limit)


def _rank(frame: pd.DataFrame, metric_column: str, *, label_columns: list[str], limit: int | None) -> pd.DataFrame:
    columns = label_columns + [metric_column]
    if frame.empty or metric_column not in frame.columns:
        return pd.DataFrame(columns=columns)
    result = frame.copy()
    result[metric_column] = pd.to_numeric(result[metric_column], errors="coerce").fillna(0.0)
    result = result.sort_values([metric_column] + label_columns, ascending=[False] + [True] * len(label_columns), kind="mergesort")
    if limit is not None:
        result = result.head(limit).copy()
    return result[columns].reset_index(drop=True)


def _group_and_count(df: pd.DataFrame, group_columns: list[str], count_name: str) -> pd.DataFrame:
    usable = df.copy()
    for column in group_columns:
        usable[column] = usable[column].map(_safe_text)
    usable = usable[usable[group_columns].apply(lambda row: any(is_meaningful_value(value) for value in row), axis=1)]
    if usable.empty:
        return pd.DataFrame(columns=group_columns + [count_name])
    return usable.groupby(group_columns, dropna=False).size().reset_index(name=count_name)


def _period_column(period: str) -> str:
    lookup = {
        "week": "History Week",
        "month": "History Month",
        "quarter": "History Quarter",
        "year": "History Year",
    }
    normalized = period.strip().casefold()
    if normalized not in lookup:
        raise ValueError("period must be Week, Month, Quarter, or Year")
    return lookup[normalized]


def _quarter_label(timestamp: pd.Timestamp) -> str:
    return f"{timestamp.year} Q{((timestamp.month - 1) // 3) + 1}"


def _field_column_name(field_name: str) -> str:
    return field_name.replace("-", "_").replace("/", "_").replace(" ", "_")


def _first_meaningful(values: Iterable[Any]) -> Any:
    for value in values:
        if is_meaningful_value(value):
            return str(value).strip()
    return ""


def _safe_text(value: Any) -> str:
    if not is_meaningful_value(value):
        return ""
    return str(value).strip()


def _dedupe_keys(identity_keys: Iterable[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for key in identity_keys:
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return keys
