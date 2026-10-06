from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import customtkinter as ctk
import pandas as pd

from ..theme import CARD_RADIUS, PALETTE, SPACING, font, status_colors


@dataclass(frozen=True, slots=True)
class SourceStatusModel:
    label: str
    kind: str
    workbook_filename: str
    last_refresh: datetime | None
    detail: str
    has_snapshot: bool


def source_status_model(state: Any, *, refreshing: bool = False) -> SourceStatusModel:
    filename = getattr(state, "workbook_filename", "Not configured")
    last_refresh = getattr(state, "last_loaded", None)
    has_snapshot = getattr(state, "data", None) is not None
    load_status = str(getattr(state, "load_status", "Not loaded"))
    health = getattr(getattr(state, "health", None), "status", None)
    health_value = str(getattr(health, "value", health or "")).casefold()

    if refreshing:
        return SourceStatusModel("Refreshing", "refreshing", filename, last_refresh, "Reading the workbook safely", has_snapshot)
    if "failed" in load_status.casefold() and has_snapshot:
        return SourceStatusModel("Warning", "warning", filename, last_refresh, "Showing the last successful snapshot", True)
    if "warning" in load_status.casefold() or "warning" in health_value:
        return SourceStatusModel("Warning", "warning", filename, last_refresh, "Loaded with workbook warnings", has_snapshot)
    if any(token in health_value for token in ["not_configured", "file_not_found", "invalid", "load_error"]) or "failed" in load_status.casefold():
        label = "Not configured" if "not_configured" in health_value else "Error"
        return SourceStatusModel(label, "neutral" if label == "Not configured" else "error", filename, last_refresh, load_status, has_snapshot)
    if has_snapshot:
        return SourceStatusModel("Ready", "ready", filename, last_refresh, "Read-only source connected", True)
    return SourceStatusModel("Not loaded", "neutral", filename, last_refresh, load_status, False)


def quality_issue_counts(frame: pd.DataFrame | None) -> dict[str, int]:
    counts = {"Critical": 0, "Warning": 0, "Information": 0}
    if frame is None or frame.empty or "Severity" not in frame.columns:
        return counts
    normalized = frame["Severity"].astype(str).str.strip().str.casefold().value_counts()
    for label in counts:
        counts[label] = int(normalized.get(label.casefold(), 0))
    return counts


class StatusBadge(ctk.CTkLabel):
    def __init__(self, parent: Any, text: str = "Not loaded", *, kind: str = "neutral") -> None:
        background, foreground = status_colors(kind)
        super().__init__(
            parent,
            text=text,
            fg_color=background,
            text_color=foreground,
            corner_radius=10,
            height=24,
            padx=10,
            font=font(11, weight="bold"),
        )

    def set_status(self, text: str, kind: str) -> None:
        background, foreground = status_colors(kind)
        self.configure(text=text, fg_color=background, text_color=foreground)


class SourceStatus(ctk.CTkFrame):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.badge = StatusBadge(self)
        self.badge.grid(row=0, column=0, sticky="e")
        self.filename = ctk.CTkLabel(self, text="", text_color=PALETTE.text, font=font(12, weight="bold"), anchor="e")
        self.filename.grid(row=1, column=0, sticky="e", pady=(SPACING.xs, 0))
        self.detail = ctk.CTkLabel(self, text="", text_color=PALETTE.text_muted, font=font(10), anchor="e")
        self.detail.grid(row=2, column=0, sticky="e")

    def update_model(self, model: SourceStatusModel) -> None:
        self.badge.set_status(model.label, model.kind)
        self.filename.configure(text=model.workbook_filename)
        refreshed = model.last_refresh.strftime("%d.%m.%Y %H:%M") if model.last_refresh else "Never refreshed"
        self.detail.configure(text=f"{refreshed} · {model.detail}")


class DataQualityIndicator(ctk.CTkFrame):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, fg_color=PALETTE.surface_subtle, corner_radius=CARD_RADIUS)
        self.labels: dict[str, ctk.CTkLabel] = {}
        for index, (name, color) in enumerate(
            [("Critical", PALETTE.danger), ("Warning", PALETTE.warning), ("Information", PALETTE.info)]
        ):
            label = ctk.CTkLabel(self, text=f"{name} 0", text_color=color, font=font(10, weight="bold"))
            label.grid(row=0, column=index, padx=(SPACING.sm if index else SPACING.md, SPACING.md), pady=SPACING.xs)
            self.labels[name] = label

    def update_counts(self, counts: dict[str, int]) -> None:
        for name, label in self.labels.items():
            label.configure(text=f"{name} {int(counts.get(name, 0))}")
