from __future__ import annotations

from typing import Any

import customtkinter as ctk

from src.app_state import ALL_OPTION, ApplicationState, VesselAnalyticsModel
from .charts import bar_chart_card
from .theme import PALETTE
from .widgets import create_treeview, format_movement_days, format_number, populate_treeview, set_combo_values


class VesselAnalyticsView(ctk.CTkFrame):
    def __init__(self, parent: Any, state: ApplicationState) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app_state = state
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        selector_frame = ctk.CTkFrame(self)
        selector_frame.grid(row=2, column=0, sticky="ew", padx=24, pady=(16, 12))
        selector_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(selector_frame, text="Vessel", text_color=PALETTE.text_muted).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        self.vessel_combo = ctk.CTkComboBox(selector_frame, values=[ALL_OPTION], command=self.on_selection_changed)
        self.vessel_combo.set(ALL_OPTION)
        self.vessel_combo.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.status_label = ctk.CTkLabel(self, text="", text_color=PALETTE.text_muted, justify="left")
        self.status_label.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 8))

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=4, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.body.grid_columnconfigure(0, weight=1)

    def refresh_view(self) -> None:
        self.refresh_selector_options(preserve_selection=True)
        self.render_detail()

    def refresh_selector_options(self, *, preserve_selection: bool) -> None:
        options = self.app_state.selector_options()
        current = self.vessel_combo.get() if preserve_selection else ALL_OPTION
        set_combo_values(self.vessel_combo, options.vessels, selected=current)

    def on_selection_changed(self, *_: Any) -> None:
        self.render_detail()

    def render_detail(self) -> None:
        _clear_frame(self.body)
        model = self.app_state.vessel_analytics(self.vessel_combo.get())
        self.status_label.configure(text=model.empty_message or "")
        if model.summary is None:
            return

        row = 0
        summary = model.summary
        row = self._add_section(
            row,
            "Identity / scope",
            [
                ("Vessel", summary.vessel or "—"),
                ("Voyages involved", _join(summary.voyages)),
                ("BlockIDs involved", _join(summary.affected_block_ids)),
                ("Affected RowIDs", _join(summary.affected_row_ids)),
            ],
        )
        row = self._add_section(
            row,
            "Operational metrics",
            [
                ("Current operational rows", format_number(summary.operational_rows)),
                ("Cancelled rows", format_number(summary.cancelled_rows)),
                ("Summary", format_number(summary.total_summary)),
                ("TEU", format_number(summary.total_teu)),
                ("TS", format_number(summary.total_ts)),
            ],
        )
        row = self._add_section(
            row,
            "History metrics",
            [
                ("Total history events", format_number(summary.history_event_count)),
                ("ETA material revisions", format_number(model.material_revision_counts["ETA"])),
                ("ETD material revisions", format_number(model.material_revision_counts["ETD"])),
                ("Cut-Off material revisions", format_number(model.material_revision_counts["Cut-Off"])),
                ("ETA T/S material revisions", format_number(model.material_revision_counts["ETA T/S"])),
                ("Voyage changes", format_number(model.material_revision_counts["Voyage"])),
            ],
        )
        row = self._add_section(
            row,
            "Schedule metrics",
            [
                ("Average net ETA movement", format_movement_days(model.schedule_metrics.get("average_net_eta_movement"))),
                ("Average absolute ETA movement", _format_abs_days(model.schedule_metrics.get("average_absolute_eta_movement"))),
                ("Maximum delay", format_movement_days(model.schedule_metrics.get("maximum_delay"))),
                ("Maximum early movement", format_movement_days(model.schedule_metrics.get("maximum_early_movement"))),
                ("Average ETA revisions / voyage", format_number(model.schedule_metrics.get("average_eta_revisions_per_voyage"))),
                ("Most revised voyage", model.schedule_metrics.get("most_revised_voyage") or "—"),
            ],
        )
        row = self._add_table(row, "Voyages for selected vessel", model.voyage_table)
        self._add_charts(row, model)

    def _add_section(self, row: int, title: str, items: list[tuple[str, str]]) -> int:
        ctk.CTkLabel(self.body, text=title, font=ctk.CTkFont(size=17, weight="bold")).grid(row=row, column=0, sticky="w", padx=6, pady=(14, 8))
        row += 1
        panel = ctk.CTkFrame(self.body)
        panel.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 8))
        for column in range(2):
            panel.grid_columnconfigure(column, weight=1)
        for index, (label, value) in enumerate(items):
            item = ctk.CTkFrame(panel, fg_color="transparent")
            item.grid(row=index // 2, column=index % 2, sticky="ew", padx=12, pady=8)
            item.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(item, text=label, text_color=PALETTE.text_muted, anchor="w").grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(item, text=value, font=ctk.CTkFont(size=15, weight="bold"), anchor="w", wraplength=420).grid(
                row=1,
                column=0,
                sticky="ew",
            )
        return row + 1

    def _add_table(self, row: int, title: str, frame) -> int:
        ctk.CTkLabel(self.body, text=title, font=ctk.CTkFont(size=17, weight="bold")).grid(row=row, column=0, sticky="w", padx=6, pady=(16, 8))
        row += 1
        if frame.empty:
            ctk.CTkLabel(self.body, text="No voyages are available for this vessel.", text_color=PALETTE.text_muted).grid(row=row, column=0, sticky="w", padx=6, pady=(0, 8))
            return row + 1
        table_frame = ctk.CTkFrame(self.body)
        table_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 10))
        table_frame.grid_columnconfigure(0, weight=1)
        display = frame[
            [
                "Voyage",
                "BlockID",
                "operational rows",
                "cancelled rows",
                "TEU",
                "TS",
                "Original ETA",
                "Current ETA",
                "Net ETA movement",
                "ETA revisions",
                "Total history events",
            ]
        ].copy()
        tree, vertical, horizontal = create_treeview(table_frame, list(display.columns), height=min(12, max(3, len(display))))
        tree.grid(row=0, column=0, sticky="ew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        populate_treeview(tree, display)
        return row + 1

    def _add_charts(self, row: int, model: VesselAnalyticsModel) -> int:
        ctk.CTkLabel(self.body, text="Vessel charts", font=ctk.CTkFont(size=17, weight="bold")).grid(row=row, column=0, sticky="w", padx=6, pady=(16, 8))
        row += 1
        frame = ctk.CTkFrame(self.body, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=0, pady=(0, 12))
        for column in range(2):
            frame.grid_columnconfigure(column, weight=1)
        charts = [
            bar_chart_card(
                frame,
                "ETA Net Movement by Voyage",
                model.eta_movement_by_voyage,
                empty_message="ETA movement cannot be calculated for this vessel yet.",
                signed=True,
                allow_all_zero=False,
            ),
            bar_chart_card(
                frame,
                "ETA Revisions by Voyage",
                model.eta_revisions_by_voyage,
                empty_message="No material ETA revision history is available for this vessel.",
            ),
            bar_chart_card(
                frame,
                "TEU by Voyage",
                model.teu_by_voyage,
                empty_message="No TEU data is available for this vessel.",
            ),
        ]
        for index, chart in enumerate(charts):
            chart.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
        return row + 1


def _format_abs_days(value: float | None) -> str:
    if value is None:
        return "Unknown"
    if value == 0:
        return "No movement"
    amount = f"{int(value)}" if float(value).is_integer() else f"{float(value):.1f}"
    return f"{amount} days"


def _join(values: list[str]) -> str:
    return ", ".join(values) if values else "—"


def _clear_frame(frame: Any) -> None:
    for child in frame.winfo_children():
        child.destroy()
