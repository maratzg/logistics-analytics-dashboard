from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ..theme import CARD_RADIUS, PALETTE, SPACING, font
from .status import DataQualityIndicator, SourceStatus


class GlobalHeader(ctk.CTkFrame):
    def __init__(self, parent: Any, refresh_command: Callable[[], None]) -> None:
        super().__init__(parent, fg_color=PALETTE.surface, corner_radius=0, border_width=0)
        self.grid_columnconfigure(0, weight=1)
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.grid(row=0, column=0, sticky="ew", padx=(SPACING.xl, SPACING.lg), pady=(SPACING.lg, SPACING.md))
        title_frame.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(title_frame, text="Dashboard", text_color=PALETTE.text, font=font(22, weight="bold"), anchor="w")
        self.title_label.grid(row=0, column=0, sticky="ew")
        self.subtitle_label = ctk.CTkLabel(title_frame, text="", text_color=PALETTE.text_muted, font=font(11), anchor="w")
        self.subtitle_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        self.quality = DataQualityIndicator(self)
        self.quality.grid(row=0, column=1, padx=(0, SPACING.lg), pady=SPACING.md)
        self.source_status = SourceStatus(self)
        self.source_status.grid(row=0, column=2, padx=(0, SPACING.lg), pady=SPACING.md)
        self.refresh_button = ctk.CTkButton(
            self,
            text="Refresh",
            width=104,
            height=36,
            command=refresh_command,
            fg_color=PALETTE.accent,
            hover_color=PALETTE.accent_hover,
            font=font(12, weight="bold"),
        )
        self.refresh_button.grid(row=0, column=3, sticky="e", padx=(0, SPACING.xl), pady=SPACING.lg)
        ctk.CTkFrame(self, height=1, fg_color=PALETTE.divider).grid(row=1, column=0, columnspan=4, sticky="ew")

    def set_page(self, title: str, subtitle: str) -> None:
        self.title_label.configure(text=title)
        self.subtitle_label.configure(text=subtitle)

    def set_refreshing(self, refreshing: bool) -> None:
        self.refresh_button.configure(state="disabled" if refreshing else "normal", text="Refreshing…" if refreshing else "Refresh")


class PageContainer(ctk.CTkFrame):
    def __init__(self, parent: Any, *, scrollable: bool = False) -> None:
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        if scrollable:
            self.body: Any = ctk.CTkScrollableFrame(self, fg_color="transparent")
            self.body.grid(row=0, column=0, sticky="nsew")
            self.body.grid_columnconfigure(0, weight=1)
        else:
            self.body = self


class SectionHeader(ctk.CTkFrame):
    def __init__(self, parent: Any, title: str, subtitle: str | None = None) -> None:
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, text_color=PALETTE.text, font=font(15, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew")
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, text_color=PALETTE.text_muted, font=font(11), anchor="w", justify="left").grid(
                row=1, column=0, sticky="ew", pady=(SPACING.xs, 0)
            )
