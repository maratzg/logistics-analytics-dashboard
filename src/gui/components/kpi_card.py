from __future__ import annotations

from typing import Any

import customtkinter as ctk
import pandas as pd

from ..theme import CARD_RADIUS, PALETTE, SPACING, font


def format_metric(value: Any, kind: str = "number", *, decimals: int | None = None) -> str:
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass

    normalized = kind.strip().casefold()
    if normalized == "text":
        return str(value)
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return str(value)
    number = float(numeric)
    if normalized in {"percent", "percentage"}:
        precision = 1 if decimals is None else decimals
        return f"{number * 100:.{precision}f}%"
    if normalized in {"days", "day"}:
        precision = 1 if decimals is None and not number.is_integer() else (0 if decimals is None else decimals)
        sign = "+" if number > 0 else ""
        return f"{sign}{number:,.{precision}f} d"
    if normalized in {"weight", "gwt"}:
        precision = 1 if decimals is None else decimals
        return f"{number:,.{precision}f}"
    precision = 0 if decimals is None and number.is_integer() else (2 if decimals is None else decimals)
    return f"{number:,.{precision}f}"


class KpiCard(ctk.CTkFrame):
    def __init__(
        self,
        parent: Any,
        title: str,
        value: Any = None,
        *,
        kind: str = "number",
        secondary: str | None = None,
        delta: str | None = None,
        help_text: str | None = None,
    ) -> None:
        super().__init__(
            parent,
            fg_color=PALETTE.surface,
            border_width=1,
            border_color=PALETTE.border,
            corner_radius=CARD_RADIUS,
        )
        self.kind = kind
        self.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(self, text=title, text_color=PALETTE.text_muted, font=font(12), anchor="w")
        self.title_label.grid(row=0, column=0, sticky="ew", padx=SPACING.lg, pady=(SPACING.lg, SPACING.xs))
        self.value_label = ctk.CTkLabel(self, text="", text_color=PALETTE.text, font=font(24, weight="bold"), anchor="w")
        self.value_label.grid(row=1, column=0, sticky="ew", padx=SPACING.lg)
        self.context_label = ctk.CTkLabel(
            self,
            text=secondary or delta or "",
            text_color=PALETTE.text_muted,
            font=font(11),
            anchor="w",
        )
        self.context_label.grid(row=2, column=0, sticky="ew", padx=SPACING.lg, pady=(SPACING.xs, SPACING.sm))
        self.help_label = ctk.CTkLabel(
            self,
            text=help_text or "",
            text_color=PALETTE.text_soft,
            font=font(10),
            anchor="w",
            justify="left",
            wraplength=250,
        )
        if help_text:
            self.help_label.grid(row=3, column=0, sticky="ew", padx=SPACING.lg, pady=(0, SPACING.md))
        self.set_value(value, secondary=secondary, delta=delta)

    def set_value(
        self,
        value: Any,
        *,
        secondary: str | None = None,
        delta: str | None = None,
        loading: bool = False,
        unavailable_text: str = "Unavailable",
    ) -> None:
        if loading:
            display = "Loading…"
            color = PALETTE.text_muted
        else:
            display = format_metric(value, self.kind)
            color = PALETTE.text if display != "—" else PALETTE.text_soft
            if display == "—" and unavailable_text:
                display = unavailable_text
        self.value_label.configure(text=display, text_color=color)
        context = delta if delta is not None else secondary
        self.context_label.configure(text=context or "")
