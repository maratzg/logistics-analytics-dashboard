from __future__ import annotations

import logging
from tkinter import messagebox
from typing import Any

import customtkinter as ctk
import pandas as pd

from src.analytical_filters import FilterContext
from src.app_state import ApplicationState

from .comparison_view import ComparisonView
from .components.filter_bar import AnalyticalFilterBar
from .components.layout import GlobalHeader
from .components.status import quality_issue_counts, source_status_model
from .dashboard_view import DashboardView
from .entity_views import EntityAnalyticsView
from .history_view import HistoryView
from .navigation import NAVIGATION_ITEMS, NavigationSidebar, navigation_item, resolve_route
from .settings_view import SettingsView
from .quality_view import DataQualityView
from .theme import PALETTE, apply_application_theme
from .voyage_view import VoyageView
from .widgets import configure_treeview_style


LOGGER = logging.getLogger(__name__)
DEFAULT_WINDOW_SIZE = (1440, 900)
MINIMUM_WINDOW_SIZE = (1100, 680)
WINDOW_MARGIN = 64


def initial_window_size(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Fit the preferred shell within an office display without shrinking below its usable minimum."""

    width = max(MINIMUM_WINDOW_SIZE[0], min(DEFAULT_WINDOW_SIZE[0], screen_width - WINDOW_MARGIN))
    height = max(MINIMUM_WINDOW_SIZE[1], min(DEFAULT_WINDOW_SIZE[1], screen_height - WINDOW_MARGIN))
    return width, height


class HistoryDashboardApp(ctk.CTk):
    """Phase D shell hosting Phase E primary screens and preserved secondary views."""

    def __init__(self, state: ApplicationState, *, smoke_test_ms: int | None = None) -> None:
        apply_application_theme()
        super().__init__(fg_color=PALETTE.app_background)
        self.app_state = state
        self.current_view_name = "Dashboard"
        self.global_filter_context = FilterContext()
        self.views: dict[str, Any] = {}
        self.nav_buttons: dict[str, ctk.CTkButton] = {}

        configure_treeview_style()
        self.title("Weekly Operations Analytics")
        window_width, window_height = initial_window_size(self.winfo_screenwidth(), self.winfo_screenheight())
        self.geometry(f"{window_width}x{window_height}")
        self.minsize(*MINIMUM_WINDOW_SIZE)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.navigation = NavigationSidebar(self, self.show_view)
        self.navigation.grid(row=0, column=0, sticky="nsew")
        self.nav_buttons = self.navigation.buttons

        self.shell = ctk.CTkFrame(self, fg_color=PALETTE.app_background, corner_radius=0)
        self.shell.grid(row=0, column=1, sticky="nsew")
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_rowconfigure(2, weight=1)

        self.header = GlobalHeader(self.shell, self.refresh_data)
        self.header.grid(row=0, column=0, sticky="ew")
        self.refresh_button = self.header.refresh_button
        self.filter_bar = AnalyticalFilterBar(self.shell, self._on_global_filter_changed)
        self.filter_bar.grid(row=1, column=0, sticky="ew")

        self._build_content_area()

        initial = self.app_state.refresh()
        if not initial.success and initial.error is not None:
            LOGGER.error("Initial workbook load failed: %s", initial.error)
        self._sync_shell_state(preserve_filter_selection=True)
        self.show_view("Dashboard")

        if smoke_test_ms is not None:
            self.after(150, self._smoke_cycle_pages)
            self.after(smoke_test_ms, self.destroy)

    def _build_content_area(self) -> None:
        self.content = ctk.CTkFrame(self.shell, corner_radius=0, fg_color=PALETTE.app_background)
        self.content.grid(row=2, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.views = {
            "Dashboard": DashboardView(
                self.content,
                self.app_state,
                locate_workbook_command=self.locate_workbook,
                discover_workbooks_command=self.find_workbooks,
            ),
            "Voyages": VoyageView(
                self.content,
                self.app_state,
                on_context_change=self.header.set_page,
                on_navigate=self.show_view,
            ),
            "History": HistoryView(self.content, self.app_state),
            "Vessel Analytics": EntityAnalyticsView(
                self.content,
                self.app_state,
                "vessel",
                on_open_voyage=lambda identity: self.open_voyage_detail(identity, "Vessel Analytics"),
            ),
            "Service Analytics": EntityAnalyticsView(
                self.content,
                self.app_state,
                "service",
                on_open_voyage=lambda identity: self.open_voyage_detail(identity, "Service Analytics"),
            ),
            "Customers": EntityAnalyticsView(
                self.content,
                self.app_state,
                "customer",
                on_open_voyage=lambda identity: self.open_voyage_detail(identity, "Customers"),
            ),
            "Compare": ComparisonView(
                self.content,
                self.app_state,
                on_open_voyage=lambda identity: self.open_voyage_detail(identity, "Compare"),
            ),
            "Data Quality": DataQualityView(
                self.content,
                self.app_state,
                on_open_voyage=lambda identity: self.open_voyage_detail(identity, "Data Quality"),
            ),
            "Settings": SettingsView(self.content, self.app_state, on_state_changed=self._after_state_change),
        }
        for view in self.views.values():
            view.grid(row=0, column=0, sticky="nsew")
            view.grid_remove()

    def show_view(self, name: str) -> None:
        route = resolve_route(name)
        if route is None or route not in self.views:
            return
        try:
            self.current_view_name = route
            item = navigation_item(route)
            if item is not None:
                self.header.set_page(item.title, item.subtitle)
            if route == "Settings":
                self.filter_bar.grid_remove()
            else:
                self.filter_bar.grid()
            for view_name, view in self.views.items():
                if view_name == route:
                    self._apply_context_to_view(view)
                    view.grid()
                    view.refresh_view()
                else:
                    view.grid_remove()
            self.navigation.select(route)
        except Exception:
            self._handle_unexpected_gui_error("displaying this page")

    def open_voyage_detail(self, identity_key: str, return_route: str) -> None:
        """Navigate within the loaded snapshot; this method never refreshes Excel."""

        view = self.views.get("Voyages")
        if not isinstance(view, VoyageView):
            return
        view.open_identity(identity_key, return_route=return_route)
        self.show_view("Voyages")

    def refresh_data(self) -> None:
        try:
            self.header.set_refreshing(True)
            self.filter_bar.set_loading(True)
            self.header.source_status.update_model(source_status_model(self.app_state, refreshing=True))
            self.update_idletasks()
            result = self.app_state.refresh()
            if not result.success and result.error is not None:
                LOGGER.error("Refresh failed: %s", result.error)
            self._sync_shell_state(preserve_filter_selection=True)
            current = self.views.get(self.current_view_name)
            if current is not None:
                self._apply_context_to_view(current)
                current.refresh_view()
        except Exception:
            self._handle_unexpected_gui_error("refreshing the workbook")
        finally:
            self.header.set_refreshing(False)
            self.filter_bar.set_loading(False)
            self.header.source_status.update_model(source_status_model(self.app_state))

    def locate_workbook(self) -> None:
        settings = self.views.get("Settings")
        if isinstance(settings, SettingsView):
            settings.change_workbook()

    def find_workbooks(self) -> None:
        self.show_view("Settings")
        settings = self.views.get("Settings")
        if isinstance(settings, SettingsView):
            settings.find_workbooks()

    def _on_global_filter_changed(self, context: FilterContext) -> None:
        self.global_filter_context = context
        self.app_state.set_analytical_filter_context(context)
        current = self.views.get(self.current_view_name)
        if current is not None:
            self._apply_context_to_view(current)
            current.refresh_view()

    def _sync_shell_state(self, *, preserve_filter_selection: bool) -> None:
        self.header.source_status.update_model(source_status_model(self.app_state))
        quality = self.app_state.data.quality_issues_df if self.app_state.data is not None else pd.DataFrame()
        self.header.quality.update_counts(quality_issue_counts(quality))
        weekly = self.app_state.data.weekly_df if self.app_state.data is not None else pd.DataFrame()
        self.filter_bar.set_dataframe(weekly, preserve_selection=preserve_filter_selection)
        self.global_filter_context = self.filter_bar.context
        self.app_state.set_analytical_filter_context(self.global_filter_context)

    def _after_state_change(self, message: str | None = None) -> None:
        del message  # detailed status remains in Settings/logs; the header stays concise
        self._sync_shell_state(preserve_filter_selection=True)
        current = self.views.get(self.current_view_name)
        if current is not None:
            self._apply_context_to_view(current)
            current.refresh_view()

    def _apply_context_to_view(self, view: Any) -> None:
        setter = getattr(view, "set_filter_context", None)
        if callable(setter):
            setter(self.global_filter_context)

    def _handle_unexpected_gui_error(self, action: str) -> None:
        LOGGER.exception("Unexpected GUI error while %s", action)
        messagebox.showerror(
            "History Dashboard",
            "Something went wrong while using the dashboard.\n\nTechnical details were written to the application log.",
        )

    def _smoke_cycle_pages(self) -> None:
        for index, item in enumerate(NAVIGATION_ITEMS):
            self.after(index * 120, lambda selected=item.route: self.show_view(selected))
        self.after(len(NAVIGATION_ITEMS) * 120, self._smoke_phase_f_drilldown)

    def _smoke_phase_f_drilldown(self) -> None:
        """Exercise one entity selection, safe voyage drill-down, and return path."""

        model = self.app_state.vessel_analytics_page_model()
        if model.overview.empty:
            return
        row = model.overview.iloc[0]
        selected_key = str(row.get("_EntityKey", ""))
        detail = self.app_state.vessel_analytics_page_model(selected_key)
        vessel_view = self.views.get("Vessel Analytics")
        if isinstance(vessel_view, EntityAnalyticsView):
            vessel_view.selected_key = selected_key
            vessel_view.selector.set(str(row.get("Vessel", "Overview")))
        self.show_view("Vessel Analytics")
        if detail.voyages.empty:
            return
        identity_key = str(detail.voyages.iloc[0].get("IdentityKey", ""))
        if not identity_key:
            return
        self.after(140, lambda: self.open_voyage_detail(identity_key, "Vessel Analytics"))
        self.after(360, self._smoke_return_from_voyage)

    def _smoke_return_from_voyage(self) -> None:
        voyage_view = self.views.get("Voyages")
        if isinstance(voyage_view, VoyageView) and voyage_view.detail_open:
            voyage_view._back_to_browser()


def run_gui(state: ApplicationState, *, smoke_test_ms: int | None = None) -> int:
    app = HistoryDashboardApp(state, smoke_test_ms=smoke_test_ms)
    app.mainloop()
    return 0
