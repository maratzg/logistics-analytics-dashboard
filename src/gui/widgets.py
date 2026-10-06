from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from tkinter import ttk

from .theme import FONT_FAMILY, PALETTE


def configure_treeview_style() -> None:
    style = ttk.Style()
    try:
        style.theme_use("default")
    except Exception:
        pass
    style.configure(
        "HistoryDashboard.Treeview",
        background=PALETTE.table_even,
        foreground=PALETTE.text,
        fieldbackground=PALETTE.table_even,
        borderwidth=0,
        rowheight=32,
        font=(FONT_FAMILY, 11),
    )
    style.configure(
        "HistoryDashboard.Treeview.Heading",
        background=PALETTE.table_header,
        foreground=PALETTE.text,
        bordercolor=PALETTE.border,
        relief="flat",
        borderwidth=1,
        padding=(8, 7),
        font=(FONT_FAMILY, 10, "bold"),
    )
    style.map(
        "HistoryDashboard.Treeview",
        background=[("selected", PALETTE.table_selected)],
        foreground=[("selected", PALETTE.text)],
    )
    style.map("HistoryDashboard.Treeview.Heading", background=[("active", PALETTE.selected)])


def create_treeview(parent: Any, columns: list[str], *, height: int = 10) -> tuple[ttk.Treeview, ttk.Scrollbar, ttk.Scrollbar]:
    tree = ttk.Treeview(
        parent,
        columns=columns,
        show="headings",
        height=height,
        style="HistoryDashboard.Treeview",
    )
    vertical = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    for column in columns:
        tree.heading(column, text=column)
        tree.column(column, width=_default_width(column), minwidth=70, stretch=True, anchor=_column_anchor(column))
    tree.tag_configure("even", background=PALETTE.table_even)
    tree.tag_configure("odd", background=PALETTE.table_odd)
    return tree, vertical, horizontal


def populate_treeview(tree: ttk.Treeview, frame: pd.DataFrame) -> None:
    clear_treeview(tree)
    if frame.empty:
        return
    for index, (_, row) in enumerate(frame.iterrows()):
        values = [format_cell_value(row.get(column)) for column in tree["columns"]]
        tree.insert("", "end", values=values, tags=("even" if index % 2 == 0 else "odd",))


def clear_treeview(tree: ttk.Treeview) -> None:
    for item in tree.get_children():
        tree.delete(item)


def format_cell_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        if value.time() == datetime.min.time():
            return value.strftime("%d.%m.%Y")
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, datetime):
        if value.time() == datetime.min.time():
            return value.strftime("%d.%m.%Y")
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def format_number(value: float | int | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{float(value):,.2f}"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Never"
    return value.strftime("%d.%m.%Y %H:%M")


def format_movement_days(value: float | None) -> str:
    if value is None:
        return "Unknown"
    if value == 0:
        return "No movement"
    abs_value = abs(value)
    amount = f"{int(abs_value)}" if float(abs_value).is_integer() else f"{abs_value:.1f}"
    direction = "later" if value > 0 else "earlier"
    sign = "+" if value > 0 else "-"
    return f"{sign}{amount} days {direction}"


def set_combo_values(combo: Any, values: list[str], *, selected: str = "All") -> None:
    safe_values = values or ["All"]
    combo.configure(values=safe_values)
    combo.set(selected if selected in safe_values else safe_values[0])


def _default_width(column: str) -> int:
    widths = {
        "Timestamp": 145,
        "User": 120,
        "Vessel": 170,
        "Voyage": 100,
        "Booking number": 140,
        "Field": 100,
        "OldValue": 160,
        "NewValue": 160,
        "Week": 70,
        "RowID": 150,
        "BlockID": 120,
        "Events": 90,
        "ETA revisions": 110,
    }
    return widths.get(column, 120)


def _column_anchor(column: str) -> str:
    normalized = column.strip().casefold()
    numeric_hints = ("count", "containers", "teu", "gwt", "%", "ratio", "movement", "revisions", "week", "rows", "summary", "ts")
    return "e" if any(hint in normalized for hint in numeric_hints) else "w"
