from __future__ import annotations

from typing import Any

import pandas as pd

from .date_utils import is_meaningful_value, normalize_text
from .operational_calculations import operational_mask
from .schema import HISTORY_VOYAGE_EVENT_KEY, LEGACY_UNAVAILABLE_VALUES


CURRENT_CONTEXT_FIELDS = (
    "Vessel",
    "Voyage",
    "BlockID",
    "Week",
    "Booking number",
    "CUSTOMER",
    "SVC",
    "POL",
    "POD",
    "ETA",
    "ETD",
    "Cut-Off",
)
IDENTITY_RESOLUTION_COLUMN = "Identity Resolution"
IDENTITY_RESOLVED = "Resolved"
IDENTITY_UNRESOLVED = "Unresolved"
IDENTITY_AMBIGUOUS = "Ambiguous"
IDENTITY_UNAVAILABLE = "Unavailable"


def is_legacy_unavailable(value: Any) -> bool:
    if not is_meaningful_value(value):
        return False
    return normalize_text(value) in {item.casefold() for item in LEGACY_UNAVAILABLE_VALUES}


def resolve_history_identities(history_df: pd.DataFrame, weekly_df: pd.DataFrame) -> pd.DataFrame:
    """Attach current logical-record context without replacing event context.

    RowID is used only to resolve one history row to one current operational
    record. Historical Vessel/Voyage/BlockID/Week values remain unchanged.
    Duplicate current operational RowIDs are marked ambiguous and are never
    guessed. Generated reservation rows are excluded from the current index.
    """

    result = history_df.copy()
    for field in CURRENT_CONTEXT_FIELDS:
        if field in result.columns and f"Historical {field}" not in result.columns:
            result[f"Historical {field}"] = result[field]
        if f"Current {field}" not in result.columns:
            result[f"Current {field}"] = pd.NA
    result[IDENTITY_RESOLUTION_COLUMN] = IDENTITY_UNAVAILABLE
    result["Current IdentityKey"] = pd.NA

    if result.empty or "RowID" not in result.columns or weekly_df.empty or "RowID" not in weekly_df.columns:
        meaningful = result.get("RowID", pd.Series(index=result.index, dtype=object)).map(is_meaningful_value)
        result.loc[meaningful, IDENTITY_RESOLUTION_COLUMN] = IDENTITY_UNRESOLVED
        return result

    current = weekly_df[operational_mask(weekly_df)].copy()
    current["_logical_row_id"] = current["RowID"].map(normalize_text)
    current = current[current["_logical_row_id"].ne("")].copy()
    counts = current["_logical_row_id"].value_counts()
    ambiguous_ids = set(counts[counts > 1].index)
    unique = current[~current["_logical_row_id"].isin(ambiguous_ids)].drop_duplicates("_logical_row_id", keep="first")
    current_by_row_id = unique.set_index("_logical_row_id", drop=False)

    logical_ids = result["RowID"].map(normalize_text)
    meaningful_ids = logical_ids.ne("")
    resolved_mask = meaningful_ids & logical_ids.isin(current_by_row_id.index)
    ambiguous_mask = meaningful_ids & logical_ids.isin(ambiguous_ids)
    unresolved_mask = meaningful_ids & ~(resolved_mask | ambiguous_mask)
    result.loc[resolved_mask, IDENTITY_RESOLUTION_COLUMN] = IDENTITY_RESOLVED
    result.loc[ambiguous_mask, IDENTITY_RESOLUTION_COLUMN] = IDENTITY_AMBIGUOUS
    result.loc[unresolved_mask, IDENTITY_RESOLUTION_COLUMN] = IDENTITY_UNRESOLVED

    for field in CURRENT_CONTEXT_FIELDS:
        if field not in current_by_row_id.columns:
            continue
        lookup = current_by_row_id[field].to_dict()
        mapped = logical_ids.map(lookup)
        result.loc[resolved_mask, f"Current {field}"] = mapped.loc[resolved_mask]

    for index in result.index[resolved_mask]:
        vessel = result.at[index, "Current Vessel"]
        voyage = result.at[index, "Current Voyage"]
        block_id = result.at[index, "Current BlockID"]
        if all(is_meaningful_value(value) for value in [vessel, voyage, block_id]):
            result.at[index, "Current IdentityKey"] = _voyage_identity_key(vessel, voyage, block_id)
    return result


def history_with_current_context(history_df: pd.DataFrame) -> pd.DataFrame:
    """Return an analytical view using current context when RowID resolved.

    Historical values remain available in ``Historical <field>`` columns. This
    view is for current voyage grouping and navigation; raw LOG_HISTORY remains
    authoritative and untouched in the loaded snapshot.
    """

    result = history_df.copy()
    if result.empty:
        return result
    for field in CURRENT_CONTEXT_FIELDS:
        current_column = f"Current {field}"
        if field not in result.columns or current_column not in result.columns:
            continue
        historical_column = f"Historical {field}"
        if historical_column not in result.columns:
            result[historical_column] = result[field]
        use_current = result.get(
            IDENTITY_RESOLUTION_COLUMN,
            pd.Series(IDENTITY_UNAVAILABLE, index=result.index),
        ).eq(IDENTITY_RESOLVED) & result[current_column].map(is_meaningful_value)
        historical_values = result[field].astype(object)
        current_values = result[current_column].astype(object)
        result[field] = historical_values.where(~use_current, current_values)
    return result


def match_history_to_current_identity(
    history_df: pd.DataFrame,
    *,
    vessel: Any,
    voyage: Any,
    block_id: Any,
) -> pd.DataFrame:
    """Match history to a current voyage identity without guessing ambiguity."""

    if history_df.empty:
        return history_df.copy()
    contextual = history_with_current_context(history_df)
    mask = pd.Series(True, index=contextual.index)
    for field, value in [("Vessel", vessel), ("Voyage", voyage), ("BlockID", block_id)]:
        if field not in contextual.columns:
            return contextual.iloc[0:0].copy()
        mask &= contextual[field].map(normalize_text).eq(normalize_text(value))
    if IDENTITY_RESOLUTION_COLUMN in contextual.columns:
        mask &= ~contextual[IDENTITY_RESOLUTION_COLUMN].eq(IDENTITY_AMBIGUOUS)
    return history_df.loc[mask].copy()


def effective_history_identity_key(row: pd.Series | dict[str, Any]) -> str | None:
    """Return current voyage identity when safely resolved, else event identity."""

    resolution = normalize_text(row.get(IDENTITY_RESOLUTION_COLUMN))
    if resolution == normalize_text(IDENTITY_AMBIGUOUS):
        return None
    if resolution == normalize_text(IDENTITY_RESOLVED):
        values = [row.get("Current Vessel"), row.get("Current Voyage"), row.get("Current BlockID")]
    else:
        values = [row.get("Vessel"), row.get("Voyage"), row.get("BlockID")]
    if not all(is_meaningful_value(value) for value in values):
        return None
    return _voyage_identity_key(*values)


def deduplicate_voyage_events(history_df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per identical voyage-level event while retaining provenance.

    Rows without a usable voyage identity or timestamp are not collapsed. Raw
    LOG_HISTORY remains available separately and is never modified here.
    """

    result = history_df.copy()
    result["_source_event_count"] = 1
    if result.empty or not all(column in result.columns for column in HISTORY_VOYAGE_EVENT_KEY):
        return result

    contextual = history_with_current_context(result)
    identity_columns = ["BlockID", "Vessel", "Voyage", "Field", "Timestamp"]
    complete_identity = pd.Series(True, index=result.index)
    for column in identity_columns:
        complete_identity &= contextual[column].map(is_meaningful_value)
    if IDENTITY_RESOLUTION_COLUMN in result.columns:
        complete_identity &= ~result[IDENTITY_RESOLUTION_COLUMN].eq(IDENTITY_AMBIGUOUS)

    complete = result[complete_identity].copy()
    incomplete = result[~complete_identity].copy()
    if complete.empty:
        return result

    complete_context = contextual.loc[complete.index]
    complete["_dedupe_block_id"] = complete_context["BlockID"].map(normalize_text)
    complete["_dedupe_vessel"] = complete_context["Vessel"].map(normalize_text)
    complete["_dedupe_voyage"] = complete_context["Voyage"].map(normalize_text)
    complete["_dedupe_old_value"] = _dedupe_value_series(complete, "OldValue")
    complete["_dedupe_new_value"] = _dedupe_value_series(complete, "NewValue")
    key = [
        "_dedupe_block_id",
        "_dedupe_vessel",
        "_dedupe_voyage",
        "Field",
        "Timestamp",
        "_dedupe_old_value",
        "_dedupe_new_value",
    ]
    complete["_source_event_count"] = complete.groupby(key, dropna=False)["Field"].transform("size")
    complete = complete.drop_duplicates(key, keep="first")
    complete = complete.drop(
        columns=[
            "_dedupe_block_id",
            "_dedupe_vessel",
            "_dedupe_voyage",
            "_dedupe_old_value",
            "_dedupe_new_value",
        ]
    )

    combined = pd.concat([complete, incomplete], axis=0).sort_index(kind="mergesort")
    return combined.reset_index(drop=True)


def _dedupe_value_series(df: pd.DataFrame, column: str) -> pd.Series:
    raw_column = f"_raw_{column}"
    source = df[raw_column] if raw_column in df.columns else df[column]

    def key(value: Any) -> str:
        if is_legacy_unavailable(value):
            return "<legacy-unavailable>"
        if not is_meaningful_value(value):
            return "<blank>"
        return normalize_text(value)

    return source.map(key)


def _voyage_identity_key(vessel: Any, voyage: Any, block_id: Any) -> str:
    return "||".join(normalize_text(value) for value in [vessel, voyage, block_id])
