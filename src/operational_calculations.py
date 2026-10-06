from __future__ import annotations

from typing import Any

import pandas as pd

from .date_utils import is_meaningful_value
from .schema import ANALYTICAL_ONLY_COLUMNS, CALCULATED_COLUMNS, EXPECTED_WEEKLY_COLUMNS, OPERATIONAL_PAYLOAD_COLUMNS


LOAD_CLASS_LOADED = "Loaded"
LOAD_CLASS_EMPTY = "Empty"
LOAD_CLASS_UNKNOWN = "Unknown"


def ensure_weekly_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy containing every canonical V2 column in workbook order."""

    result = df.copy()
    for column in EXPECTED_WEEKLY_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    ordered = list(EXPECTED_WEEKLY_COLUMNS)
    ordered.extend(column for column in result.columns if column not in ordered)
    return result[ordered]


def normalize_load_status(value: Any) -> str:
    """Apply the V2 compatibility rule: blank means Loaded."""

    if not is_meaningful_value(value):
        return LOAD_CLASS_LOADED
    normalized = str(value).replace("\xa0", " ").strip().casefold()
    if normalized == "loaded":
        return LOAD_CLASS_LOADED
    if normalized == "empty":
        return LOAD_CLASS_EMPTY
    return LOAD_CLASS_UNKNOWN


def recalculate_operational_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate every workbook-derived quantity from normalized source inputs.

    Excel formula cache values are deliberately not used by this function.
    Unknown LoadStatus values remain in total quantities but receive no
    loaded/empty allocation and should be surfaced by validation.
    """

    result = ensure_weekly_schema(df)
    index = result.index
    amount = _numeric(result, "CNTR AMT")
    size = _numeric(result, "SIZE")
    gwt = _numeric(result, "GWT")
    cancelled = cancelled_mask(result)
    active = ~cancelled
    loaded = active & result["LoadStatus"].eq(LOAD_CLASS_LOADED)
    empty = active & result["LoadStatus"].eq(LOAD_CLASS_EMPTY)
    size_20 = size.eq(2)
    size_40 = size.eq(4)
    teu_factor = pd.Series(0.0, index=index)
    teu_factor.loc[size_20] = 1.0
    teu_factor.loc[size_40] = 2.0

    result["Summary"] = amount.where(active, 0.0)
    result["TEU"] = (amount * teu_factor).where(active, 0.0)
    result["TS"] = gwt.where(active, 0.0)

    result["Loaded Containers"] = amount.where(loaded, 0.0)
    result["Empty Containers"] = amount.where(empty, 0.0)
    result["Unclassified Containers"] = amount.where(active & ~(loaded | empty), 0.0)
    result["Total Containers"] = amount.where(active, 0.0)

    result["Loaded 20ft"] = amount.where(loaded & size_20, 0.0)
    result["Empty 20ft"] = amount.where(empty & size_20, 0.0)
    result["Total 20ft"] = amount.where(active & size_20, 0.0)
    result["Loaded 40ft"] = amount.where(loaded & size_40, 0.0)
    result["Empty 40ft"] = amount.where(empty & size_40, 0.0)
    result["Total 40ft"] = amount.where(active & size_40, 0.0)

    calculated_teu = amount * teu_factor
    result["Loaded TEU"] = calculated_teu.where(loaded, 0.0)
    result["Empty TEU"] = calculated_teu.where(empty, 0.0)
    result["Unclassified TEU"] = calculated_teu.where(active & ~(loaded | empty), 0.0)
    result["Total TEU"] = calculated_teu.where(active, 0.0)

    result["Loaded GWT"] = gwt.where(loaded, 0.0)
    result["Empty GWT"] = gwt.where(empty, 0.0)
    result["Unclassified GWT"] = gwt.where(active & ~(loaded | empty), 0.0)
    result["Total GWT"] = gwt.where(active, 0.0)

    for column in CALCULATED_COLUMNS + ANALYTICAL_ONLY_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)
    return result


def operational_mask(df: pd.DataFrame) -> pd.Series:
    """Analytical rows have a stable identity and actual shipment payload."""

    return identity_row_mask(df) & operational_payload_mask(df)


def identity_row_mask(df: pd.DataFrame) -> pd.Series:
    """Stable row identity is a nonblank opaque RowID; its format has no meaning."""

    if "RowID" not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    return df["RowID"].map(is_meaningful_value).astype(bool)


def operational_payload_mask(df: pd.DataFrame) -> pd.Series:
    """Exclude generated rows, while retaining explicitly cancelled records."""

    mask = pd.Series(False, index=df.index, dtype=bool)
    for column in OPERATIONAL_PAYLOAD_COLUMNS:
        if column in df.columns:
            mask |= df[column].map(is_meaningful_value).fillna(False).astype(bool)
    if "RowStatus" in df.columns:
        mask |= cancelled_mask(df)
    if "CancelReason" in df.columns:
        mask |= df["CancelReason"].map(is_meaningful_value).fillna(False).astype(bool)
    return mask


def cancelled_mask(df: pd.DataFrame) -> pd.Series:
    if "RowStatus" not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    return df["RowStatus"].astype(str).str.strip().str.casefold().eq("cancelled")


def active_operational_mask(df: pd.DataFrame) -> pd.Series:
    return operational_mask(df) & ~cancelled_mask(df)


def eta_year_series(eta_values: pd.Series) -> pd.Series:
    """Expose ETA Year explicitly; it is not an authoritative operational year."""

    parsed = pd.to_datetime(eta_values, errors="coerce")
    values = pd.Series("Unknown", index=eta_values.index, dtype=object)
    valid = parsed.notna()
    values.loc[valid] = parsed.loc[valid].dt.year.astype(int)
    return values


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[column], errors="coerce").fillna(0.0)
