from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable

import pandas as pd

from .analytical_filters import FilterContext, apply_current_filters
from .date_utils import is_meaningful_value, normalize_text
from .history_processing import is_legacy_unavailable
from .operational_analytics import voyage_identity_key, voyage_load_profiles
from .operational_calculations import cancelled_mask


DEFAULT_CHECKPOINTS = (14, 7, 3, 1)


def cargo_evolution_foundation(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    checkpoints: Iterable[int] = DEFAULT_CHECKPOINTS,
) -> pd.DataFrame:
    """Build conservative cargo snapshots; unavailable history stays unavailable."""

    weekly = apply_current_filters(weekly_df, context)
    weekly = weekly[~cancelled_mask(weekly)].copy()
    profiles = voyage_load_profiles(weekly, None)
    columns = [
        "IdentityKey",
        "Vessel",
        "Voyage",
        "BlockID",
        "SVC",
        "ETD",
        "Days Before ETD",
        "Checkpoint Timestamp",
        "Known Containers",
        "Containers",
        "Known TEU",
        "TEU",
        "Containers Complete",
        "TEU Complete",
        "Complete",
        "History Completeness",
        "Incomplete Rows",
        "Completeness Reason",
    ]
    if profiles.empty:
        return pd.DataFrame(columns=columns)

    output: list[dict[str, Any]] = []
    for _, profile in profiles.iterrows():
        identity = {column: profile.get(column) for column in ["Vessel", "Voyage", "BlockID"]}
        current_rows = _match_identity(weekly, identity)
        etd = pd.to_datetime(profile.get("ETD"), errors="coerce")
        for days in checkpoints:
            checkpoint = etd - timedelta(days=int(days)) if not pd.isna(etd) else pd.NaT
            known_containers = 0.0
            known_teu = 0.0
            container_complete_rows = 0
            teu_complete_rows = 0
            incomplete_reasons: list[str] = []
            for _, row in current_rows.iterrows():
                events = _row_history(history_df, row.get("RowID"))
                amount, amount_complete, amount_reason = _numeric_state_at(row.get("CNTR AMT"), events, "CNTR AMT", checkpoint)
                size, size_complete, size_reason = _numeric_state_at(row.get("SIZE"), events, "SIZE", checkpoint)
                container_complete = not pd.isna(checkpoint) and amount_complete
                teu_complete = container_complete and size_complete and size in {2, 4}
                if amount is not None and container_complete:
                    known_containers += amount
                if amount is not None and size is not None and teu_complete:
                    known_teu += amount * (1 if size == 2 else 2)
                if container_complete:
                    container_complete_rows += 1
                else:
                    incomplete_reasons.append(amount_reason or "Incomplete quantity history")
                if teu_complete:
                    teu_complete_rows += 1
                elif amount_complete:
                    incomplete_reasons.append(size_reason or "Incomplete size history")
            row_count = len(current_rows)
            containers_complete = row_count > 0 and container_complete_rows == row_count and not pd.isna(checkpoint)
            teu_complete = row_count > 0 and teu_complete_rows == row_count and not pd.isna(checkpoint)
            complete = containers_complete and teu_complete
            completeness = float(teu_complete_rows / row_count) if row_count else 0.0
            output.append(
                {
                    "IdentityKey": voyage_identity_key(identity["Vessel"], identity["Voyage"], identity["BlockID"]),
                    **identity,
                    "SVC": profile.get("SVC"),
                    "ETD": etd,
                    "Days Before ETD": int(days),
                    "Checkpoint Timestamp": checkpoint,
                    "Known Containers": known_containers,
                    "Containers": known_containers if containers_complete else pd.NA,
                    "Known TEU": known_teu,
                    "TEU": known_teu if teu_complete else pd.NA,
                    "Containers Complete": containers_complete,
                    "TEU Complete": teu_complete,
                    "Complete": complete,
                    "History Completeness": completeness,
                    "Incomplete Rows": row_count - teu_complete_rows,
                    "Completeness Reason": "; ".join(sorted(set(incomplete_reasons))) if incomplete_reasons else "Complete from recorded transitions",
                }
            )
    return pd.DataFrame(output, columns=columns)


def forecast_readiness(
    weekly_df: pd.DataFrame,
    cargo_evolution_df: pd.DataFrame,
    context: FilterContext | None = None,
    *,
    minimum_comparable_voyages: int = 3,
    minimum_complete_checkpoints: int = 3,
) -> pd.DataFrame:
    profiles = voyage_load_profiles(weekly_df, context)
    columns = [
        "IdentityKey",
        "Vessel",
        "Voyage",
        "BlockID",
        "SVC",
        "Comparable Historical Voyages",
        "Complete Checkpoints",
        "Available Cargo-Development Checkpoints",
        "History Completeness",
        "Readiness Status",
        "Readiness Reason",
    ]
    if profiles.empty:
        return pd.DataFrame(columns=columns)
    output: list[dict[str, Any]] = []
    for _, profile in profiles.iterrows():
        identity_key = profile["IdentityKey"]
        curve = cargo_evolution_df[cargo_evolution_df.get("IdentityKey", pd.Series(dtype=object)).eq(identity_key)].copy()
        complete_curve = curve[curve.get("Complete", pd.Series(index=curve.index, dtype=bool)).fillna(False).astype(bool)]
        service = normalize_text(profile.get("SVC"))
        comparable_keys: set[str] = set()
        if not cargo_evolution_df.empty and "SVC" in cargo_evolution_df.columns:
            comparables = cargo_evolution_df[
                cargo_evolution_df["SVC"].map(normalize_text).eq(service)
                & cargo_evolution_df["Complete"].fillna(False).astype(bool)
                & ~cargo_evolution_df["IdentityKey"].eq(identity_key)
            ]
            comparable_keys = set(comparables["IdentityKey"].dropna().astype(str))
        complete_count = int(len(complete_curve))
        comparable_count = len(comparable_keys)
        expected = max(len(curve), len(DEFAULT_CHECKPOINTS))
        completeness = float(complete_count / expected) if expected else 0.0
        ready = comparable_count >= minimum_comparable_voyages and complete_count >= minimum_complete_checkpoints
        reason = (
            "Enough recorded checkpoints and comparable voyages for explainable method evaluation; no forecast is produced in Phase C."
            if ready
            else f"Needs at least {minimum_complete_checkpoints} complete checkpoints and {minimum_comparable_voyages} comparable historical voyages."
        )
        output.append(
            {
                "IdentityKey": identity_key,
                "Vessel": profile.get("Vessel"),
                "Voyage": profile.get("Voyage"),
                "BlockID": profile.get("BlockID"),
                "SVC": profile.get("SVC"),
                "Comparable Historical Voyages": comparable_count,
                "Complete Checkpoints": complete_count,
                "Available Cargo-Development Checkpoints": sorted(complete_curve.get("Days Before ETD", pd.Series(dtype=int)).astype(int).tolist(), reverse=True),
                "History Completeness": completeness,
                "Readiness Status": "Ready for method evaluation" if ready else "Insufficient history",
                "Readiness Reason": reason,
            }
        )
    return pd.DataFrame(output, columns=columns)


def _numeric_state_at(
    current_value: Any,
    history: pd.DataFrame,
    field: str,
    checkpoint: pd.Timestamp,
) -> tuple[float | None, bool, str | None]:
    current = _number(current_value)
    if pd.isna(checkpoint):
        return current, False, "Missing or invalid ETD"
    events = history[history.get("Field", pd.Series(index=history.index, dtype=object)).map(normalize_text) == normalize_text(field)].copy()
    if events.empty:
        return current, False, f"No {field} history"
    events["_timestamp"] = pd.to_datetime(events.get("Timestamp"), errors="coerce")
    events = events.sort_values("_timestamp", ascending=False, kind="mergesort")
    state = current
    for _, event in events[events["_timestamp"] > checkpoint].iterrows():
        raw_old = event.get("_raw_OldValue", event.get("OldValue"))
        if is_legacy_unavailable(raw_old):
            return state, False, f"Legacy unavailable {field} old value"
        if not is_meaningful_value(event.get("OldValue")):
            if is_meaningful_value(event.get("NewValue")):
                state = 0.0
                continue
            return state, False, f"Unavailable {field} transition"
        old = _number(event.get("OldValue"))
        if old is None:
            return state, False, f"Malformed {field} history"
        state = old
    return state, True, None


def _row_history(history: pd.DataFrame, row_id: Any) -> pd.DataFrame:
    if history.empty or "RowID" not in history.columns:
        return history.iloc[0:0].copy()
    return history[history["RowID"].map(normalize_text).eq(normalize_text(row_id))].copy()


def _match_identity(df: pd.DataFrame, identity: dict[str, Any]) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for column, value in identity.items():
        mask &= df[column].map(normalize_text).eq(normalize_text(value))
    return df[mask].copy()


def _number(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(numeric) else float(numeric)
