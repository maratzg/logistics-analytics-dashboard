from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk
import pandas as pd

from src.app_state import ApplicationState

from .components.chart_card import ChartCard
from .components.data_table import DataTable
from .components.empty_state import StatePanel
from .components.kpi_card import KpiCard
from .components.layout import SectionHeader
from .presentation import format_date, format_movement, format_number, format_percentage
from .theme import PALETTE, SPACING, font


VOYAGE_COLUMNS = [
    "Vessel", "Voyage", "Week", "ETA", "ETD", "POL", "POD", "SVC",
    "Total Containers", "Loaded Containers", "Empty Containers", "Total TEU",
    "Total GWT", "ETA Revision Count", "Net ETA Movement", "Week Change Count",
    "Cancelled rows", "Attention",
]
BOOKING_COLUMNS = [
    "Booking number", "Customer", "CNTR AMT", "SIZE", "TYPE", "LoadStatus",
    "GWT", "POD", "Booking status", "RowStatus", "CancelReason",
]
TIMELINE_COLUMNS = ["Timestamp", "Field", "Old Value", "New Value", "Booking number", "User", "Raw Events"]


class VoyageView(ctk.CTkFrame):
    """Phase E voyage browser and safe-composite-identity detail experience."""

    def __init__(
        self,
        parent: Any,
        state: ApplicationState,
        *,
        on_context_change: Callable[[str, str], None] | None = None,
        on_navigate: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app_state = state
        self.on_context_change = on_context_change
        self.on_navigate = on_navigate
        self.selected_identity_key: str | None = None
        self.return_route: str | None = None
        self.detail_open = False
        self.timeline_mode = "grouped"
        self.open_button: ctk.CTkButton | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=0, column=0, sticky="nsew", padx=SPACING.xl, pady=(SPACING.md, SPACING.xl))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(1, weight=1)

    def refresh_view(self) -> None:
        if self.detail_open and self.selected_identity_key:
            self._render_detail()
        else:
            self._render_browser()

    def open_identity(self, identity_key: str, *, return_route: str | None = None) -> None:
        self.selected_identity_key = identity_key
        self.return_route = return_route
        self.detail_open = True
        self._render_detail()

    def _render_browser(self) -> None:
        self.detail_open = False
        self.return_route = None
        if self.on_context_change is not None:
            self.on_context_change("Voyages", "Browse complete voyage instances and operational details.")
        _clear_frame(self.body)
        self.body.grid_rowconfigure(1, weight=1)
        model = self.app_state.voyage_browser_model()

        toolbar = ctk.CTkFrame(self.body, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, SPACING.md))
        toolbar.grid_columnconfigure(0, weight=1)
        subtitle = "Select a safely identified voyage instance, then double-click or choose Open voyage."
        SectionHeader(toolbar, "Current voyage instances", subtitle).grid(row=0, column=0, sticky="ew")
        self.open_button = ctk.CTkButton(
            toolbar,
            text="Open voyage",
            command=self._open_selected,
            state="disabled",
            width=118,
            fg_color=PALETTE.accent,
            hover_color=PALETTE.accent_hover,
        )
        self.open_button.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(toolbar, text=f"{model.voyage_count} voyage instance{'s' if model.voyage_count != 1 else ''}", text_color=PALETTE.text_muted, font=font(10)).grid(
            row=1, column=0, sticky="w", pady=(SPACING.xs, 0)
        )

        table = DataTable(
            self.body,
            empty_message=model.empty_message or "No voyages match the shared filters.",
            height=20,
            visible_columns=VOYAGE_COLUMNS,
            formatters={
                "ETA": format_date,
                "ETD": format_date,
                "Net ETA Movement": format_movement,
                "Total GWT": lambda value: format_number(value, decimals=1),
            },
            on_select=self._selected,
            on_activate=self._activated,
        )
        table.grid(row=1, column=0, sticky="nsew")
        table.set_dataframe(model.rows)
        self.voyage_table = table

    def _selected(self, row: pd.Series | None) -> None:
        self.selected_identity_key = str(row.get("IdentityKey")) if row is not None else None
        if self.open_button is not None:
            self.open_button.configure(state="normal" if self.selected_identity_key else "disabled")

    def _activated(self, row: pd.Series) -> None:
        identity_key = str(row.get("IdentityKey", ""))
        if identity_key:
            self.open_identity(identity_key)

    def _open_selected(self) -> None:
        if self.selected_identity_key:
            self.open_identity(self.selected_identity_key)

    def _render_detail(self) -> None:
        _clear_frame(self.body)
        self.body.grid_rowconfigure(1, weight=1)
        model = self.app_state.voyage_detail_model(self.selected_identity_key or "")

        header = ctk.CTkFrame(self.body, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING.md))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            header,
            text=f"← Back to {self.return_route or 'Voyages'}",
            command=self._back_to_browser,
            width=132,
            fg_color="transparent",
            text_color=PALETTE.accent,
            hover_color=PALETTE.accent_soft,
            border_width=1,
            border_color=PALETTE.border,
        ).grid(row=0, column=0, sticky="w", padx=(0, SPACING.md))

        if not model.available:
            StatePanel(
                self.body,
                "Voyage unavailable",
                model.empty_message or "The selected voyage is no longer available.",
                kind="warning",
            ).grid(row=1, column=0, sticky="ew")
            return

        if self.on_context_change is not None:
            self.on_context_change("Voyage Detail", f"Current schedule, cargo, bookings, and changes for {model.vessel} · {model.voyage}.")

        title = ctk.CTkFrame(header, fg_color="transparent")
        title.grid(row=0, column=1, sticky="ew")
        title.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title, text=f"{model.vessel} · {model.voyage}", text_color=PALETTE.text, font=font(22, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew")
        context = f"Week {model.week} · {model.svc} · {model.route} · ETA {model.eta} · ETD {model.etd} · Cut-Off {model.cut_off}"
        ctk.CTkLabel(title, text=context, text_color=PALETTE.text_muted, font=font(11), anchor="w").grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ctk.CTkLabel(header, text=f"Technical ID: {model.block_id}", text_color=PALETTE.text_soft, font=font(9), anchor="e").grid(row=0, column=2, sticky="e")

        scroll = ctk.CTkScrollableFrame(self.body, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        row_index = self._detail_kpis(scroll, 0, model)
        row_index = self._schedule(scroll, row_index, model)
        row_index = self._cargo_charts(scroll, row_index, model)
        row_index = self._bookings(scroll, row_index, model)
        row_index = self._timeline(scroll, row_index, model)
        self._quality(scroll, row_index, model)

    def _detail_kpis(self, parent: Any, row_index: int, model: Any) -> int:
        SectionHeader(parent, "Cargo profile", "Current booking quantities; cancelled rows remain in the booking audit but contribute zero quantities.").grid(
            row=row_index, column=0, sticky="ew", pady=(SPACING.sm, SPACING.md)
        )
        row_index += 1
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row_index, column=0, sticky="ew")
        for column in range(4):
            frame.grid_columnconfigure(column, weight=1, uniform="voyage-kpi")
        values = [
            ("Total Containers", model.metrics.get("Total Containers"), "number", "All active cargo"),
            ("Loaded", model.metrics.get("Loaded Containers"), "number", format_percentage(model.metrics.get("Loaded %"))),
            ("Empty", model.metrics.get("Empty Containers"), "number", format_percentage(model.metrics.get("Empty %"))),
            ("Total TEU", model.metrics.get("Total TEU"), "number", "Python-calculated"),
            ("Total GWT", model.metrics.get("Total GWT"), "gwt", "Gross weight"),
            ("20ft", model.metrics.get("Total 20ft"), "number", "Known equipment"),
            ("40ft", model.metrics.get("Total 40ft"), "number", "Known equipment"),
            ("GWT / Loaded TEU", model.metrics.get("Loaded GWT / Loaded TEU"), "number", "Unavailable when loaded TEU is zero"),
        ]
        for index, (title, value, kind, secondary) in enumerate(values):
            KpiCard(frame, title, value, kind=kind, secondary=secondary).grid(
                row=index // 4, column=index % 4, sticky="nsew", padx=SPACING.xs, pady=SPACING.xs
            )
        row_index += 1
        unclassified = pd.to_numeric(pd.Series([model.metrics.get("Unclassified Containers")]), errors="coerce").fillna(0).iloc[0]
        if unclassified > 0:
            StatePanel(
                parent,
                "Unclassified cargo",
                f"{float(unclassified):g} containers remain in voyage totals but are excluded from Loaded and Empty percentages.",
                kind="warning",
            ).grid(row=row_index, column=0, sticky="ew", pady=(SPACING.sm, 0))
            row_index += 1
        return row_index

    def _schedule(self, parent: Any, row_index: int, model: Any) -> int:
        SectionHeader(parent, "Schedule movement", "Positive ETA movement means later; it is not assigned a good/bad score.").grid(
            row=row_index, column=0, sticky="ew", pady=(SPACING.xl, SPACING.md)
        )
        row_index += 1
        panel = ctk.CTkFrame(parent, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=10)
        panel.grid(row=row_index, column=0, sticky="ew")
        for column in range(4):
            panel.grid_columnconfigure(column, weight=1, uniform="schedule")
        items = [
            ("Original ETA", model.schedule.get("Original ETA")),
            ("Current ETA", model.schedule.get("Current ETA")),
            ("Net movement", format_movement(model.schedule.get("Net ETA Movement"))),
            ("Cumulative movement", format_movement(model.schedule.get("Cumulative ETA Movement"))),
            ("ETA revisions", format_number(model.schedule.get("ETA Revision Count"))),
            ("Largest revision", format_movement(model.schedule.get("Largest ETA Revision"))),
            ("Week changes", format_number(model.schedule.get("Week Change Count"))),
            ("Week path", f"{_shown(model.schedule.get('Original Week'))} → {_shown(model.schedule.get('Current Week'))}"),
        ]
        for index, (label, value) in enumerate(items):
            item = ctk.CTkFrame(panel, fg_color="transparent")
            item.grid(row=index // 4, column=index % 4, sticky="ew", padx=SPACING.md, pady=SPACING.md)
            ctk.CTkLabel(item, text=label, text_color=PALETTE.text_muted, font=font(10), anchor="w").pack(fill="x")
            ctk.CTkLabel(item, text=str(value), text_color=PALETTE.text, font=font(13, weight="bold"), anchor="w").pack(fill="x", pady=(3, 0))
        return row_index + 1

    def _cargo_charts(self, parent: Any, row_index: int, model: Any) -> int:
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.grid(row=row_index, column=0, sticky="ew", pady=(SPACING.lg, 0))
        for column in range(2):
            grid.grid_columnconfigure(column, weight=1, uniform="cargo")
        loaded = ChartCard(grid, "Loaded vs Empty", "Unclassified is shown separately.")
        loaded.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.xs))
        _single_breakdown(loaded, [
            ("Loaded", model.metrics.get("Loaded Containers"), PALETTE.accent),
            ("Empty", model.metrics.get("Empty Containers"), "#8AA4B0"),
            ("Unclassified", model.metrics.get("Unclassified Containers"), PALETTE.warning),
        ])
        equipment = ChartCard(grid, "Equipment mix", "Known 20ft and 40ft quantities.")
        equipment.grid(row=0, column=1, sticky="nsew", padx=(SPACING.xs, 0))
        _single_breakdown(equipment, [
            ("20ft", model.metrics.get("Total 20ft"), PALETTE.accent),
            ("40ft", model.metrics.get("Total 40ft"), "#78A6B8"),
        ])
        return row_index + 1

    def _bookings(self, parent: Any, row_index: int, model: Any) -> int:
        SectionHeader(parent, "Current bookings", f"{len(model.bookings)} rows, including cancelled rows for audit.").grid(
            row=row_index, column=0, sticky="ew", pady=(SPACING.xl, SPACING.md)
        )
        row_index += 1
        table = DataTable(parent, height=min(10, max(4, len(model.bookings))), visible_columns=BOOKING_COLUMNS, empty_message="No booking rows are available for this voyage.")
        table.grid(row=row_index, column=0, sticky="ew")
        table.set_dataframe(model.bookings)
        return row_index + 1

    def _timeline(self, parent: Any, row_index: int, model: Any) -> int:
        heading = ctk.CTkFrame(parent, fg_color="transparent")
        heading.grid(row=row_index, column=0, sticky="ew", pady=(SPACING.xl, SPACING.md))
        heading.grid_columnconfigure(0, weight=1)
        SectionHeader(heading, "Voyage timeline", "Grouped events remove duplicate voyage-wide row logging; raw events remain available.").grid(row=0, column=0, sticky="ew")
        toggle = ctk.CTkSegmentedButton(
            heading,
            values=["Grouped", "Raw"],
            command=lambda value: self._change_timeline_mode(value, parent, model),
            selected_color=PALETTE.accent,
            selected_hover_color=PALETTE.accent_hover,
            unselected_color=PALETTE.surface,
            unselected_hover_color=PALETTE.accent_soft,
            text_color=PALETTE.text,
        )
        toggle.set("Grouped" if self.timeline_mode == "grouped" else "Raw")
        toggle.grid(row=0, column=1, sticky="e")
        row_index += 1
        self.timeline_host = ctk.CTkFrame(parent, fg_color="transparent")
        self.timeline_host.grid(row=row_index, column=0, sticky="ew")
        self._render_timeline_table(model)
        return row_index + 1

    def _change_timeline_mode(self, value: str, _parent: Any, model: Any) -> None:
        self.timeline_mode = "grouped" if value == "Grouped" else "raw"
        self._render_timeline_table(model)

    def _render_timeline_table(self, model: Any) -> None:
        _clear_frame(self.timeline_host)
        rows = model.grouped_timeline if self.timeline_mode == "grouped" else model.raw_timeline
        table = DataTable(
            self.timeline_host,
            height=min(10, max(4, len(rows))),
            visible_columns=TIMELINE_COLUMNS,
            sort_keys={"Timestamp": "_TimestampSort"},
            empty_message="No recorded changes are available for this voyage.",
        )
        table.pack(fill="both", expand=True)
        table.set_dataframe(rows)

    def _quality(self, parent: Any, row_index: int, model: Any) -> None:
        count = len(model.quality_issues)
        SectionHeader(parent, "Data-quality context", "Use Data Quality for the complete issue list, search, explanations, and export.").grid(
            row=row_index, column=0, sticky="ew", pady=(SPACING.xl, SPACING.md)
        )
        row_index += 1
        if count == 0:
            StatePanel(parent, "No voyage-specific issues", "No current structured quality issue is associated with this voyage.", kind="information").grid(row=row_index, column=0, sticky="ew", pady=(0, SPACING.lg))
            return
        first = model.quality_issues.iloc[0]
        StatePanel(
            parent,
            f"{count} issue{'s' if count != 1 else ''} associated with this voyage",
            str(first.get("Message", "Review the detailed Data Quality page when it is implemented.")),
            kind="warning",
        ).grid(row=row_index, column=0, sticky="ew", pady=(0, SPACING.lg))

    def _back_to_browser(self) -> None:
        return_route = self.return_route
        self.detail_open = False
        self.return_route = None
        if return_route and self.on_navigate is not None:
            self.on_navigate(return_route)
            return
        self._render_browser()


def _single_breakdown(card: ChartCard, values: list[tuple[str, Any, str]]) -> None:
    labels = [label for label, value, _ in values if _numeric(value) > 0]
    numbers = [_numeric(value) for _, value, _ in values if _numeric(value) > 0]
    colors = [color for _, value, color in values if _numeric(value) > 0]
    if not numbers:
        card.show_empty("No quantity is available for this breakdown.")
        return
    figure = card.new_figure(height=2.5)
    axis = figure.add_subplot(111)
    ChartCard.style_axis(axis)
    axis.barh(labels[::-1], numbers[::-1], color=colors[::-1])
    axis.set_xlabel("Containers", color=PALETTE.text_muted)
    card.show_figure(figure)


def _numeric(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return 0.0 if pd.isna(numeric) else float(numeric)


def _shown(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if not pd.isna(numeric) and float(numeric).is_integer():
        return str(int(numeric))
    text = str(value).strip() if value is not None else ""
    return text if text and text.casefold() not in {"nan", "nat", "none"} else "Unavailable"


def _clear_frame(frame: Any) -> None:
    for child in frame.winfo_children():
        child.destroy()
