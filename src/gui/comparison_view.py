from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
import pandas as pd

from src.analytical_filters import FilterContext
from src.app_state import ApplicationState

from .components.chart_card import ChartCard
from .components.data_table import DataTable
from .components.empty_state import StatePanel
from .components.layout import SectionHeader
from .exporting import export_visible_csv
from .presentation import format_movement, format_number, format_percentage
from .theme import PALETTE, SPACING, font


NOT_SELECTED = "Not selected"
COMPARISON_COLUMNS = [
    "Label", "Total Containers", "Loaded Containers", "Empty Containers", "Loaded %", "Empty %", "Total 20ft", "Total 40ft",
    "Total TEU", "Loaded TEU", "Empty TEU", "Total GWT", "Loaded GWT", "Empty GWT",
    "GWT / Loaded TEU", "ETA Revision Count", "Net ETA Movement", "Cumulative ETA Movement",
    "Largest ETA Revision", "Week Change Count", "Cancellations",
]


class ComparisonView(ctk.CTkFrame):
    """Side-by-side comparison of two to five safely identified voyage instances."""

    def __init__(
        self,
        parent: Any,
        state: ApplicationState,
        *,
        on_open_voyage: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app_state = state
        self.on_open_voyage = on_open_voyage
        self.filter_context = FilterContext()
        self.selectors: list[ctk.CTkComboBox] = []
        self.label_to_key: dict[str, str] = {}
        self.current_rows = pd.DataFrame()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        SectionHeader(self, "Voyage-instance comparison", "Select 2–5 voyages. Vessel, Voyage, and opaque BlockID remain the safe internal identity.").grid(
            row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.md, SPACING.sm)
        )
        controls = ctk.CTkFrame(self, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=10)
        controls.grid(row=1, column=0, sticky="ew", padx=SPACING.xl, pady=(0, SPACING.md))
        for column in range(3):
            controls.grid_columnconfigure(column, weight=1)
        for index in range(5):
            host = ctk.CTkFrame(controls, fg_color="transparent")
            host.grid(row=index // 3, column=index % 3, sticky="ew", padx=SPACING.md, pady=SPACING.sm)
            host.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(host, text=f"Voyage {index + 1}", text_color=PALETTE.text_muted, font=font(10), anchor="w").grid(row=0, column=0, sticky="ew")
            selector = ctk.CTkComboBox(host, values=[NOT_SELECTED], command=lambda _value: self._render_selected())
            selector.set(NOT_SELECTED)
            selector.grid(row=1, column=0, sticky="ew", pady=(SPACING.xs, 0))
            self.selectors.append(selector)
        actions = ctk.CTkFrame(controls, fg_color="transparent")
        actions.grid(row=1, column=2, sticky="e", padx=SPACING.md, pady=SPACING.md)
        self.open_button = ctk.CTkButton(actions, text="Open selected row", command=self._open_selected, state="disabled", width=138)
        self.open_button.pack(side="left", padx=(0, SPACING.sm))
        ctk.CTkButton(actions, text="Export", command=self._export, width=88, fg_color=PALETTE.surface_subtle,
                      hover_color=PALETTE.accent_soft, text_color=PALETTE.text).pack(side="left")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.xl))
        self.body.grid_columnconfigure(0, weight=1)

    def set_filter_context(self, context: FilterContext) -> None:
        self.filter_context = context

    def refresh_view(self) -> None:
        model = self.app_state.comparison_page_model()
        self.label_to_key = dict(zip(model.candidates.get("Label", []), model.candidates.get("IdentityKey", []), strict=False))
        values = [NOT_SELECTED] + list(self.label_to_key)
        for selector in self.selectors:
            current = selector.get()
            selector.configure(values=values)
            selector.set(current if current in values else NOT_SELECTED)
        self._render_selected()

    def _selected_keys(self) -> list[str]:
        return [self.label_to_key[label] for label in (selector.get() for selector in self.selectors) if label in self.label_to_key]

    def _render_selected(self) -> None:
        _clear(self.body)
        model = self.app_state.comparison_page_model(self._selected_keys())
        self.current_rows = model.rows
        if model.error_message or model.empty_message:
            StatePanel(
                self.body,
                "Comparison needs attention" if model.error_message else "Choose voyage instances",
                model.error_message or model.empty_message or "Select voyages to compare.",
                kind="warning" if model.error_message else "information",
            ).grid(row=0, column=0, sticky="ew")
            self.open_button.configure(state="disabled")
            return

        SectionHeader(self.body, "Comparison matrix", "Unavailable history remains explicit and is never converted to zero.").grid(
            row=0, column=0, sticky="ew", pady=(SPACING.sm, SPACING.md)
        )
        self.table = DataTable(
            self.body,
            visible_columns=COMPARISON_COLUMNS,
            height=min(7, max(3, len(model.rows))),
            formatters={
                "Loaded %": format_percentage,
                "Empty %": format_percentage,
                "Net ETA Movement": format_movement,
                "Cumulative ETA Movement": format_movement,
                "Largest ETA Revision": format_movement,
                "Total GWT": lambda value: format_number(value, decimals=1),
                "Loaded GWT": lambda value: format_number(value, decimals=1),
                "Empty GWT": lambda value: format_number(value, decimals=1),
            },
            on_select=self._row_selected,
            on_activate=self._open_row,
        )
        self.table.grid(row=1, column=0, sticky="ew")
        self.table.set_dataframe(model.rows)
        self._charts(model.rows, 2)

    def _charts(self, rows: pd.DataFrame, row_index: int) -> None:
        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.grid(row=row_index, column=0, sticky="ew", pady=(SPACING.lg, 0))
        for column in range(2):
            grid.grid_columnconfigure(column, weight=1, uniform="comparison")
        volume = ChartCard(grid, "Containers and TEU", "Two operational volume measures; no winner is declared.")
        volume.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.xs))
        _grouped_chart(volume, rows, ["Total Containers", "Total TEU"])
        mix = ChartCard(grid, "Loaded and Empty", "Current classified container quantities.")
        mix.grid(row=0, column=1, sticky="nsew", padx=(SPACING.xs, 0))
        _grouped_chart(mix, rows, ["Loaded Containers", "Empty Containers"])

    def _row_selected(self, row: pd.Series | None) -> None:
        enabled = row is not None and bool(str(row.get("IdentityKey", "")))
        self.open_button.configure(state="normal" if enabled else "disabled")

    def _open_selected(self) -> None:
        row = self.table.selected_row() if hasattr(self, "table") else None
        if row is not None:
            self._open_row(row)

    def _open_row(self, row: pd.Series) -> None:
        identity = str(row.get("IdentityKey", ""))
        if identity and self.on_open_voyage is not None:
            self.on_open_voyage(identity)

    def _export(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="Export comparison", initialfile="voyage_comparison.csv", defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        result = export_visible_csv(self.current_rows, Path(path), visible_columns=COMPARISON_COLUMNS)
        if result.success:
            messagebox.showinfo("Export complete", result.message, parent=self)
        else:
            messagebox.showwarning("Nothing to export", result.message, parent=self)


def _grouped_chart(card: ChartCard, rows: pd.DataFrame, metrics: list[str]) -> None:
    if rows.empty or not all(metric in rows.columns for metric in metrics):
        card.show_empty("No comparison values are available.")
        return
    figure = card.new_figure(height=3.1)
    axis = figure.add_subplot(111)
    ChartCard.style_axis(axis)
    positions = list(range(len(rows)))
    width = 0.36
    colors = [PALETTE.accent, "#8AA4B0"]
    for index, metric in enumerate(metrics):
        x = [position + (index - 0.5) * width for position in positions]
        axis.bar(x, pd.to_numeric(rows[metric], errors="coerce").fillna(0), width=width, label=metric, color=colors[index])
    short_labels = [f"{row.get('Vessel', '—')} · {row.get('Voyage', '—')}" for _, row in rows.iterrows()]
    axis.set_xticks(positions, short_labels, rotation=20, ha="right")
    axis.legend(facecolor=PALETTE.surface, edgecolor=PALETTE.border, labelcolor=PALETTE.text_muted)
    card.show_figure(figure)


def _clear(parent: Any) -> None:
    for child in parent.winfo_children():
        child.destroy()
