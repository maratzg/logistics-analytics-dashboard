from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any

import pandas as pd

from src.analytical_filters import FilterContext, apply_current_filters, eta_period_columns
from src.date_utils import is_meaningful_value, normalize_text


ALL_FILTER_VALUE = "All"


@dataclass(frozen=True, slots=True)
class FilterSpec:
    key: str
    label: str
    context_attribute: str
    dataframe_column: str
    primary: bool = False


FILTER_SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("vessel", "Vessel", "vessel", "Vessel", True),
    FilterSpec("voyage", "Voyage", "voyage", "Voyage", True),
    FilterSpec("week", "Week", "week", "Week", True),
    FilterSpec("eta_month", "ETA Month", "eta_month", "ETA Month", True),
    FilterSpec("eta_year", "ETA Year", "eta_year", "ETA Year"),
    FilterSpec("svc", "SVC", "svc", "SVC"),
    FilterSpec("pol", "POL", "pol", "POL"),
    FilterSpec("pod", "POD", "pod", "POD"),
    FilterSpec("customer", "Customer", "customer", "CUSTOMER"),
    FilterSpec("load_status", "LoadStatus", "load_status", "LoadStatus"),
    FilterSpec("row_status", "RowStatus", "row_status", "RowStatus"),
)


class FilterSelectionState:
    """Toolkit-independent global filter state backed by Phase C FilterContext."""

    def __init__(self, context: FilterContext | None = None) -> None:
        self._values = {item.name: getattr(context or FilterContext(), item.name) for item in fields(FilterContext)}

    @property
    def active_count(self) -> int:
        return sum(value is not None for value in self._values.values())

    @property
    def is_active(self) -> bool:
        return self.active_count > 0

    def value(self, key: str) -> Any | None:
        spec = filter_spec(key)
        return self._values[spec.context_attribute]

    def set_value(self, key: str, value: Any | None) -> None:
        spec = filter_spec(key)
        self._values[spec.context_attribute] = _selection_value(value)

    def reset(self) -> None:
        for key in self._values:
            self._values[key] = None

    def to_context(self) -> FilterContext:
        return FilterContext(**self._values)

    def reconcile(self, options: dict[str, list[str]]) -> bool:
        changed = False
        for spec in FILTER_SPECS:
            selected = self.value(spec.key)
            if selected is None:
                continue
            allowed = {normalize_text(value) for value in options.get(spec.key, []) if value != ALL_FILTER_VALUE}
            if normalize_text(selected) not in allowed:
                self._values[spec.context_attribute] = None
                changed = True
        return changed


def filter_spec(key: str) -> FilterSpec:
    for spec in FILTER_SPECS:
        if spec.key == key:
            return spec
    raise KeyError(f"Unknown analytical filter: {key}")


def faceted_filter_options(df: pd.DataFrame, selection: FilterSelectionState | FilterContext | None = None) -> dict[str, list[str]]:
    """Build cascading options with every facet excluding its own selection."""

    context = selection.to_context() if isinstance(selection, FilterSelectionState) else selection or FilterContext()
    options: dict[str, list[str]] = {}
    for spec in FILTER_SPECS:
        facet_context = replace(context, **{spec.context_attribute: None})
        filtered = eta_period_columns(apply_current_filters(df, facet_context))
        values = filtered.get(spec.dataframe_column, pd.Series(dtype=object))
        if spec.key == "row_status":
            values = values.map(lambda value: value if is_meaningful_value(value) else "Active")
        options[spec.key] = [ALL_FILTER_VALUE] + _display_values(values)
    return options


def filtered_current_rows(df: pd.DataFrame, selection: FilterSelectionState | FilterContext | None = None) -> pd.DataFrame:
    context = selection.to_context() if isinstance(selection, FilterSelectionState) else selection
    return apply_current_filters(df, context)


def _selection_value(value: Any | None) -> Any | None:
    if value is None or normalize_text(value) in {"", normalize_text(ALL_FILTER_VALUE)}:
        return None
    return value


def _display_values(values: pd.Series) -> list[str]:
    unique: dict[str, str] = {}
    for value in values.tolist():
        if not is_meaningful_value(value):
            continue
        if isinstance(value, float) and value.is_integer():
            display = str(int(value))
        else:
            display = str(value).strip()
        if display and normalize_text(display) != "unknown":
            unique.setdefault(normalize_text(display), display)
        elif normalize_text(display) == "unknown":
            unique.setdefault("unknown", "Unknown")
    return sorted(unique.values(), key=_sort_key)


def _sort_key(value: str) -> tuple[int, float | str]:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if not pd.isna(numeric):
        return (0, float(numeric))
    return (1, normalize_text(value))
