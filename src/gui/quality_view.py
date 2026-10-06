from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
import pandas as pd

from src.analytical_filters import FilterContext
from src.app_state import ApplicationState

from .components.data_table import DataTable
from .components.empty_state import StatePanel
from .components.kpi_card import KpiCard
from .components.layout import SectionHeader
from .exporting import export_visible_csv
from .secondary_models import identity_for_quality_issue
from .theme import PALETTE, SPACING, font


QUALITY_COLUMNS = ["Severity", "Category", "Message", "Vessel", "Voyage", "Week", "Booking number", "Field", "Raw Value"]


class DataQualityView(ctk.CTkFrame):
    """Actionable, read-only presentation of Phase C structured quality issues."""

    def __init__(
        self,
        parent: Any,
        state: ApplicationState,
        *,
        on_open_voyage: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app_state = state
        self.on_open_voyage = on_open_voyage
        self.filter_context = FilterContext()
        self.current_rows = pd.DataFrame()
        self.selected_issue: pd.Series | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.md, SPACING.sm))
        controls.grid_columnconfigure(2, weight=1)
        self.severity_combo = _combo(controls, "Severity", 0, self._filters_changed)
        self.category_combo = _combo(controls, "Category", 1, self._filters_changed, width=230)
        search_host = ctk.CTkFrame(controls, fg_color="transparent")
        search_host.grid(row=0, column=2, sticky="ew", padx=SPACING.sm)
        search_host.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(search_host, text="Search", text_color=PALETTE.text_muted, font=font(10), anchor="w").grid(row=0, column=0, sticky="ew")
        self.search_entry = ctk.CTkEntry(search_host, placeholder_text="Message, voyage, booking, field, raw value…")
        self.search_entry.grid(row=1, column=0, sticky="ew", pady=(SPACING.xs, 0))
        self.search_entry.bind("<Return>", lambda _event: self._filters_changed())
        ctk.CTkButton(search_host, text="Search", command=self._filters_changed, width=78).grid(row=1, column=1, padx=(SPACING.sm, 0), pady=(SPACING.xs, 0))
        ctk.CTkButton(controls, text="Clear", command=self._clear_filters, width=72, fg_color=PALETTE.surface_subtle,
                      hover_color=PALETTE.accent_soft, text_color=PALETTE.text).grid(row=0, column=3, sticky="s", padx=SPACING.xs)
        ctk.CTkButton(controls, text="Export", command=self._export, width=82, fg_color=PALETTE.surface_subtle,
                      hover_color=PALETTE.accent_soft, text_color=PALETTE.text).grid(row=0, column=4, sticky="s", padx=(SPACING.xs, 0))

        self.summary = ctk.CTkFrame(self, fg_color="transparent")
        self.summary.grid(row=1, column=0, sticky="ew", padx=SPACING.xl, pady=(0, SPACING.md))
        for column in range(6):
            self.summary.grid_columnconfigure(column, weight=1, uniform="quality-kpi")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=SPACING.xl, pady=(0, SPACING.xl))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(1, weight=1)

    def set_filter_context(self, context: FilterContext) -> None:
        self.filter_context = context

    def refresh_view(self) -> None:
        unfiltered = self.app_state.data_quality_page_model()
        _set_options(self.severity_combo, unfiltered.severities)
        _set_options(self.category_combo, unfiltered.categories)
        self._render_filtered()

    def _filters_changed(self, *_: Any) -> None:
        self._render_filtered()

    def _clear_filters(self) -> None:
        self.severity_combo.set("All")
        self.category_combo.set("All")
        self.search_entry.delete(0, "end")
        self._render_filtered()

    def _render_filtered(self) -> None:
        model = self.app_state.data_quality_page_model(
            severity=self.severity_combo.get(),
            category=self.category_combo.get(),
            search=self.search_entry.get(),
        )
        self.current_rows = model.rows
        self.selected_issue = None
        self._render_summary(model)
        _clear(self.body)
        SectionHeader(
            self.body,
            "Issues requiring attention",
            f"{len(model.rows):,} visible of {model.scope_count:,} issues in the shared filter scope. Python reports issues but never repairs Excel.",
        ).grid(row=0, column=0, sticky="ew", pady=(SPACING.sm, SPACING.md))
        content = ctk.CTkFrame(self.body, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)
        table = DataTable(
            content,
            visible_columns=QUALITY_COLUMNS,
            height=18,
            empty_message=model.empty_message or "No issues match these filters.",
            on_select=self._select_issue,
            on_activate=self._activate_issue,
        )
        table.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.sm))
        table.set_dataframe(model.rows)
        self.issue_table = table
        self.detail_host = ctk.CTkFrame(content, fg_color="transparent")
        self.detail_host.grid(row=0, column=1, sticky="nsew", padx=(SPACING.sm, 0))
        self._render_detail(None)

    def _render_summary(self, model: Any) -> None:
        _clear(self.summary)
        values = [
            ("Critical", model.counts.get("Critical", 0), "Immediate review"),
            ("Warning", model.counts.get("Warning", 0), "Needs attention"),
            ("Information", model.counts.get("Information", 0), "Review context"),
            ("Total issues", len(model.rows), "Current local filters"),
            ("Affected rows", model.affected_rows, "Distinct RowIDs"),
            ("Affected voyages", model.affected_voyages, "Complete safe identities"),
        ]
        for index, (title, value, secondary) in enumerate(values):
            KpiCard(self.summary, title, value, secondary=secondary).grid(row=0, column=index, sticky="nsew", padx=SPACING.xs)

    def _select_issue(self, issue: pd.Series | None) -> None:
        self.selected_issue = issue
        self._render_detail(issue)

    def _activate_issue(self, issue: pd.Series) -> None:
        identity = identity_for_quality_issue(issue)
        if identity and self.on_open_voyage is not None:
            self.on_open_voyage(identity)
        else:
            self._select_issue(issue)

    def _render_detail(self, issue: pd.Series | None) -> None:
        _clear(self.detail_host)
        if issue is None:
            StatePanel(self.detail_host, "Select an issue", "Choose a row to see its explanation, source context, and suggested correction.", kind="information").pack(fill="x")
            return
        identity = identity_for_quality_issue(issue)
        panel = ctk.CTkFrame(self.detail_host, fg_color=PALETTE.surface, border_width=1, border_color=PALETTE.border, corner_radius=10)
        panel.pack(fill="both", expand=True)
        ctk.CTkLabel(panel, text=str(issue.get("Severity", "Issue")), text_color=_severity_color(issue.get("Severity")), font=font(12, weight="bold"), anchor="w").pack(fill="x", padx=SPACING.lg, pady=(SPACING.lg, SPACING.xs))
        ctk.CTkLabel(panel, text=str(issue.get("Category", "Data quality")), text_color=PALETTE.text, font=font(18, weight="bold"), anchor="w", wraplength=350, justify="left").pack(fill="x", padx=SPACING.lg)
        ctk.CTkLabel(panel, text=str(issue.get("Message", "Review the source value.")), text_color=PALETTE.text_muted, font=font(11), anchor="w", wraplength=350, justify="left").pack(fill="x", padx=SPACING.lg, pady=(SPACING.sm, SPACING.md))
        for label, value in [
            ("Affected entity", _entity_text(issue)),
            ("Field", _shown(issue.get("Field"))),
            ("Raw value", _shown(issue.get("Raw Value"))),
            ("Booking", _shown(issue.get("Booking number"))),
            ("Suggested correction", _shown(issue.get("Suggested Correction"))),
            ("RowID", _shown(issue.get("RowID"))),
            ("BlockID", _shown(issue.get("BlockID"))),
        ]:
            host = ctk.CTkFrame(panel, fg_color="transparent")
            host.pack(fill="x", padx=SPACING.lg, pady=SPACING.xs)
            ctk.CTkLabel(host, text=label, text_color=PALETTE.text_soft, font=font(9), anchor="w").pack(fill="x")
            ctk.CTkLabel(host, text=value, text_color=PALETTE.text, font=font(11), anchor="w", wraplength=350, justify="left").pack(fill="x")
        button = ctk.CTkButton(panel, text="Open related voyage", command=lambda: self._open_identity(identity), state="normal" if identity else "disabled")
        button.pack(anchor="w", padx=SPACING.lg, pady=SPACING.lg)

    def _open_identity(self, identity: str | None) -> None:
        if identity and self.on_open_voyage is not None:
            self.on_open_voyage(identity)

    def _export(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="Export data-quality issues", initialfile="data_quality_issues.csv", defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        columns = QUALITY_COLUMNS + ["Suggested Correction", "RowID", "BlockID"]
        result = export_visible_csv(self.current_rows, Path(path), visible_columns=columns)
        if result.success:
            messagebox.showinfo("Export complete", result.message, parent=self)
        else:
            messagebox.showwarning("Nothing to export", result.message, parent=self)


def _combo(parent: Any, label: str, column: int, command: Callable[..., None], *, width: int = 150) -> ctk.CTkComboBox:
    host = ctk.CTkFrame(parent, fg_color="transparent")
    host.grid(row=0, column=column, sticky="w", padx=(0, SPACING.sm))
    ctk.CTkLabel(host, text=label, text_color=PALETTE.text_muted, font=font(10), anchor="w").pack(fill="x")
    combo = ctk.CTkComboBox(host, values=["All"], command=command, width=width)
    combo.set("All")
    combo.pack(fill="x", pady=(SPACING.xs, 0))
    return combo


def _set_options(combo: ctk.CTkComboBox, options: list[str]) -> None:
    current = combo.get()
    combo.configure(values=options or ["All"])
    combo.set(current if current in options else "All")


def _severity_color(value: Any) -> str:
    normalized = str(value).strip().casefold()
    return {"critical": PALETTE.danger, "warning": PALETTE.warning, "information": PALETTE.accent}.get(normalized, PALETTE.text)


def _entity_text(issue: pd.Series) -> str:
    parts = [_shown(issue.get("Vessel")), _shown(issue.get("Voyage")), f"Week {_shown(issue.get('Week'))}"]
    return " · ".join(parts)


def _shown(value: Any) -> str:
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text and text.casefold() not in {"none", "nan", "nat"} else "—"


def _clear(parent: Any) -> None:
    for child in parent.winfo_children():
        child.destroy()
