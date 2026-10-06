from __future__ import annotations

import importlib
import os
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from matplotlib.figure import Figure

from src.analytical_filters import FilterContext, apply_current_filters
from src.analytics import calculate_history_metrics, calculate_weekly_metrics
from src.app_state import ApplicationState, LoadedWorkbookData
from src.config import AppConfig
from src.data_cleaner import clean_history, clean_weekly
from src.gui.app import DEFAULT_WINDOW_SIZE, MINIMUM_WINDOW_SIZE, initial_window_size
from src.gui.components.chart_card import ChartCard
from src.gui.components.data_table import column_alignment, column_width, sort_dataframe
from src.gui.components.kpi_card import format_metric
from src.gui.components.status import quality_issue_counts, source_status_model
from src.gui.filter_state import FilterSelectionState, faceted_filter_options, filtered_current_rows
from src.gui.navigation import NAVIGATION_ITEMS, navigation_groups, resolve_route
from src.gui.presentation import format_voyage_identity
from src.workbook_health import WorkbookHealthStatus


def weekly_frame() -> pd.DataFrame:
    return clean_weekly(
        pd.DataFrame(
            [
                {
                    "Week": 39,
                    "Vessel": "VESSEL A",
                    "Voyage": "V001",
                    "ETA": "2026-09-15",
                    "SVC": "S1",
                    "POL": "RIGA",
                    "POD": "ROTTERDAM",
                    "CUSTOMER": "Alice",
                    "Booking number": "BK-1",
                    "CNTR AMT": 2,
                    "SIZE": 2,
                    "GWT": 12,
                    "BlockID": "opaque-a",
                    "RowID": "row-a",
                    "LoadStatus": "",
                    "RowStatus": "",
                },
                {
                    "Week": 40,
                    "Vessel": "VESSEL B",
                    "Voyage": "V002",
                    "ETA": "2026-10-03",
                    "SVC": "S2",
                    "POL": "TALLINN",
                    "POD": "HAMBURG",
                    "CUSTOMER": "Bob",
                    "Booking number": "BK-2",
                    "CNTR AMT": 3,
                    "SIZE": 4,
                    "GWT": 20,
                    "BlockID": "opaque-b",
                    "RowID": "row-b",
                    "LoadStatus": "Empty",
                    "RowStatus": "Cancelled",
                },
            ]
        )
    ).dataframe


class PhaseDNavigationTests(unittest.TestCase):
    def test_grouped_navigation_has_required_order_and_alias(self) -> None:
        self.assertEqual(
            [item.route for item in NAVIGATION_ITEMS],
            ["Dashboard", "Voyages", "History", "Vessel Analytics", "Service Analytics", "Customers", "Compare", "Data Quality", "Settings"],
        )
        groups = navigation_groups()
        self.assertEqual([item.route for item in groups["Primary"]], ["Dashboard", "Voyages", "History"])
        self.assertEqual([item.route for item in groups["Secondary"]], ["Settings"])
        self.assertEqual(resolve_route("Vessels"), "Vessel Analytics")
        self.assertIsNone(resolve_route("Unknown page"))

    def test_window_foundation_fits_target_office_resolution(self) -> None:
        self.assertLessEqual(MINIMUM_WINDOW_SIZE[0], 1366)
        self.assertLessEqual(MINIMUM_WINDOW_SIZE[1], 768)
        self.assertEqual(DEFAULT_WINDOW_SIZE, (1440, 900))
        self.assertEqual(initial_window_size(1366, 768), (1302, 704))
        self.assertEqual(initial_window_size(1920, 1080), DEFAULT_WINDOW_SIZE)


class PhaseDFilterFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly = weekly_frame()

    def test_filter_state_maps_to_phase_c_context_and_clears(self) -> None:
        state = FilterSelectionState()
        state.set_value("vessel", "VESSEL A")
        state.set_value("week", "39")

        self.assertEqual(state.active_count, 2)
        self.assertEqual(state.to_context().vessel, "VESSEL A")
        self.assertEqual(filtered_current_rows(self.weekly, state)["RowID"].tolist(), ["row-a"])

        state.reset()
        self.assertFalse(state.is_active)
        self.assertEqual(state.to_context(), FilterContext())

    def test_faceted_options_are_dynamic_and_safe_when_result_is_empty(self) -> None:
        state = FilterSelectionState()
        state.set_value("vessel", "VESSEL A")
        options = faceted_filter_options(self.weekly, state)
        self.assertEqual(options["voyage"], ["All", "V001"])
        self.assertIn("Active", options["row_status"])

        state.set_value("voyage", "DOES NOT EXIST")
        self.assertTrue(filtered_current_rows(self.weekly, state).empty)
        empty_options = faceted_filter_options(self.weekly, state)
        self.assertEqual(empty_options["svc"], ["All"])

    def test_blank_row_status_filters_as_active(self) -> None:
        active = apply_current_filters(self.weekly, FilterContext(row_status="Active"))
        cancelled = apply_current_filters(self.weekly, FilterContext(row_status="Cancelled"))
        self.assertEqual(active["RowID"].tolist(), ["row-a"])
        self.assertEqual(cancelled["RowID"].tolist(), ["row-b"])

    def test_application_state_models_share_the_global_filter_context(self) -> None:
        history = clean_history(pd.DataFrame()).dataframe
        loaded = LoadedWorkbookData(
            workbook_path=Path("/tmp/source.xlsm"),
            structure=None,
            weekly_df=self.weekly,
            history_df=history,
            weekly_metrics=calculate_weekly_metrics(self.weekly),
            history_metrics=calculate_history_metrics(history),
            issues=[],
            loaded_at=datetime(2026, 9, 9, 10, 30),
        )
        state = ApplicationState(AppConfig(workbook_path=loaded.workbook_path), loader=lambda: loaded)
        state.refresh()
        state.set_analytical_filter_context(FilterContext(vessel="VESSEL A"))

        self.assertEqual(state.filtered_weekly()["RowID"].tolist(), ["row-a"])
        self.assertEqual(state.dashboard_model().weekly_metrics.total_containers, 2)
        self.assertEqual(state.selector_options().vessels, ["All", "VESSEL A"])


class PhaseDComponentHelperTests(unittest.TestCase):
    def test_kpi_formatting(self) -> None:
        self.assertEqual(format_metric(1234, "containers"), "1,234")
        self.assertEqual(format_metric(0.625, "percent"), "62.5%")
        self.assertEqual(format_metric(3, "days"), "+3 d")
        self.assertEqual(format_metric(None, "teu"), "—")

    def test_table_alignment_width_and_stable_sort(self) -> None:
        frame = pd.DataFrame({"Vessel": ["B", "A"], "Total TEU": [2, 10]})
        sorted_frame = sort_dataframe(frame, "Total TEU", ascending=False)
        self.assertEqual(sorted_frame["Total TEU"].tolist(), [10, 2])
        self.assertEqual(column_alignment("Total TEU", frame["Total TEU"]), "e")
        self.assertEqual(column_alignment("Vessel", frame["Vessel"]), "w")
        self.assertGreaterEqual(column_width("Booking number"), 140)

    def test_source_status_transitions_and_cached_snapshot(self) -> None:
        state = SimpleNamespace(
            workbook_filename="Weekly.xlsm",
            last_loaded=datetime(2026, 9, 9, 10, 30),
            data=object(),
            load_status="Loaded successfully",
            health=SimpleNamespace(status=WorkbookHealthStatus.READY),
        )
        self.assertEqual(source_status_model(state).kind, "ready")
        self.assertEqual(source_status_model(state, refreshing=True).label, "Refreshing")
        state.load_status = "Refresh failed; showing previously loaded data"
        cached = source_status_model(state)
        self.assertEqual(cached.kind, "warning")
        self.assertIn("last successful", cached.detail)

    def test_quality_indicator_counts(self) -> None:
        issues = pd.DataFrame({"Severity": ["Critical", "Warning", "warning", "Information"]})
        self.assertEqual(quality_issue_counts(issues), {"Critical": 1, "Warning": 2, "Information": 1})

    def test_voyage_identity_hides_opaque_id_until_needed(self) -> None:
        label = format_voyage_identity(
            vessel="VESSEL A",
            voyage="V001",
            week=39,
            eta="2026-09-15",
            pol="RIGA",
            pod="ROTTERDAM",
            block_id="opaque-block-a",
        )
        self.assertIn("VESSEL A · V001", label)
        self.assertIn("Week 39", label)
        self.assertNotIn("opaque-block-a", label)
        detailed = format_voyage_identity(vessel="VESSEL A", voyage="V001", block_id="opaque-block-a", disambiguate=True)
        self.assertIn("ID opaque-block-a", detailed)

    def test_chart_axis_foundation_is_light_and_labeled(self) -> None:
        figure = Figure()
        axis = figure.add_subplot(111)
        ChartCard.style_axis(axis, value_label="TEU")
        self.assertEqual(axis.get_ylabel(), "TEU")
        self.assertTrue(any(line.get_visible() for line in axis.get_ygridlines()))

    def test_gui_startup_modules_import(self) -> None:
        for module in [
            "src.gui.app",
            "src.gui.navigation",
            "src.gui.components.filter_bar",
            "src.gui.components.data_table",
            "src.gui.components.chart_card",
        ]:
            self.assertIsNotNone(importlib.import_module(module))


@unittest.skipUnless(os.environ.get("HISTORY_DASHBOARD_GUI_SMOKE") == "1", "GUI display smoke is opt-in")
class PhaseDDisplaySmokeTests(unittest.TestCase):
    def test_shell_initializes_when_a_display_is_available(self) -> None:
        from src.gui.app import HistoryDashboardApp

        state = ApplicationState(AppConfig(workbook_path=Path("/tmp/not-configured.xlsm")))
        app = HistoryDashboardApp(state, smoke_test_ms=100)
        app.update_idletasks()
        self.assertEqual(len(app.views), 9)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
