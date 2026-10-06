from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ..theme import CARD_RADIUS, PALETTE, SPACING, font, status_colors


STATE_SYMBOLS = {
    "empty": "—",
    "loading": "…",
    "warning": "!",
    "error": "×",
    "information": "i",
}


class StatePanel(ctk.CTkFrame):
    def __init__(
        self,
        parent: Any,
        title: str,
        message: str,
        *,
        kind: str = "empty",
        action_label: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        background, accent = status_colors("neutral" if kind == "empty" else kind)
        super().__init__(parent, fg_color=background, border_width=1, border_color=PALETTE.border, corner_radius=CARD_RADIUS)
        self.grid_columnconfigure(1, weight=1)
        symbol = STATE_SYMBOLS.get(kind, "—")
        ctk.CTkLabel(self, text=symbol, text_color=accent, font=font(18, weight="bold"), width=34).grid(
            row=0, column=0, rowspan=2, padx=(SPACING.lg, SPACING.md), pady=SPACING.lg
        )
        ctk.CTkLabel(self, text=title, text_color=PALETTE.text, font=font(14, weight="bold"), anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(0, SPACING.lg), pady=(SPACING.lg, SPACING.xs)
        )
        ctk.CTkLabel(self, text=message, text_color=PALETTE.text_muted, font=font(12), anchor="w", justify="left", wraplength=720).grid(
            row=1, column=1, sticky="ew", padx=(0, SPACING.lg), pady=(0, SPACING.lg)
        )
        if action_label and action:
            ctk.CTkButton(
                self,
                text=action_label,
                command=action,
                fg_color=PALETTE.accent,
                hover_color=PALETTE.accent_hover,
                width=112,
            ).grid(row=0, column=2, rowspan=2, padx=(0, SPACING.lg), pady=SPACING.lg)
