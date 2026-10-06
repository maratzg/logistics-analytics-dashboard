from __future__ import annotations

from typing import Any

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from ..theme import CARD_RADIUS, PALETTE, SPACING, font


class ChartCard(ctk.CTkFrame):
    """Reusable responsive matplotlib host with loading and empty states."""

    def __init__(self, parent: Any, title: str, subtitle: str | None = None) -> None:
        super().__init__(parent, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=CARD_RADIUS)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.canvas: FigureCanvasTkAgg | None = None
        ctk.CTkLabel(self, text=title, text_color=PALETTE.text, font=font(14, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=SPACING.lg, pady=(SPACING.lg, 0)
        )
        self.subtitle = ctk.CTkLabel(self, text=subtitle or "", text_color=PALETTE.text_muted, font=font(10), anchor="w")
        self.subtitle.grid(row=1, column=0, sticky="ew", padx=SPACING.lg, pady=(2, SPACING.xs))
        self.state_label = ctk.CTkLabel(self, text="", text_color=PALETTE.text_muted, font=font(12))

    def new_figure(self, *, width: float = 5.8, height: float = 3.0) -> Figure:
        return Figure(figsize=(width, height), dpi=96, facecolor=PALETTE.surface, constrained_layout=True)

    def show_figure(self, figure: Figure) -> None:
        self._clear_body()
        self.canvas = FigureCanvasTkAgg(figure, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().grid(row=2, column=0, sticky="nsew", padx=SPACING.sm, pady=(0, SPACING.md))

    def show_empty(self, message: str = "No data is available for this view.") -> None:
        self._show_state(message)

    def show_loading(self) -> None:
        self._show_state("Loading chart…")

    @staticmethod
    def style_axis(axis: Any, *, value_label: str | None = None) -> None:
        axis.set_facecolor(PALETTE.surface)
        axis.tick_params(colors=PALETTE.text_muted, labelsize=9)
        axis.grid(color=PALETTE.chart_grid, alpha=0.6, linewidth=0.8)
        for spine in axis.spines.values():
            spine.set_color(PALETTE.border)
        if value_label:
            axis.set_ylabel(value_label, color=PALETTE.text_muted)

    def _show_state(self, text: str) -> None:
        self._clear_body()
        self.state_label.configure(text=text)
        self.state_label.grid(row=2, column=0, sticky="nsew", padx=SPACING.lg, pady=SPACING.xl)

    def _clear_body(self) -> None:
        self.state_label.grid_forget()
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None
