from __future__ import annotations

from dataclasses import fields
from typing import Any

import customtkinter as ctk

from src.analytical_filters import FilterContext, apply_current_filters
from src.app_state import ApplicationState

from .components.empty_state import StatePanel
from .theme import PALETTE, SPACING, font


PLACEHOLDER_COPY = {
    "Service Analytics": (
        "Service analytics content arrives in Phase F",
        "The navigation route, shared filters, responsive page host, status system, and Phase C service data are ready. Full analytical composition is intentionally deferred.",
    ),
    "Customers": (
        "Customer analytics content arrives in Phase F",
        "The foundation preserves customer-safe grouping and shared filters. Charts and customer drilldowns are intentionally not being implemented in Phase D.",
    ),
    "Data Quality": (
        "Full data-quality page arrives in Phase F",
        "Critical, Warning, and Information issue counts are already available in the global header. The detailed issue workflow is intentionally deferred.",
    ),
}


class FoundationPlaceholderView(ctk.CTkFrame):
    """Honest Phase D route placeholder; it performs no page-level analytics."""

    def __init__(self, parent: Any, state: ApplicationState, route: str) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app_state = state
        self.route = route
        self.filter_context = FilterContext()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.scope_label = ctk.CTkLabel(self, text="", text_color=PALETTE.text_muted, font=font(11), anchor="w")
        self.scope_label.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.xl, SPACING.md))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.xl))
        self.body.grid_columnconfigure(0, weight=1)

    def set_filter_context(self, context: FilterContext) -> None:
        self.filter_context = context

    def refresh_view(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        if self.app_state.data is None:
            self.scope_label.configure(text="No workbook snapshot available")
            panel = StatePanel(
                self.body,
                "Workbook not loaded",
                "Select a valid workbook in Settings. This page will continue to use the same read-only source and refresh behavior.",
                kind="empty",
            )
        else:
            scoped = apply_current_filters(self.app_state.data.weekly_df, self.filter_context)
            active = sum(getattr(self.filter_context, item.name) is not None for item in fields(FilterContext))
            self.scope_label.configure(text=f"Shared filter scope: {len(scoped):,} operational rows · {active} active filters")
            title, message = PLACEHOLDER_COPY[self.route]
            panel = StatePanel(self.body, title, message, kind="information")
        panel.grid(row=0, column=0, sticky="ew")
