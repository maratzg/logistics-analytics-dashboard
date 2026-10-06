from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk
import pandas as pd

from src.app_state import ApplicationState

from .components.chart_card import ChartCard
from .components.empty_state import StatePanel
from .components.kpi_card import KpiCard
from .components.layout import SectionHeader
from .theme import PALETTE, SPACING, font


class DashboardView(ctk.CTkFrame):
    """Phase E current-operations overview; historical deep analysis stays elsewhere."""

    def __init__(
        self,
        parent: Any,
        state: ApplicationState,
        *,
        locate_workbook_command: Callable[[], None] | None = None,
        discover_workbooks_command: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app_state = state
        self.locate_workbook_command = locate_workbook_command
        self.discover_workbooks_command = discover_workbooks_command
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=0, column=0, sticky="nsew", padx=SPACING.lg, pady=(SPACING.md, SPACING.lg))
        self.body.grid_columnconfigure(0, weight=1)

    def refresh_view(self) -> None:
        _clear_frame(self.body)
        if self.app_state.data is None:
            self._render_setup()
            return

        model = self.app_state.operational_dashboard_model()
        if not model.has_rows:
            StatePanel(
                self.body,
                "No current operations in this view",
                model.empty_message or "No operational rows are currently available.",
                kind="empty",
            ).grid(row=0, column=0, sticky="ew", padx=SPACING.xs, pady=SPACING.sm)
            self._render_recent_changes(1, model.recent_changes)
            return

        row = self._render_kpis(0, model.metrics)
        unclassified = float(model.metrics.unclassified_containers)
        if unclassified > 0:
            StatePanel(
                self.body,
                "Unclassified cargo remains in totals",
                f"{unclassified:g} containers are included in Total but not forced into Loaded or Empty. Review LoadStatus in WEEKLY.",
                kind="warning",
            ).grid(row=row, column=0, sticky="ew", padx=SPACING.xs, pady=(0, SPACING.md))
            row += 1

        row = self._render_charts(row, model)
        row = self._render_attention(row, model.attention_items, model.quality_counts)
        self._render_recent_changes(row, model.recent_changes)

    def _render_setup(self) -> None:
        panel = StatePanel(
            self.body,
            "Workbook not configured",
            "Select the SharePoint/OneDrive-synced workbook to begin. The application only reads the source.",
            kind="empty",
            action_label="Locate workbook" if self.locate_workbook_command else None,
            action=self.locate_workbook_command,
        )
        panel.grid(row=0, column=0, sticky="ew", padx=SPACING.xs, pady=SPACING.md)
        if self.discover_workbooks_command is not None:
            ctk.CTkButton(
                self.body,
                text="Find synced workbooks",
                command=self.discover_workbooks_command,
                fg_color="transparent",
                text_color=PALETTE.accent,
                hover_color=PALETTE.accent_soft,
            ).grid(row=1, column=0, sticky="w", padx=SPACING.sm)

    def _render_kpis(self, row: int, metrics: Any) -> int:
        SectionHeader(self.body, "Current operations", "Cancellation-safe quantities from the current WEEKLY snapshot.").grid(
            row=row, column=0, sticky="ew", padx=SPACING.xs, pady=(SPACING.sm, SPACING.md)
        )
        row += 1
        frame = ctk.CTkFrame(self.body, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew")
        for column in range(4):
            frame.grid_columnconfigure(column, weight=1, uniform="dashboard-kpi")
        cards = [
            ("Total Containers", metrics.total_containers, "number", "All active classified and unclassified cargo"),
            ("Loaded Containers", metrics.loaded_containers, "number", f"{_percent(metrics.loaded_percent)} of total"),
            ("Empty Containers", metrics.empty_containers, "number", f"{_percent(metrics.empty_percent)} of total"),
            ("Total TEU", metrics.total_teu, "number", "Python-calculated"),
            ("Total GWT", metrics.total_gwt, "gwt", "Gross weight"),
            ("20ft Containers", metrics.total_20ft, "number", "Known equipment size"),
            ("40ft Containers", metrics.total_40ft, "number", "Known equipment size"),
            ("Cancelled", metrics.cancelled_rows, "number", "Rows retained for audit"),
        ]
        for index, (title, value, kind, context) in enumerate(cards):
            card = KpiCard(frame, title, value, kind=kind, secondary=context)
            card.grid(row=index // 4, column=index % 4, sticky="nsew", padx=SPACING.xs, pady=SPACING.xs)
        return row + 1

    def _render_charts(self, row: int, model: Any) -> int:
        SectionHeader(self.body, "Cargo at a glance", "Current composition under the shared filters.").grid(
            row=row, column=0, sticky="ew", padx=SPACING.xs, pady=(SPACING.xl, SPACING.md)
        )
        row += 1
        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.grid(row=row, column=0, sticky="ew")
        for column in range(2):
            grid.grid_columnconfigure(column, weight=1, uniform="dashboard-charts")

        composition = ChartCard(grid, "Loaded vs Empty by Voyage", "Unclassified cargo is shown separately when present.")
        composition.grid(row=0, column=0, sticky="nsew", padx=SPACING.xs, pady=SPACING.xs)
        _stacked_bar(composition, model.voyage_composition, "Label", ["Loaded Containers", "Empty Containers", "Unclassified Containers"], [PALETTE.accent, "#8AA4B0", PALETTE.warning], "Containers")

        equipment = ChartCard(grid, "20ft vs 40ft by Voyage", "Known equipment only.")
        equipment.grid(row=0, column=1, sticky="nsew", padx=SPACING.xs, pady=SPACING.xs)
        _stacked_bar(equipment, model.equipment_mix, "Label", ["Total 20ft", "Total 40ft"], [PALETTE.accent, "#78A6B8"], "Containers")

        teu = ChartCard(grid, "TEU by Vessel", "Current capacity distribution.")
        teu.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=SPACING.xs, pady=SPACING.xs)
        _horizontal_bar(teu, model.teu_by_vessel, "Vessel", "Total TEU", "TEU")
        row += 1
        if model.chart_limit_note:
            ctk.CTkLabel(self.body, text=model.chart_limit_note, text_color=PALETTE.text_muted, font=font(10), anchor="w").grid(
                row=row, column=0, sticky="ew", padx=SPACING.sm, pady=(SPACING.xs, 0)
            )
            row += 1
        return row

    def _render_attention(self, row: int, items: list[Any], quality_counts: dict[str, int]) -> int:
        quality_text = f"{quality_counts['Critical']} critical · {quality_counts['Warning']} warning · {quality_counts['Information']} information"
        SectionHeader(self.body, "Needs attention", quality_text).grid(
            row=row, column=0, sticky="ew", padx=SPACING.xs, pady=(SPACING.xl, SPACING.md)
        )
        row += 1
        if not items:
            StatePanel(
                self.body,
                "No explainable attention signals",
                "No cancellations, unclassified cargo, repeat revisions, Week changes, or warning-level quality issues appear under the current filters.",
                kind="information",
            ).grid(row=row, column=0, sticky="ew", padx=SPACING.xs)
            return row + 1
        panel = ctk.CTkFrame(self.body, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=SPACING.xs)
        panel.grid_columnconfigure(1, weight=1)
        for index, item in enumerate(items):
            color = PALETTE.danger if item.severity == "critical" else (PALETTE.warning if item.severity in {"warning", "watch"} else PALETTE.info)
            ctk.CTkLabel(panel, text="!" if item.severity != "information" else "i", text_color=color, font=font(13, weight="bold"), width=26).grid(
                row=index, column=0, padx=(SPACING.md, SPACING.sm), pady=SPACING.sm
            )
            text = ctk.CTkFrame(panel, fg_color="transparent")
            text.grid(row=index, column=1, sticky="ew", padx=(0, SPACING.md), pady=SPACING.sm)
            text.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(text, text=item.title, text_color=PALETTE.text, font=font(11, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(text, text=item.reason, text_color=PALETTE.text_muted, font=font(10), anchor="w", justify="left", wraplength=840).grid(row=1, column=0, sticky="ew")
        return row + 1

    def _render_recent_changes(self, row: int, changes: list[Any]) -> int:
        SectionHeader(self.body, "Recent operational changes", "Deduplicated voyage-level events from LOG_HISTORY.").grid(
            row=row, column=0, sticky="ew", padx=SPACING.xs, pady=(SPACING.xl, SPACING.md)
        )
        row += 1
        if not changes:
            StatePanel(self.body, "No recent changes", "No meaningful change events match the current filters.", kind="empty").grid(
                row=row, column=0, sticky="ew", padx=SPACING.xs
            )
            return row + 1
        panel = ctk.CTkFrame(self.body, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=10)
        panel.grid(row=row, column=0, sticky="ew", padx=SPACING.xs, pady=(0, SPACING.lg))
        panel.grid_columnconfigure(1, weight=1)
        for index, change in enumerate(changes):
            ctk.CTkLabel(panel, text=change.timestamp, text_color=PALETTE.text_soft, font=font(10), anchor="w", width=128).grid(
                row=index, column=0, sticky="nw", padx=SPACING.md, pady=SPACING.sm
            )
            context = f"{change.vessel} / {change.voyage}"
            if change.raw_event_count > 1:
                context += f" · grouped from {change.raw_event_count} row events"
            text = ctk.CTkFrame(panel, fg_color="transparent")
            text.grid(row=index, column=1, sticky="ew", padx=(0, SPACING.md), pady=SPACING.sm)
            text.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(text, text=change.message, text_color=PALETTE.text, font=font(11, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(text, text=context, text_color=PALETTE.text_muted, font=font(10), anchor="w").grid(row=1, column=0, sticky="ew")
        return row + 1


def _stacked_bar(card: ChartCard, data: pd.DataFrame, label_column: str, series: list[str], colors: list[str], value_label: str) -> None:
    if data.empty or not any(pd.to_numeric(data.get(column), errors="coerce").fillna(0).abs().sum() > 0 for column in series):
        card.show_empty("No cargo composition is available under the current filters.")
        return
    figure = card.new_figure(height=max(3.0, min(4.8, len(data) * 0.34 + 1.4)))
    axis = figure.add_subplot(111)
    ChartCard.style_axis(axis)
    labels = data[label_column].astype(str).tolist()[::-1]
    left = pd.Series(0.0, index=range(len(data)))
    for column, color in zip(series, colors, strict=False):
        values = pd.to_numeric(data[column], errors="coerce").fillna(0).reset_index(drop=True)[::-1].reset_index(drop=True)
        axis.barh(labels, values, left=left, label=column.replace(" Containers", "").replace("Total ", ""), color=color)
        left += values
    axis.set_xlabel(value_label, color=PALETTE.text_muted)
    axis.legend(frameon=False, fontsize=8, ncol=len(series), loc="lower right")
    card.show_figure(figure)


def _horizontal_bar(card: ChartCard, data: pd.DataFrame, label_column: str, value_column: str, value_label: str) -> None:
    if data.empty or pd.to_numeric(data.get(value_column), errors="coerce").fillna(0).abs().sum() == 0:
        card.show_empty("No TEU is available under the current filters.")
        return
    shown = data.iloc[::-1]
    figure = card.new_figure(height=max(2.7, min(4.6, len(shown) * 0.32 + 1.2)))
    axis = figure.add_subplot(111)
    ChartCard.style_axis(axis)
    axis.barh(shown[label_column].astype(str), pd.to_numeric(shown[value_column], errors="coerce").fillna(0), color=PALETTE.accent)
    axis.set_xlabel(value_label, color=PALETTE.text_muted)
    card.show_figure(figure)


def _percent(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "Unavailable" if pd.isna(numeric) else f"{float(numeric) * 100:.1f}%"


def _clear_frame(frame: Any) -> None:
    for child in frame.winfo_children():
        child.destroy()
