from __future__ import annotations

from typing import Any

import customtkinter as ctk
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .theme import CARD_RADIUS, PALETTE, SPACING, font


CHART_FACE = PALETTE.surface
AXIS_FACE = PALETTE.surface
TEXT_COLOR = PALETTE.text_muted
GRID_COLOR = PALETTE.chart_grid
BAR_COLOR = PALETTE.accent
ALT_COLORS = [PALETTE.accent, "#5A91A7", "#8CB2C2", "#46697A"]


def chart_card(parent: Any, title: str, empty_message: str) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(parent, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=CARD_RADIUS)
    frame.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(frame, text=title, text_color=PALETTE.text, font=font(14, weight="bold")).grid(
        row=0,
        column=0,
        sticky="w",
        padx=SPACING.lg,
        pady=(SPACING.lg, 2),
    )
    ctk.CTkLabel(frame, text=empty_message, text_color=PALETTE.text_muted, wraplength=420, justify="left", font=font(11)).grid(
        row=1,
        column=0,
        sticky="w",
        padx=14,
        pady=(8, 14),
    )
    return frame


def bar_chart_card(
    parent: Any,
    title: str,
    data: pd.DataFrame,
    *,
    label_column: str = "Label",
    value_column: str = "Value",
    empty_message: str,
    horizontal: bool = True,
    signed: bool = False,
    allow_all_zero: bool = False,
) -> ctk.CTkFrame:
    if _empty_chart_data(data, label_column, value_column, allow_all_zero=allow_all_zero):
        return chart_card(parent, title, empty_message)

    frame = _figure_card(parent, title)
    figure = _figure()
    axis = figure.add_subplot(111)
    _style_axis(axis)

    labels = data[label_column].astype(str).tolist()
    values = pd.to_numeric(data[value_column], errors="coerce").fillna(0.0).tolist()
    colors = [_bar_color(value, signed=signed) for value in values]

    if horizontal:
        labels_plot = labels[::-1]
        values_plot = values[::-1]
        colors_plot = colors[::-1]
        axis.barh(labels_plot, values_plot, color=colors_plot)
        axis.set_xlabel(value_column, color=TEXT_COLOR)
    else:
        axis.bar(labels, values, color=colors)
        axis.tick_params(axis="x", rotation=35)
        axis.set_ylabel(value_column, color=TEXT_COLOR)

    if signed:
        axis.axvline(0, color=GRID_COLOR, linewidth=1)
    axis.grid(axis="x" if horizontal else "y", color=GRID_COLOR, alpha=0.45, linewidth=0.8)
    _embed(frame, figure)
    return frame


def line_chart_card(
    parent: Any,
    title: str,
    data: pd.DataFrame,
    *,
    label_column: str,
    value_column: str,
    empty_message: str,
) -> ctk.CTkFrame:
    if _empty_chart_data(data, label_column, value_column, allow_all_zero=False):
        return chart_card(parent, title, empty_message)

    frame = _figure_card(parent, title)
    figure = _figure()
    axis = figure.add_subplot(111)
    _style_axis(axis)
    labels = data[label_column].astype(str).tolist()
    values = pd.to_numeric(data[value_column], errors="coerce").fillna(0.0).tolist()
    axis.plot(labels, values, marker="o", color=BAR_COLOR, linewidth=2)
    axis.tick_params(axis="x", rotation=35)
    axis.set_ylabel(value_column, color=TEXT_COLOR)
    axis.grid(axis="y", color=GRID_COLOR, alpha=0.45, linewidth=0.8)
    _embed(frame, figure)
    return frame


def grouped_bar_chart_card(
    parent: Any,
    title: str,
    data: pd.DataFrame,
    *,
    label_column: str,
    metric_columns: list[str],
    empty_message: str,
) -> ctk.CTkFrame:
    if data.empty or label_column not in data.columns or not any(column in data.columns for column in metric_columns):
        return chart_card(parent, title, empty_message)

    usable = data[[label_column] + [column for column in metric_columns if column in data.columns]].copy()
    for column in metric_columns:
        if column in usable.columns:
            usable[column] = pd.to_numeric(usable[column], errors="coerce").fillna(0.0)
    metric_columns = [column for column in metric_columns if column in usable.columns]
    if not metric_columns or usable[metric_columns].abs().sum().sum() == 0:
        return chart_card(parent, title, empty_message)

    frame = _figure_card(parent, title)
    figure = _figure(width=6.4, height=3.2)
    axis = figure.add_subplot(111)
    _style_axis(axis)

    labels = usable[label_column].astype(str).tolist()
    x_positions = list(range(len(labels)))
    bar_width = min(0.8 / len(metric_columns), 0.28)
    center_shift = (len(metric_columns) - 1) * bar_width / 2
    for index, column in enumerate(metric_columns):
        positions = [position - center_shift + index * bar_width for position in x_positions]
        axis.bar(positions, usable[column].tolist(), width=bar_width, label=column, color=ALT_COLORS[index % len(ALT_COLORS)])

    axis.set_xticks(x_positions)
    axis.set_xticklabels(labels, rotation=30, ha="right")
    axis.set_ylabel("Revisions", color=TEXT_COLOR)
    axis.legend(facecolor=AXIS_FACE, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)
    axis.grid(axis="y", color=GRID_COLOR, alpha=0.45, linewidth=0.8)
    _embed(frame, figure)
    return frame


def _figure_card(parent: Any, title: str) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(parent, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=CARD_RADIUS)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(1, weight=1)
    ctk.CTkLabel(frame, text=title, text_color=PALETTE.text, font=font(14, weight="bold")).grid(
        row=0,
        column=0,
        sticky="w",
        padx=SPACING.lg,
        pady=(SPACING.lg, 0),
    )
    return frame


def _figure(*, width: float = 5.8, height: float = 3.0) -> Figure:
    return Figure(figsize=(width, height), dpi=96, facecolor=CHART_FACE, constrained_layout=True)


def _style_axis(axis: Any) -> None:
    axis.set_facecolor(AXIS_FACE)
    axis.tick_params(colors=TEXT_COLOR, labelsize=9)
    axis.xaxis.label.set_color(TEXT_COLOR)
    axis.yaxis.label.set_color(TEXT_COLOR)
    for spine in axis.spines.values():
        spine.set_color(PALETTE.border)


def _embed(parent: Any, figure: Figure) -> None:
    canvas = FigureCanvasTkAgg(figure, master=parent)
    canvas.draw()
    canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 10))


def _empty_chart_data(
    data: pd.DataFrame,
    label_column: str,
    value_column: str,
    *,
    allow_all_zero: bool,
) -> bool:
    if data.empty or label_column not in data.columns or value_column not in data.columns:
        return True
    values = pd.to_numeric(data[value_column], errors="coerce").fillna(0.0)
    return not allow_all_zero and bool(values.abs().sum() == 0)


def _bar_color(value: float, *, signed: bool) -> str:
    if not signed:
        return BAR_COLOR
    if value < 0:
        return PALETTE.warning
    return BAR_COLOR
