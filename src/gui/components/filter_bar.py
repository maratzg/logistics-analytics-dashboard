from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk
import pandas as pd

from src.analytical_filters import FilterContext

from ..filter_state import ALL_FILTER_VALUE, FILTER_SPECS, FilterSelectionState, faceted_filter_options
from ..theme import CARD_RADIUS, PALETTE, SPACING, font


class AnalyticalFilterBar(ctk.CTkFrame):
    def __init__(self, parent: Any, on_change: Callable[[FilterContext], None]) -> None:
        super().__init__(parent, fg_color=PALETTE.surface, corner_radius=0, border_width=0)
        self.on_change = on_change
        self.selection = FilterSelectionState()
        self.dataframe = pd.DataFrame()
        self.controls: dict[str, ctk.CTkComboBox] = {}
        self.more_visible = False
        self.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.md, SPACING.sm))
        top.grid_columnconfigure(0, weight=1)
        self.active_label = ctk.CTkLabel(top, text="No active filters", text_color=PALETTE.text_muted, font=font(11), anchor="w")
        self.active_label.grid(row=0, column=0, sticky="ew")
        self.more_button = ctk.CTkButton(
            top,
            text="More filters",
            command=self.toggle_more,
            width=104,
            height=28,
            fg_color="transparent",
            text_color=PALETTE.accent,
            hover_color=PALETTE.accent_soft,
            border_width=0,
            font=font(11, weight="bold"),
        )
        self.more_button.grid(row=0, column=1, padx=SPACING.sm)
        self.clear_button = ctk.CTkButton(
            top,
            text="Clear",
            command=self.clear,
            width=66,
            height=28,
            fg_color="transparent",
            text_color=PALETTE.text_muted,
            hover_color=PALETTE.surface_subtle,
            border_width=1,
            border_color=PALETTE.border,
            font=font(11),
        )
        self.clear_button.grid(row=0, column=2)

        self.primary_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.primary_frame.grid(row=1, column=0, sticky="ew", padx=SPACING.xl, pady=(0, SPACING.md))
        self.more_frame = ctk.CTkFrame(self, fg_color=PALETTE.surface_subtle, corner_radius=CARD_RADIUS)

        primary_specs = [spec for spec in FILTER_SPECS if spec.primary]
        more_specs = [spec for spec in FILTER_SPECS if not spec.primary]
        self._build_controls(self.primary_frame, primary_specs, columns=4)
        self._build_controls(self.more_frame, more_specs, columns=4)
        ctk.CTkFrame(self, height=1, fg_color=PALETTE.divider).grid(row=3, column=0, sticky="ew")
        self.refresh_options()

    @property
    def context(self) -> FilterContext:
        return self.selection.to_context()

    def set_dataframe(self, dataframe: pd.DataFrame, *, preserve_selection: bool = True) -> None:
        self.dataframe = dataframe.copy()
        if not preserve_selection:
            self.selection.reset()
        self.refresh_options(notify=True)

    def clear(self) -> None:
        self.selection.reset()
        self.refresh_options(notify=True)

    def toggle_more(self) -> None:
        self.more_visible = not self.more_visible
        if self.more_visible:
            self.more_frame.grid(row=2, column=0, sticky="ew", padx=SPACING.xl, pady=(0, SPACING.md))
            self.more_button.configure(text="Fewer filters")
        else:
            self.more_frame.grid_remove()
            self.more_button.configure(text="More filters")

    def set_loading(self, loading: bool) -> None:
        state = "disabled" if loading else "readonly"
        for control in self.controls.values():
            control.configure(state=state)
        self.clear_button.configure(state="disabled" if loading or not self.selection.is_active else "normal")
        self.more_button.configure(state="disabled" if loading else "normal")

    def refresh_options(self, *, notify: bool = False) -> None:
        options = faceted_filter_options(self.dataframe, self.selection)
        if self.selection.reconcile(options):
            options = faceted_filter_options(self.dataframe, self.selection)
        for spec in FILTER_SPECS:
            control = self.controls[spec.key]
            values = options.get(spec.key) or [ALL_FILTER_VALUE]
            selected = self.selection.value(spec.key)
            display = next(
                (value for value in values if selected is not None and value.casefold() == str(selected).casefold()),
                ALL_FILTER_VALUE,
            )
            control.configure(values=values)
            control.set(display)
        count = self.selection.active_count
        self.active_label.configure(
            text="No active filters" if count == 0 else f"{count} active filter{'s' if count != 1 else ''}",
            text_color=PALETTE.accent if count else PALETTE.text_muted,
        )
        self.clear_button.configure(state="normal" if count else "disabled")
        if notify:
            self.on_change(self.context)

    def _build_controls(self, parent: ctk.CTkFrame, specs: list[Any], *, columns: int) -> None:
        for column in range(columns):
            parent.grid_columnconfigure(column, weight=1, uniform="filters")
        for index, spec in enumerate(specs):
            container = ctk.CTkFrame(parent, fg_color="transparent")
            container.grid(row=index // columns, column=index % columns, sticky="ew", padx=SPACING.xs, pady=SPACING.xs)
            container.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(container, text=spec.label, text_color=PALETTE.text_muted, font=font(10, weight="bold"), anchor="w").grid(
                row=0, column=0, sticky="ew", pady=(0, 3)
            )
            combo = ctk.CTkComboBox(
                container,
                values=[ALL_FILTER_VALUE],
                command=lambda value, key=spec.key: self._selected(key, value),
                height=32,
                border_width=1,
                border_color=PALETTE.border,
                fg_color=PALETTE.surface,
                button_color=PALETTE.surface,
                button_hover_color=PALETTE.accent_soft,
                text_color=PALETTE.text,
                dropdown_fg_color=PALETTE.surface,
                dropdown_text_color=PALETTE.text,
                dropdown_hover_color=PALETTE.accent_soft,
                font=font(11),
                dropdown_font=font(11),
                state="readonly",
            )
            combo.set(ALL_FILTER_VALUE)
            combo.grid(row=1, column=0, sticky="ew")
            self.controls[spec.key] = combo

    def _selected(self, key: str, value: str) -> None:
        self.selection.set_value(key, value)
        self.refresh_options(notify=True)
