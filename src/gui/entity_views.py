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
from .components.kpi_card import KpiCard
from .components.layout import SectionHeader
from .exporting import export_visible_csv
from .presentation import format_date, format_movement, format_number, format_percentage
from .secondary_models import EntityAnalyticsPageModel
from .theme import PALETTE, SPACING, font


ENTITY_CONFIG = {
    "vessel": {
        "title": "Vessels",
        "label": "Vessel",
        "question": "How are our vessels being used and how do they compare?",
        "file": "vessel_summary.csv",
        "overview": [
            "Vessel", "Voyage Count", "Total Containers", "Loaded Containers", "Empty Containers", "Loaded %", "Empty %",
            "Total TEU", "Total GWT", "20ft", "40ft", "Cancellation Count", "Cancellation Rate",
            "Median Net ETA Movement", "Median ETA Revision Count", "Median Schedule Volatility", "Week Rollover %",
        ],
    },
    "service": {
        "title": "Services",
        "label": "SVC",
        "question": "How are our shipping services performing operationally?",
        "file": "service_summary.csv",
        "overview": [
            "SVC", "Voyage Count", "Total Containers", "Loaded Containers", "Empty Containers", "Total TEU", "Total GWT",
            "Loaded %", "Empty %", "20ft", "40ft", "Cancellation Rate", "Customer Count", "Median Net ETA Movement",
            "Median ETA Revision Count", "Median Schedule Volatility", "Week Rollover %",
        ],
    },
    "customer": {
        "title": "Customers",
        "label": "CUSTOMER",
        "question": "Who is moving cargo with us and what does their activity look like?",
        "file": "customer_summary.csv",
        "overview": [
            "CUSTOMER", "Voyage Count", "Booking/Row Count", "Total Containers", "Loaded Containers", "Empty Containers",
            "Total TEU", "Total GWT", "20ft", "40ft", "Average Booking Size", "Cancellation Count", "Cancellation Rate",
            "Share of Total TEU",
        ],
    },
}

VOYAGE_COLUMNS = [
    "Vessel", "Voyage", "Week", "ETA", "POD", "SVC", "Total Containers", "Loaded Containers", "Empty Containers",
    "Total TEU", "Total GWT", "ETA Revision Count", "Net ETA Movement", "Week Change Count", "Cancelled rows", "Attention",
]


class EntityAnalyticsView(ctk.CTkFrame):
    """Shared Phase F composition for vessel, service, and customer analytics."""

    def __init__(
        self,
        parent: Any,
        state: ApplicationState,
        kind: str,
        *,
        on_open_voyage: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        if kind not in ENTITY_CONFIG:
            raise ValueError(f"Unsupported entity page: {kind}")
        self.app_state = state
        self.kind = kind
        self.config = ENTITY_CONFIG[kind]
        self.on_open_voyage = on_open_voyage
        self.filter_context = FilterContext()
        self.selected_key: str | None = None
        self.label_to_key: dict[str, str] = {}
        self.current_model: EntityAnalyticsPageModel | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.md, SPACING.sm))
        toolbar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(toolbar, text=f"Selected {self.config['label']}", text_color=PALETTE.text_muted, font=font(11)).grid(row=0, column=0, sticky="w")
        self.selector = ctk.CTkComboBox(toolbar, values=["Overview"], command=self._select_entity, width=300)
        self.selector.set("Overview")
        self.selector.grid(row=1, column=0, sticky="w", pady=(SPACING.xs, 0))
        ctk.CTkLabel(toolbar, text=self.config["question"], text_color=PALETTE.text_muted, font=font(11), anchor="w").grid(
            row=1, column=1, sticky="ew", padx=SPACING.lg
        )
        ctk.CTkButton(toolbar, text="Export summary", command=self._export_summary, width=122, fg_color=PALETTE.surface_subtle,
                      hover_color=PALETTE.accent_soft, text_color=PALETTE.text).grid(row=1, column=2, sticky="e")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.xl))
        self.body.grid_columnconfigure(0, weight=1)

    def set_filter_context(self, context: FilterContext) -> None:
        self.filter_context = context

    def refresh_view(self) -> None:
        overview = self._state_model(None)
        self._sync_options(overview)
        if self.selected_key and self.selected_key not in set(overview.overview.get("_EntityKey", pd.Series(dtype=object))):
            self.selected_key = None
            self.selector.set("Overview")
        self.current_model = self._state_model(self.selected_key)
        self._render(self.current_model)

    def _state_model(self, selected_key: str | None) -> EntityAnalyticsPageModel:
        if self.kind == "vessel":
            return self.app_state.vessel_analytics_page_model(selected_key)
        if self.kind == "service":
            return self.app_state.service_analytics_page_model(selected_key)
        return self.app_state.customer_analytics_page_model(selected_key)

    def _sync_options(self, model: EntityAnalyticsPageModel) -> None:
        self.label_to_key = {"Overview": ""}
        for _, row in model.overview.iterrows():
            label = str(row.get(model.label_column, "Unassigned"))
            self.label_to_key[label] = str(row.get("_EntityKey", ""))
        values = list(self.label_to_key)
        current = self.selector.get()
        self.selector.configure(values=values or ["Overview"])
        self.selector.set(current if current in values else "Overview")

    def _select_entity(self, label: str) -> None:
        self.selected_key = self.label_to_key.get(label) or None
        self.current_model = self._state_model(self.selected_key)
        self._render(self.current_model)

    def _render(self, model: EntityAnalyticsPageModel) -> None:
        _clear(self.body)
        if model.empty_message and model.overview.empty:
            StatePanel(self.body, f"No {self.config['title'].lower()}", model.empty_message, kind="information").grid(row=0, column=0, sticky="ew")
            return
        row_index = self._overview(model, 0)
        row_index = self._overview_charts(model, row_index)
        if model.selected_key:
            self._detail(model, row_index)

    def _overview(self, model: EntityAnalyticsPageModel, row_index: int) -> int:
        SectionHeader(
            self.body,
            f"{self.config['title']} overview",
            "Current operational values respect the shared filters. Schedule statistics remain unavailable when comparable history is absent.",
        ).grid(row=row_index, column=0, sticky="ew", pady=(SPACING.sm, SPACING.md))
        row_index += 1
        table = DataTable(
            self.body,
            visible_columns=self.config["overview"],
            height=min(11, max(4, len(model.overview))),
            empty_message=model.empty_message or "No rows match the shared filters.",
            formatters=_formatters(),
            on_activate=self._activate_overview,
        )
        table.grid(row=row_index, column=0, sticky="ew")
        table.set_dataframe(model.overview)
        self.overview_table = table
        return row_index + 1

    def _activate_overview(self, row: pd.Series) -> None:
        key = str(row.get("_EntityKey", ""))
        label = str(row.get(self.config["label"], ""))
        if key:
            self.selected_key = key
            if label in self.label_to_key:
                self.selector.set(label)
            self.current_model = self._state_model(key)
            self._render(self.current_model)

    def _overview_charts(self, model: EntityAnalyticsPageModel, row_index: int) -> int:
        charts = ctk.CTkFrame(self.body, fg_color="transparent")
        charts.grid(row=row_index, column=0, sticky="ew", pady=(SPACING.lg, 0))
        for column in range(2):
            charts.grid_columnconfigure(column, weight=1, uniform="entity-charts")
        label = model.label_column
        ranked = model.overview.sort_values("Total TEU", ascending=False, kind="mergesort").head(12)
        teu = ChartCard(charts, f"TEU by {self.config['title'][:-1]}", "Ranked current totals; up to 12 values are shown.")
        teu.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.xs))
        _ranked_bar(teu, ranked, label, "Total TEU")
        mix = ChartCard(charts, "Loaded vs Empty", "Current container quantities; unclassified cargo is excluded from this split.")
        mix.grid(row=0, column=1, sticky="nsew", padx=(SPACING.xs, 0))
        _grouped_horizontal(mix, ranked, label, ["Loaded Containers", "Empty Containers"])
        return row_index + 1

    def _detail(self, model: EntityAnalyticsPageModel, row_index: int) -> None:
        SectionHeader(self.body, f"{model.selected_label} detail", "Entity selection adds a local scope while preserving every active shared filter.").grid(
            row=row_index, column=0, sticky="ew", pady=(SPACING.xl, SPACING.md)
        )
        row_index += 1
        if model.detail_message:
            StatePanel(self.body, "Analytical context", model.detail_message, kind="information").grid(row=row_index, column=0, sticky="ew", pady=(0, SPACING.md))
            row_index += 1
        row_index = self._detail_kpis(model, row_index)
        row_index = self._detail_mix(model, row_index)
        row_index = self._voyages(model, row_index)
        row_index = self._breakdowns(model, row_index)
        if self.kind == "customer":
            self._trend(model, row_index)

    def _detail_kpis(self, model: EntityAnalyticsPageModel, row_index: int) -> int:
        frame = ctk.CTkFrame(self.body, fg_color="transparent")
        frame.grid(row=row_index, column=0, sticky="ew")
        for column in range(4):
            frame.grid_columnconfigure(column, weight=1, uniform="entity-kpi")
        summary = model.summary
        cards = [
            ("Voyages", summary.get("Voyage Count"), "number", "Safe voyage instances"),
            ("Containers", summary.get("Total Containers"), "number", "Cancelled rows contribute zero"),
            ("Loaded", summary.get("Loaded Containers"), "number", format_percentage(summary.get("Loaded %"))),
            ("Empty", summary.get("Empty Containers"), "number", format_percentage(summary.get("Empty %"))),
            ("TEU", summary.get("Total TEU"), "number", "Python-calculated"),
            ("GWT", summary.get("Total GWT"), "gwt", "Current gross weight"),
            ("Cancellations", summary.get("Cancellation Count"), "number", format_percentage(summary.get("Cancellation Rate"))),
            ("Median ETA movement", format_movement(summary.get("Median Net ETA Movement")), "text", "Unavailable without comparable history"),
        ]
        for index, (title, value, kind, secondary) in enumerate(cards):
            KpiCard(frame, title, value, kind=kind, secondary=secondary).grid(
                row=index // 4, column=index % 4, sticky="nsew", padx=SPACING.xs, pady=SPACING.xs
            )
        return row_index + 1

    def _detail_mix(self, model: EntityAnalyticsPageModel, row_index: int) -> int:
        charts = ctk.CTkFrame(self.body, fg_color="transparent")
        charts.grid(row=row_index, column=0, sticky="ew", pady=(SPACING.lg, 0))
        for column in range(2):
            charts.grid_columnconfigure(column, weight=1, uniform="detail-charts")
        load = ChartCard(charts, "Load mix", "Loaded and empty quantities for the selected scope.")
        load.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.xs))
        _single_bar(load, [("Loaded", model.summary.get("Loaded Containers")), ("Empty", model.summary.get("Empty Containers"))])
        equipment = ChartCard(charts, "Equipment mix", "Known 20ft and 40ft quantities.")
        equipment.grid(row=0, column=1, sticky="nsew", padx=(SPACING.xs, 0))
        _single_bar(equipment, [("20ft", model.summary.get("20ft")), ("40ft", model.summary.get("40ft"))])
        return row_index + 1

    def _voyages(self, model: EntityAnalyticsPageModel, row_index: int) -> int:
        SectionHeader(self.body, "Voyage breakdown", "Double-click a row to open the existing Voyage Detail screen using composite identity.").grid(
            row=row_index, column=0, sticky="ew", pady=(SPACING.xl, SPACING.md)
        )
        row_index += 1
        table = DataTable(
            self.body,
            visible_columns=VOYAGE_COLUMNS,
            height=min(10, max(4, len(model.voyages))),
            empty_message="No safely identified voyage instance is available for this selection.",
            formatters=_formatters(),
            on_activate=self._open_voyage,
        )
        table.grid(row=row_index, column=0, sticky="ew")
        table.set_dataframe(model.voyages)
        return row_index + 1

    def _open_voyage(self, row: pd.Series) -> None:
        identity = str(row.get("IdentityKey", ""))
        if identity and self.on_open_voyage is not None:
            self.on_open_voyage(identity)

    def _breakdowns(self, model: EntityAnalyticsPageModel, row_index: int) -> int:
        choices: list[tuple[str, pd.DataFrame, str]] = []
        if self.kind == "service":
            choices = [("Major observed PODs", model.pod_breakdown, "POD"), ("Major customers", model.customer_breakdown, "CUSTOMER")]
        elif self.kind == "customer":
            choices = [("POD distribution", model.pod_breakdown, "POD"), ("Service distribution", model.service_breakdown, "SVC")]
        if not choices:
            return row_index
        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.grid(row=row_index, column=0, sticky="ew", pady=(SPACING.lg, 0))
        for column in range(2):
            grid.grid_columnconfigure(column, weight=1, uniform="breakdowns")
        for index, (title, frame, label) in enumerate(choices):
            host = ctk.CTkFrame(grid, fg_color="transparent")
            host.grid(row=0, column=index, sticky="nsew", padx=(0, SPACING.xs) if index == 0 else (SPACING.xs, 0))
            SectionHeader(host, title, "Observed current-state distribution; no causation is implied.").pack(fill="x", pady=(0, SPACING.sm))
            table = DataTable(host, visible_columns=[label, "Voyage Count", "Total Containers", "Total TEU"], height=min(7, max(3, len(frame))), formatters=_formatters())
            table.pack(fill="both", expand=True)
            table.set_dataframe(frame.head(12))
        return row_index + 1

    def _trend(self, model: EntityAnalyticsPageModel, row_index: int) -> None:
        SectionHeader(self.body, "ETA-month trend", "A trend is shown only when at least two valid ETA periods exist.").grid(
            row=row_index, column=0, sticky="ew", pady=(SPACING.xl, SPACING.md)
        )
        row_index += 1
        card = ChartCard(self.body, "Customer TEU over time", "ETA Month is derived only from valid ETA dates.")
        card.grid(row=row_index, column=0, sticky="ew")
        if len(model.trend) < 2:
            card.show_empty("Insufficient valid ETA periods for a meaningful trend.")
            return
        figure = card.new_figure(height=2.8)
        axis = figure.add_subplot(111)
        ChartCard.style_axis(axis, value_label="TEU")
        axis.plot(model.trend["ETA Month"].astype(str), pd.to_numeric(model.trend["Total TEU"], errors="coerce"), marker="o", color=PALETTE.accent)
        card.show_figure(figure)

    def _export_summary(self) -> None:
        if self.current_model is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export analytical summary", initialfile=self.config["file"], defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        result = export_visible_csv(self.current_model.overview, Path(path), visible_columns=self.config["overview"])
        if result.success:
            messagebox.showinfo("Export complete", result.message, parent=self)
        else:
            messagebox.showwarning("Nothing to export", result.message, parent=self)


def _formatters() -> dict[str, Callable[[Any], str]]:
    return {
        "ETA": format_date,
        "Loaded %": format_percentage,
        "Empty %": format_percentage,
        "Cancellation Rate": format_percentage,
        "Share of Total TEU": format_percentage,
        "Week Rollover %": format_percentage,
        "Median Net ETA Movement": format_movement,
        "Median Schedule Volatility": _format_duration,
        "Net ETA Movement": format_movement,
        "Total GWT": lambda value: format_number(value, decimals=1),
    }
def _ranked_bar(card: ChartCard, frame: pd.DataFrame, label: str, metric: str) -> None:
    if frame.empty or metric not in frame.columns or pd.to_numeric(frame[metric], errors="coerce").fillna(0).sum() == 0:
        card.show_empty("No quantity is available for this chart.")
        return
    figure = card.new_figure(height=3.0)
    axis = figure.add_subplot(111)
    ChartCard.style_axis(axis, value_label=metric)
    axis.barh(frame[label].astype(str).tolist()[::-1], pd.to_numeric(frame[metric], errors="coerce").fillna(0).tolist()[::-1], color=PALETTE.accent)
    card.show_figure(figure)


def _grouped_horizontal(card: ChartCard, frame: pd.DataFrame, label: str, metrics: list[str]) -> None:
    if frame.empty or not all(metric in frame.columns for metric in metrics):
        card.show_empty("No load classification is available for this chart.")
        return
    figure = card.new_figure(height=3.0)
    axis = figure.add_subplot(111)
    ChartCard.style_axis(axis, value_label="Containers")
    y = list(range(len(frame)))
    height = 0.34
    axis.barh([value - height / 2 for value in y], pd.to_numeric(frame[metrics[0]], errors="coerce").fillna(0), height=height, label="Loaded", color=PALETTE.accent)
    axis.barh([value + height / 2 for value in y], pd.to_numeric(frame[metrics[1]], errors="coerce").fillna(0), height=height, label="Empty", color="#8AA4B0")
    axis.set_yticks(y, frame[label].astype(str).tolist())
    axis.legend(facecolor=PALETTE.surface, edgecolor=PALETTE.border, labelcolor=PALETTE.text_muted)
    card.show_figure(figure)


def _single_bar(card: ChartCard, values: list[tuple[str, Any]]) -> None:
    usable = [(label, _number(value)) for label, value in values if _number(value) > 0]
    if not usable:
        card.show_empty("No quantity is available for this breakdown.")
        return
    figure = card.new_figure(height=2.5)
    axis = figure.add_subplot(111)
    ChartCard.style_axis(axis, value_label="Containers")
    axis.barh([label for label, _ in usable][::-1], [value for _, value in usable][::-1], color=[PALETTE.accent, "#8AA4B0"][:len(usable)][::-1])
    card.show_figure(figure)


def _number(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return 0.0 if pd.isna(numeric) else float(numeric)


def _format_duration(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "Unavailable"
    amount = f"{float(numeric):.0f}" if float(numeric).is_integer() else f"{float(numeric):.1f}"
    return f"{amount} days"


def _clear(parent: Any) -> None:
    for child in parent.winfo_children():
        child.destroy()
