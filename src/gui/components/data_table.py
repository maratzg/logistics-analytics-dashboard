from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import customtkinter as ctk
import pandas as pd
from tkinter import ttk

from ..theme import CARD_RADIUS, PALETTE, SPACING, font
from ..widgets import format_cell_value


NUMERIC_HINTS = ("count", "containers", "teu", "gwt", "%", "ratio", "movement", "revisions", "week", "rows")


def column_alignment(column: str, series: pd.Series | None = None) -> str:
    if series is not None and pd.api.types.is_numeric_dtype(series):
        return "e"
    normalized = column.strip().casefold()
    return "e" if any(hint in normalized for hint in NUMERIC_HINTS) else "w"


def column_width(column: str) -> int:
    normalized = column.strip().casefold()
    if "timestamp" in normalized or "date" in normalized:
        return 142
    if column in {"Vessel", "CUSTOMER", "Customer", "POD", "POL"}:
        return 150
    if column in {"RowID", "BlockID", "Booking number", "IdentityKey"}:
        return 165
    if any(hint in normalized for hint in NUMERIC_HINTS):
        return 112
    return max(96, min(180, len(column) * 8 + 28))


def sort_dataframe(frame: pd.DataFrame, column: str, *, ascending: bool = True) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame.copy()
    values = frame[column]
    numeric = pd.to_numeric(values, errors="coerce")
    working = frame.copy()
    sort_column = "_table_sort_value"
    working[sort_column] = numeric if numeric.notna().sum() == values.notna().sum() else values.map(lambda value: str(value).casefold())
    return working.sort_values(sort_column, ascending=ascending, na_position="last", kind="mergesort").drop(columns=sort_column).reset_index(drop=True)


class DataTable(ctk.CTkFrame):
    def __init__(
        self,
        parent: Any,
        *,
        empty_message: str = "No records match the current filters.",
        height: int = 11,
        visible_columns: Iterable[str] | None = None,
        formatters: dict[str, Callable[[Any], str]] | None = None,
        sort_keys: dict[str, str] | None = None,
        on_select: Callable[[pd.Series | None], None] | None = None,
        on_activate: Callable[[pd.Series], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=CARD_RADIUS)
        self.empty_message = empty_message
        self.height = height
        self.frame = pd.DataFrame()
        self.visible_columns = list(visible_columns) if visible_columns is not None else None
        self.formatters = formatters or {}
        self.sort_keys = sort_keys or {}
        self.on_select = on_select
        self.on_activate = on_activate
        self.sort_column: str | None = None
        self.sort_ascending = True
        self.tree: ttk.Treeview | None = None
        self.empty_label: ctk.CTkLabel | None = None
        self._row_map: dict[str, pd.Series] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

    def set_dataframe(self, frame: pd.DataFrame) -> None:
        self.frame = frame.copy()
        self._render()

    def selected_values(self) -> tuple[Any, ...] | None:
        if self.tree is None:
            return None
        selection = self.tree.selection()
        return tuple(self.tree.item(selection[0], "values")) if selection else None

    def selected_row(self) -> pd.Series | None:
        if self.tree is None:
            return None
        selection = self.tree.selection()
        return self._row_map.get(selection[0]).copy() if selection and selection[0] in self._row_map else None

    def _render(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self.tree = None
        self._row_map.clear()
        if self.frame.empty:
            self.empty_label = ctk.CTkLabel(self, text=self.empty_message, text_color=PALETTE.text_muted, font=font(12))
            self.empty_label.grid(row=0, column=0, sticky="ew", padx=SPACING.lg, pady=SPACING.xl)
            return

        columns = [column for column in (self.visible_columns or list(self.frame.columns)) if column in self.frame.columns]
        tree = ttk.Treeview(self, columns=columns, show="headings", height=self.height, style="HistoryDashboard.Treeview", selectmode="browse")
        vertical = ttk.Scrollbar(self, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for column in columns:
            next_direction = not self.sort_ascending if self.sort_column == column else True
            marker = " ▲" if self.sort_column == column and self.sort_ascending else (" ▼" if self.sort_column == column else "")
            tree.heading(column, text=f"{column}{marker}", command=lambda selected=column, asc=next_direction: self._sort(selected, asc))
            tree.column(column, width=column_width(column), minwidth=72, anchor=column_alignment(column, self.frame[column]), stretch=True)
        tree.tag_configure("even", background=PALETTE.table_even)
        tree.tag_configure("odd", background=PALETTE.table_odd)
        tree.tag_configure("cancelled", background=PALETTE.danger_soft, foreground=PALETTE.danger)
        for index, (_, row) in enumerate(self.frame.iterrows()):
            iid = f"row-{index}"
            values = [self._format_value(column, row.get(column)) for column in columns]
            status = str(row.get("RowStatus", "")).strip().casefold()
            tags = ("cancelled",) if status == "cancelled" else ("even" if index % 2 == 0 else "odd",)
            tree.insert("", "end", iid=iid, values=values, tags=tags)
            self._row_map[iid] = row.copy()
        tree.bind("<<TreeviewSelect>>", self._selected)
        tree.bind("<Double-1>", self._activated)
        tree.grid(row=0, column=0, sticky="nsew", padx=(SPACING.sm, 0), pady=(SPACING.sm, 0))
        vertical.grid(row=0, column=1, sticky="ns", padx=(0, SPACING.sm), pady=(SPACING.sm, 0))
        horizontal.grid(row=1, column=0, sticky="ew", padx=SPACING.sm, pady=(0, SPACING.sm))
        self.tree = tree

    def _sort(self, column: str, ascending: bool) -> None:
        self.sort_column = column
        self.sort_ascending = ascending
        self.frame = sort_dataframe(self.frame, self.sort_keys.get(column, column), ascending=ascending)
        self._render()

    def _format_value(self, column: str, value: Any) -> str:
        formatter = self.formatters.get(column)
        return formatter(value) if formatter is not None else format_cell_value(value)

    def _selected(self, *_: Any) -> None:
        if self.on_select is not None:
            self.on_select(self.selected_row())

    def _activated(self, *_: Any) -> None:
        selected = self.selected_row()
        if selected is not None and self.on_activate is not None:
            self.on_activate(selected)
