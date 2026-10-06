from __future__ import annotations

from typing import Any

import customtkinter as ctk
import pandas as pd

from src.app_state import ALL_OPTION, ApplicationState

from .components.data_table import DataTable
from .components.empty_state import StatePanel
from .components.layout import SectionHeader
from .theme import PALETTE, SPACING, font
from .widgets import set_combo_values


HISTORY_COLUMNS = ["Timestamp", "Vessel", "Voyage", "Week", "Booking number", "Field", "Old Value", "New Value", "User", "Raw Events"]


class HistoryView(ctk.CTkFrame):
    """Phase E operational history explorer with grouped and raw audit modes."""

    def __init__(self, parent: Any, state: ApplicationState) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app_state = state
        self.mode = "grouped"
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_controls()

        self.summary_label = ctk.CTkLabel(self, text="", text_color=PALETTE.text_muted, font=font(10), anchor="w")
        self.summary_label.grid(row=1, column=0, sticky="ew", padx=SPACING.xl, pady=(0, SPACING.sm))

        self.table_host = ctk.CTkFrame(self, fg_color="transparent")
        self.table_host.grid(row=2, column=0, sticky="nsew", padx=SPACING.xl)
        self.table_host.grid_columnconfigure(0, weight=1)
        self.table_host.grid_rowconfigure(0, weight=1)

        self.detail_host = ctk.CTkFrame(self, fg_color="transparent")
        self.detail_host.grid(row=3, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.md, SPACING.xl))
        self.detail_host.grid_columnconfigure(0, weight=1)

    def refresh_view(self) -> None:
        self._render()

    def clear_filters(self) -> None:
        self.field_combo.set(ALL_OPTION)
        self.user_combo.set(ALL_OPTION)
        self.start_entry.delete(0, "end")
        self.end_entry.delete(0, "end")
        self.search_entry.delete(0, "end")
        self._render()

    def _build_controls(self) -> None:
        controls = ctk.CTkFrame(self, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=10)
        controls.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.md, SPACING.sm))
        for column in range(6):
            controls.grid_columnconfigure(column, weight=1, uniform="history-controls")

        mode_frame = ctk.CTkFrame(controls, fg_color="transparent")
        mode_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=SPACING.md, pady=SPACING.md)
        ctk.CTkLabel(mode_frame, text="History mode", text_color=PALETTE.text_muted, font=font(10, weight="bold"), anchor="w").pack(fill="x", pady=(0, 3))
        self.mode_control = ctk.CTkSegmentedButton(
            mode_frame,
            values=["Grouped / Operational", "Raw Row Events"],
            command=self._mode_changed,
            selected_color=PALETTE.accent,
            selected_hover_color=PALETTE.accent_hover,
            unselected_color=PALETTE.surface_subtle,
            unselected_hover_color=PALETTE.accent_soft,
            text_color=PALETTE.text,
        )
        self.mode_control.set("Grouped / Operational")
        self.mode_control.pack(fill="x")

        self.field_combo = self._combo_control(controls, "Field", 2)
        self.user_combo = self._combo_control(controls, "User", 3)
        self.start_entry = self._entry_control(controls, "From date", 4, "DD.MM.YYYY")
        self.end_entry = self._entry_control(controls, "To date", 5, "DD.MM.YYYY")

        search_frame = ctk.CTkFrame(controls, fg_color="transparent")
        search_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=SPACING.md, pady=(0, SPACING.md))
        search_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(search_frame, text="Search", text_color=PALETTE.text_muted, font=font(10, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew", pady=(0, 3))
        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="RowID, vessel, voyage, week, booking, user, field, old or new value",
        )
        self.search_entry.grid(row=1, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda _event: self._render())

        actions = ctk.CTkFrame(controls, fg_color="transparent")
        actions.grid(row=1, column=4, columnspan=2, sticky="e", padx=SPACING.md, pady=(16, SPACING.md))
        ctk.CTkButton(actions, text="Apply", command=self._render, width=88, fg_color=PALETTE.accent, hover_color=PALETTE.accent_hover).pack(side="left", padx=SPACING.xs)
        ctk.CTkButton(
            actions,
            text="Clear history controls",
            command=self.clear_filters,
            width=138,
            fg_color="transparent",
            text_color=PALETTE.text_muted,
            hover_color=PALETTE.surface_subtle,
            border_width=1,
            border_color=PALETTE.border,
        ).pack(side="left", padx=SPACING.xs)

    def _combo_control(self, parent: Any, label: str, column: int) -> ctk.CTkComboBox:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=column, sticky="ew", padx=SPACING.sm, pady=SPACING.md)
        ctk.CTkLabel(frame, text=label, text_color=PALETTE.text_muted, font=font(10, weight="bold"), anchor="w").pack(fill="x", pady=(0, 3))
        combo = ctk.CTkComboBox(frame, values=[ALL_OPTION], state="readonly", command=lambda _value: self._render())
        combo.set(ALL_OPTION)
        combo.pack(fill="x")
        return combo

    def _entry_control(self, parent: Any, label: str, column: int, placeholder: str) -> ctk.CTkEntry:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=column, sticky="ew", padx=SPACING.sm, pady=SPACING.md)
        ctk.CTkLabel(frame, text=label, text_color=PALETTE.text_muted, font=font(10, weight="bold"), anchor="w").pack(fill="x", pady=(0, 3))
        entry = ctk.CTkEntry(frame, placeholder_text=placeholder)
        entry.pack(fill="x")
        entry.bind("<Return>", lambda _event: self._render())
        return entry

    def _mode_changed(self, selected: str) -> None:
        self.mode = "raw" if selected == "Raw Row Events" else "grouped"
        self._render()

    def _render(self) -> None:
        current_field = self.field_combo.get()
        current_user = self.user_combo.get()
        model = self.app_state.operational_history_model(
            mode=self.mode,
            field_name=current_field,
            user=current_user,
            start_date=self.start_entry.get(),
            end_date=self.end_entry.get(),
            search=self.search_entry.get(),
        )
        set_combo_values(self.field_combo, model.fields, selected=current_field)
        set_combo_values(self.user_combo, model.users, selected=current_user)

        _clear_frame(self.table_host)
        _clear_frame(self.detail_host)
        if self.mode == "grouped":
            summary = f"{model.matching_count} grouped event{'s' if model.matching_count != 1 else ''} representing {model.source_event_count} raw LOG_HISTORY row{'s' if model.source_event_count != 1 else ''}."
        else:
            summary = f"{model.matching_count} raw LOG_HISTORY event{'s' if model.matching_count != 1 else ''}."
        if model.input_warning:
            summary += f"  {model.input_warning}"
        self.summary_label.configure(text=summary, text_color=PALETTE.warning if model.input_warning else PALETTE.text_muted)

        table = DataTable(
            self.table_host,
            visible_columns=HISTORY_COLUMNS,
            height=15,
            sort_keys={"Timestamp": "_TimestampSort"},
            empty_message=model.empty_message or "No history events are available.",
            on_select=self._show_event_detail,
        )
        table.grid(row=0, column=0, sticky="nsew")
        table.set_dataframe(model.rows)
        self.history_table = table
        if model.rows.empty:
            StatePanel(
                self.detail_host,
                "No event selected",
                model.empty_message or "Select an event to inspect its context.",
                kind="empty",
            ).grid(row=0, column=0, sticky="ew")
        else:
            self._show_event_detail(None)

    def _show_event_detail(self, row: pd.Series | None) -> None:
        _clear_frame(self.detail_host)
        if row is None:
            ctk.CTkLabel(self.detail_host, text="Select an event to see its complete audit context.", text_color=PALETTE.text_muted, font=font(10), anchor="w").grid(row=0, column=0, sticky="ew")
            return
        panel = ctk.CTkFrame(self.detail_host, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=10)
        panel.grid(row=0, column=0, sticky="ew")
        panel.grid_columnconfigure(1, weight=1)
        title = f"{row.get('Field', 'Value')} · {row.get('Vessel', '—')} / {row.get('Voyage', '—')}"
        ctk.CTkLabel(panel, text=title, text_color=PALETTE.text, font=font(13, weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=SPACING.md, pady=(SPACING.md, SPACING.xs)
        )
        description = f"{row.get('Old Value', '—')}  →  {row.get('New Value', '—')}"
        ctk.CTkLabel(panel, text=description, text_color=PALETTE.text, font=font(12), anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=SPACING.md
        )
        context = f"{row.get('Timestamp', '—')} · User: {row.get('User', '—')} · Booking: {row.get('Booking number', '—')} · {row.get('Mode', '')}"
        if int(pd.to_numeric(pd.Series([row.get("Raw Events", 1)]), errors="coerce").fillna(1).iloc[0]) > 1:
            context += f" · Represents {row.get('Raw Events')} raw events"
        ctk.CTkLabel(panel, text=context, text_color=PALETTE.text_muted, font=font(10), anchor="w", wraplength=900, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=SPACING.md, pady=(SPACING.xs, 2)
        )
        diagnostic = f"Historical event: RowID {row.get('RowID', '—')} · BlockID {row.get('BlockID', '—')}"
        ctk.CTkLabel(panel, text=diagnostic, text_color=PALETTE.text_soft, font=font(9), anchor="w").grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=SPACING.md, pady=(0, 2)
        )
        current_context = (
            f"Current context: {row.get('Current Vessel', '—')} / {row.get('Current Voyage', '—')} · "
            f"Week {row.get('Current Week', '—')} · BlockID {row.get('Current BlockID', '—')} · "
            f"Resolution: {row.get('Identity Resolution', '—')}"
        )
        ctk.CTkLabel(panel, text=current_context, text_color=PALETTE.text_soft, font=font(9), anchor="w").grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=SPACING.md, pady=(0, SPACING.md)
        )


def _clear_frame(frame: Any) -> None:
    for child in frame.winfo_children():
        child.destroy()
