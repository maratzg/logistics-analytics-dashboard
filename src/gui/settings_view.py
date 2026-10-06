from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from src.app_state import ApplicationState
from src.system_actions import open_folder
from src.workbook_discovery import WorkbookDiscoveryResult, discover_workbooks
from src.workbook_health import WorkbookHealthStatus
from .theme import PALETTE
from .widgets import format_datetime


LOGGER = logging.getLogger(__name__)


class SettingsView(ctk.CTkFrame):
    def __init__(self, parent: Any, state: ApplicationState, *, on_state_changed: Callable[[str | None], None] | None = None) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app_state = state
        self.on_state_changed = on_state_changed
        self.discovery_result: WorkbookDiscoveryResult | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=18, pady=(16, 18))
        self.body.grid_columnconfigure(0, weight=1)

    def refresh_view(self) -> None:
        _clear_frame(self.body)
        model = self.app_state.settings_model()

        row = 0
        row = self._section(row, "Workbook")
        row = self._key_values(
            row,
            [
                ("Configured filename", model.configured_workbook_filename),
                ("Configured path", model.configured_workbook_path),
                ("File exists", "Yes" if model.workbook_exists else "No"),
                ("Load status", model.load_status),
                ("Health status", model.health_status.value),
                ("Last successful load", format_datetime(model.last_successful_load)),
            ],
        )
        row = self._actions(
            row,
            [
                ("Change Workbook", self.change_workbook),
                ("Validate Workbook", self.validate_workbook),
                ("Find Workbooks", self.find_workbooks),
            ],
        )

        if model.health_errors or model.health_warnings or model.config_errors:
            row = self._messages(row, "Health details", model.health_errors + model.config_errors, model.health_warnings + model.config_warnings)

        row = self._section(row, "Application")
        row = self._key_values(
            row,
            [
                ("Name", model.app_name),
                ("Version", model.app_version),
                ("Purpose", model.app_purpose),
                ("Expected workbook hint", model.expected_workbook_filename),
                ("User config file", str(model.user_config_path or "Not available")),
                ("Config folder", str(model.user_config_dir)),
                ("Log folder", str(model.log_dir)),
            ],
        )
        row = self._actions(
            row,
            [
                ("Open Config Folder", lambda: self.open_directory(model.user_config_dir, "config")),
                ("Open Log Folder", lambda: self.open_directory(model.log_dir, "log")),
            ],
        )
        if self.app_state.config.workbook_path is not None:
            self._actions(row, [("Open Workbook Folder", lambda: self.open_directory(self.app_state.config.workbook_path.parent, "workbook", create=False))])

        if self.discovery_result is not None:
            self._render_discovery_results(row + 1, self.discovery_result)

    def change_workbook(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select weekly operations workbook",
            filetypes=[
                ("Excel workbooks", "*.xlsm *.xlsx"),
                ("Macro-enabled workbook", "*.xlsm"),
                ("Excel workbook", "*.xlsx"),
            ],
        )
        if not selected:
            return
        self.use_workbook(Path(selected))

    def validate_workbook(self) -> None:
        try:
            health = self.app_state.validate_configured_workbook()
            self.refresh_view()
            title = "Workbook validation"
            if health.can_load:
                messagebox.showinfo(title, "Workbook validation completed successfully." if health.status == WorkbookHealthStatus.READY else "Workbook validation completed with warnings.")
            else:
                messagebox.showwarning(title, "\n".join(health.errors[:5]) or "Workbook validation failed.")
            self._notify_state_changed("Workbook validation completed.")
        except Exception:
            LOGGER.exception("Unexpected error during workbook validation")
            messagebox.showerror("Workbook validation", "Something went wrong while validating the workbook. Technical details were written to the application log.")

    def find_workbooks(self) -> None:
        try:
            result = discover_workbooks(expected_filename=self.app_state.config.expected_workbook_filename)
            self.discovery_result = result
            self.refresh_view()
            if len(result.candidates) == 1:
                candidate = result.candidates[0]
                if messagebox.askyesno("Workbook found", f"Use this workbook?\n\n{candidate}"):
                    self.use_workbook(candidate)
            elif not result.candidates:
                messagebox.showinfo("Find Workbooks", "No likely workbook was found in common OneDrive locations. Use Locate/Change Workbook to choose it manually.")
            else:
                messagebox.showinfo("Find Workbooks", "Multiple likely workbooks were found. Select the correct one in Settings.")
        except Exception:
            LOGGER.exception("Unexpected error during workbook discovery")
            messagebox.showerror("Find Workbooks", "Something went wrong while searching for workbooks. Technical details were written to the application log.")

    def use_workbook(self, path: Path) -> None:
        try:
            result = self.app_state.change_workbook(path)
            self.discovery_result = None
            self.refresh_view()
            self._notify_state_changed(result.message)
            if result.success:
                messagebox.showinfo("Workbook configured", "Workbook validated, saved, and loaded read-only.")
            else:
                details = "\n".join(result.health.errors[:5])
                messagebox.showwarning("Workbook not saved", details or result.message)
        except Exception:
            LOGGER.exception("Unexpected error while changing workbook")
            messagebox.showerror("Workbook setup", "Something went wrong while loading the workbook. Technical details were written to the application log.")

    def open_directory(self, path: Path, label: str, *, create: bool = True) -> None:
        ok, error = open_folder(path, create=create)
        if not ok:
            LOGGER.warning("Could not open %s folder %s: %s", label, path, error)
            messagebox.showwarning("Open Folder", f"The {label} folder could not be opened automatically.\n\n{path}")

    def _notify_state_changed(self, message: str | None) -> None:
        if self.on_state_changed is not None:
            self.on_state_changed(message)

    def _section(self, row: int, title: str) -> int:
        ctk.CTkLabel(self.body, text=title, font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=row,
            column=0,
            sticky="w",
            padx=6,
            pady=(12, 8),
        )
        return row + 1

    def _key_values(self, row: int, values: list[tuple[str, str]]) -> int:
        panel = ctk.CTkFrame(self.body)
        panel.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 10))
        panel.grid_columnconfigure(1, weight=1)
        for index, (label, value) in enumerate(values):
            ctk.CTkLabel(panel, text=label, text_color=PALETTE.text_muted, anchor="w").grid(row=index, column=0, sticky="w", padx=14, pady=5)
            ctk.CTkLabel(panel, text=value, anchor="w", justify="left", wraplength=820).grid(row=index, column=1, sticky="ew", padx=14, pady=5)
        return row + 1

    def _actions(self, row: int, actions: list[tuple[str, Callable[[], None]]]) -> int:
        frame = ctk.CTkFrame(self.body, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="w", padx=2, pady=(0, 12))
        for index, (label, command) in enumerate(actions):
            ctk.CTkButton(frame, text=label, command=command).grid(row=0, column=index, padx=4, pady=4)
        return row + 1

    def _messages(self, row: int, title: str, errors: list[str], warnings: list[str]) -> int:
        panel = ctk.CTkFrame(self.body)
        panel.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 12))
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(panel, text=title, font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        lines = [f"ERROR: {message}" for message in errors] + [f"WARNING: {message}" for message in warnings]
        ctk.CTkLabel(panel, text="\n".join(lines[:8]), justify="left", text_color=PALETTE.danger if errors else PALETTE.warning, wraplength=900).grid(
            row=1,
            column=0,
            sticky="w",
            padx=14,
            pady=(0, 12),
        )
        return row + 1

    def _render_discovery_results(self, row: int, result: WorkbookDiscoveryResult) -> int:
        row = self._section(row, "Discovery results")
        if not result.candidates:
            return self._key_values(row, [("Result", "No likely workbook found.")])

        panel = ctk.CTkFrame(self.body)
        panel.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 12))
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(panel, text="Select the correct synced workbook:", text_color=PALETTE.text_muted, anchor="w").grid(
            row=0,
            column=0,
            sticky="ew",
            padx=14,
            pady=(12, 6),
        )
        for index, candidate in enumerate(result.candidates[:10], start=1):
            ctk.CTkButton(panel, text=str(candidate), anchor="w", command=lambda selected=candidate: self.use_workbook(selected)).grid(
                row=index,
                column=0,
                sticky="ew",
                padx=14,
                pady=4,
            )
        if result.truncated:
            ctk.CTkLabel(panel, text="Search stopped at the configured safety limit.", text_color=PALETTE.warning).grid(
                row=len(result.candidates[:10]) + 1,
                column=0,
                sticky="w",
                padx=14,
                pady=(4, 12),
            )
        return row + 1


def _clear_frame(frame: Any) -> None:
    for child in frame.winfo_children():
        child.destroy()
