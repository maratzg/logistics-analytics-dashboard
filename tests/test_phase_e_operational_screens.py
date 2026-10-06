from __future__ import annotations

import importlib
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.analytical_filters import FilterContext
from src.analytics import calculate_history_metrics, calculate_weekly_metrics
from src.app_state import ApplicationState, LoadedWorkbookData
from src.config import AppConfig
from src.data_cleaner import clean_history, clean_weekly
from src.gui.operational_models import (
    build_attention_items,
    build_dashboard_model,
    build_history_model,
    build_voyage_browser_model,
    build_voyage_detail_model,
)
from src.gui.presentation import UNAVAILABLE_TEXT, format_movement, history_change_message
from src.quality_analytics import generate_quality_issues


def weekly_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Week": 39,
        "Vessel": "VESSEL A",
        "Voyage": "V001",
        "ETA": "2026-09-15",
        "ETD": "2026-09-16",
        "Cut-Off": "2026-09-13",
        "ETA T/S": "2026-09-20",
        "Booking number": "BK-1",
        "SVC": "S1",
        "Booking status": "Confirmed",
        "CNTR AMT": 2,
        "SIZE": 2,
        "TYPE": "DRY",
        "GWT": 12,
        "POL": "RIGA",
        "POD CODE": "NLRTM",
        "POD": "ROTTERDAM",
        "CUSTOMER": "Alice",
        "RowStatus": "",
        "CancelReason": "",
        "BlockID": "opaque-block-a",
        "RowID": "opaque-row-1",
        "LoadStatus": "Loaded",
    }
    row.update(overrides)
    return row


def history_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Timestamp": "2026-09-10 10:00:00",
        "User": "employee",
        "BlockID": "opaque-block-a",
        "RowID": "opaque-row-1",
        "Week": 39,
        "Vessel": "VESSEL A",
        "Voyage": "V001",
        "Booking number": "BK-1",
        "Comments 1": "",
        "Comments 2": "",
        "CancelReason": "",
        "Field": "ETA",
        "OldValue": "2026-09-12",
        "NewValue": "2026-09-14",
        "Year": 1900,
        "Month": 1,
    }
    row.update(overrides)
    return row


def fixture_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    weekly = clean_weekly(
        pd.DataFrame(
            [
                weekly_row(),
                weekly_row(RowID="opaque-row-2", **{"Booking number": "BK-2", "LoadStatus": "Empty", "CNTR AMT": 3, "SIZE": 4, "GWT": 0}),
                weekly_row(RowID="opaque-row-3", **{"Booking number": "BK-3", "LoadStatus": "mystery", "CNTR AMT": 1, "SIZE": 4, "GWT": 5}),
                weekly_row(RowID="opaque-row-4", **{"Booking number": "BK-4", "RowStatus": "Cancelled", "CancelReason": "Customer request", "CNTR AMT": 5, "SIZE": 4, "GWT": 30}),
                weekly_row(RowID="opaque-row-b", BlockID="opaque-block-b", Vessel="VESSEL B", Voyage="V001", Week=40, SVC="S2", POL="TALLINN", POD="HAMBURG", **{"POD CODE": "DEHAM", "CUSTOMER": "Bob", "Booking number": "BK-5", "ETA": "2026-10-03", "ETD": "2026-10-04", "CNTR AMT": 4, "SIZE": 2, "GWT": 24}),
            ]
        )
    ).dataframe
    history = clean_history(
        pd.DataFrame(
            [
                history_row(RowID="opaque-row-1"),
                history_row(RowID="opaque-row-2", **{"Booking number": "BK-2"}),
                history_row(RowID="opaque-row-1", Timestamp="2026-09-11 10:00:00", OldValue="2026-09-14", NewValue="2026-09-15"),
                history_row(RowID="opaque-row-1", Field="Week", Timestamp="2026-09-12 10:00:00", OldValue=37, NewValue=39),
                history_row(RowID="opaque-row-2", **{"Booking number": "BK-2", "Field": "Week", "Timestamp": "2026-09-12 10:00:00", "OldValue": 37, "NewValue": 39}),
                history_row(RowID="opaque-row-3", Field="LoadStatus", Timestamp="2026-09-13 10:00:00", OldValue="[bulk edit]", NewValue="mystery"),
                history_row(RowID="opaque-row-b", BlockID="opaque-block-b", Vessel="VESSEL B", Voyage="V001", Week=40, **{"Booking number": "BK-5", "Timestamp": "2026-10-01 08:00:00", "OldValue": "2026-10-01", "NewValue": "2026-10-03"}),
            ]
        )
    ).dataframe
    quality = generate_quality_issues(weekly, history)
    return weekly, history, quality


def loaded(weekly: pd.DataFrame, history: pd.DataFrame, quality: pd.DataFrame) -> LoadedWorkbookData:
    return LoadedWorkbookData(
        workbook_path=Path("/tmp/source.xlsm"),
        structure=None,
        weekly_df=weekly,
        history_df=history,
        weekly_metrics=calculate_weekly_metrics(weekly),
        history_metrics=calculate_history_metrics(history),
        issues=[],
        loaded_at=datetime(2026, 9, 14, 12, 0),
        quality_issues_df=quality,
    )


class PhaseEDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()

    def test_dashboard_kpis_and_unclassified_cargo(self) -> None:
        model = build_dashboard_model(self.weekly, self.history, self.quality)
        self.assertTrue(model.has_rows)
        self.assertEqual(model.metrics.total_containers, 10)
        self.assertEqual(model.metrics.loaded_containers, 6)
        self.assertEqual(model.metrics.empty_containers, 3)
        self.assertEqual(model.metrics.unclassified_containers, 1)
        self.assertEqual(model.metrics.cancelled_rows, 1)
        self.assertEqual(len(model.voyage_composition), 2)

    def test_empty_dashboard_is_intentional(self) -> None:
        model = build_dashboard_model(self.weekly, self.history, self.quality, FilterContext(vessel="NO SUCH VESSEL"))
        self.assertFalse(model.has_rows)
        self.assertIn("shared filters", model.empty_message or "")

    def test_recent_changes_are_grouped_and_human_readable(self) -> None:
        model = build_dashboard_model(self.weekly, self.history, self.quality)
        eta = next(item for item in model.recent_changes if item.field == "ETA" and item.vessel == "VESSEL B")
        self.assertIn("changed from 01.10.2026 to 03.10.2026", eta.message)
        grouped = next(item for item in model.recent_changes if item.field == "Week")
        self.assertEqual(grouped.raw_event_count, 2)

    def test_bulk_edit_is_presented_as_unavailable(self) -> None:
        model = build_dashboard_model(self.weekly, self.history, self.quality)
        event = next(item for item in model.recent_changes if item.field == "LoadStatus")
        self.assertIn("previous value unavailable", event.message)
        self.assertNotIn("bulk edit", event.message.casefold())

    def test_attention_items_explain_source_signals(self) -> None:
        model = build_dashboard_model(self.weekly, self.history, self.quality)
        reasons = " ".join(item.reason for item in model.attention_items)
        self.assertTrue(any(token in reasons for token in ["unclassified", "LoadStatus", "Week changed", "revised"]))
        self.assertFalse(any(hasattr(item, "score") for item in model.attention_items))


class PhaseEVoyageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()

    def test_browser_keeps_duplicate_voyage_text_as_safe_instances(self) -> None:
        model = build_voyage_browser_model(self.weekly, self.history, self.quality)
        self.assertEqual(model.voyage_count, 2)
        self.assertEqual(model.rows["IdentityKey"].nunique(), 2)
        self.assertEqual(set(model.rows["Vessel"]), {"VESSEL A", "VESSEL B"})

    def test_browser_respects_shared_filters(self) -> None:
        model = build_voyage_browser_model(self.weekly, self.history, self.quality, FilterContext(vessel="VESSEL B"))
        self.assertEqual(model.voyage_count, 1)
        self.assertEqual(model.rows.iloc[0]["Vessel"], "VESSEL B")

    def test_detail_uses_selected_composite_identity(self) -> None:
        browser = build_voyage_browser_model(self.weekly, self.history, self.quality)
        selected = browser.rows[browser.rows["Vessel"].eq("VESSEL A")].iloc[0]["IdentityKey"]
        detail = build_voyage_detail_model(self.weekly, self.history, self.quality, selected)
        self.assertTrue(detail.available)
        self.assertEqual(detail.vessel, "VESSEL A")
        self.assertEqual(detail.block_id, "opaque-block-a")
        self.assertEqual(detail.metrics["Total Containers"], 6)

    def test_bookings_include_cancelled_rows(self) -> None:
        key = "vessel a||v001||opaque-block-a"
        detail = build_voyage_detail_model(self.weekly, self.history, self.quality, key)
        self.assertEqual(len(detail.bookings), 4)
        cancelled = detail.bookings[detail.bookings["RowStatus"].eq("Cancelled")]
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled.iloc[0]["CancelReason"], "Customer request")

    def test_schedule_movement_and_timeline_modes(self) -> None:
        detail = build_voyage_detail_model(self.weekly, self.history, self.quality, "vessel a||v001||opaque-block-a")
        self.assertEqual(format_movement(detail.schedule["Net ETA Movement"]), "+3 days later")
        self.assertEqual(detail.schedule["Week Change Count"], 1)
        self.assertLess(len(detail.grouped_timeline), len(detail.raw_timeline))
        self.assertEqual(detail.grouped_timeline["Raw Events"].max(), 2)

    def test_original_eta_is_unavailable_when_history_cannot_support_it(self) -> None:
        weekly = clean_weekly(pd.DataFrame([weekly_row()])).dataframe
        history = clean_history(pd.DataFrame([history_row(OldValue="[bulk edit]", NewValue="2026-09-15")])).dataframe
        detail = build_voyage_detail_model(weekly, history, pd.DataFrame(), "vessel a||v001||opaque-block-a")
        self.assertEqual(detail.schedule["Original ETA"], UNAVAILABLE_TEXT)
        self.assertIsNone(detail.schedule["Net ETA Movement"])

    def test_stale_selection_returns_safe_unavailable_model(self) -> None:
        detail = build_voyage_detail_model(self.weekly, self.history, self.quality, "missing||identity||key")
        self.assertFalse(detail.available)
        self.assertIn("no longer available", detail.empty_message or "")


class PhaseEHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()

    def test_grouped_is_default_and_raw_remains_available(self) -> None:
        grouped = build_history_model(self.weekly, self.history)
        raw = build_history_model(self.weekly, self.history, mode="raw")
        self.assertEqual(grouped.mode, "grouped")
        self.assertLess(grouped.matching_count, raw.matching_count)
        self.assertEqual(grouped.source_event_count, raw.matching_count)

    def test_legacy_value_never_appears_as_business_value(self) -> None:
        raw = build_history_model(self.weekly, self.history, mode="raw", field_name="LoadStatus")
        self.assertEqual(raw.rows.iloc[0]["Old Value"], UNAVAILABLE_TEXT)
        self.assertNotIn("bulk edit", " ".join(raw.rows.astype(str).stack().tolist()).casefold())

    def test_field_user_and_date_filters(self) -> None:
        result = build_history_model(
            self.weekly,
            self.history,
            mode="raw",
            field_name="ETA",
            user="employee",
            start_date="11.09.2026",
            end_date="30.09.2026",
        )
        self.assertEqual(result.matching_count, 1)
        self.assertEqual(result.rows.iloc[0]["Field"], "ETA")

    def test_case_insensitive_whitespace_safe_search_includes_customer_context(self) -> None:
        result = build_history_model(self.weekly, self.history, mode="raw", search="  ALICE  ")
        self.assertGreater(result.matching_count, 0)
        self.assertTrue((result.rows["Customer"] == "Alice").all())

    def test_empty_history_and_invalid_date_are_safe(self) -> None:
        empty = build_history_model(self.weekly, self.history, search="not present")
        invalid = build_history_model(self.weekly, self.history, start_date="not-a-date")
        self.assertEqual(empty.matching_count, 0)
        self.assertIsNotNone(empty.empty_message)
        self.assertIn("invalid", invalid.input_warning or "")


class PhaseEStateIntegrationTests(unittest.TestCase):
    def test_navigation_models_do_not_trigger_additional_workbook_reads(self) -> None:
        weekly, history, quality = fixture_frames()
        calls = 0

        def loader() -> LoadedWorkbookData:
            nonlocal calls
            calls += 1
            return loaded(weekly, history, quality)

        state = ApplicationState(AppConfig(workbook_path=Path("/tmp/source.xlsm")), loader=loader)
        state.refresh()
        first = state.operational_dashboard_model()
        self.assertIs(first, state.operational_dashboard_model())
        state.voyage_browser_model()
        state.operational_history_model()
        state.voyage_detail_model("vessel a||v001||opaque-block-a")
        self.assertEqual(calls, 1)

    def test_shared_filter_and_refresh_keep_valid_identity_available(self) -> None:
        weekly, history, quality = fixture_frames()
        state = ApplicationState(AppConfig(workbook_path=Path("/tmp/source.xlsm")), loader=lambda: loaded(weekly, history, quality))
        state.refresh()
        state.set_analytical_filter_context(FilterContext(vessel="VESSEL B"))
        self.assertEqual(state.voyage_browser_model().voyage_count, 1)
        key = state.voyage_browser_model().rows.iloc[0]["IdentityKey"]
        state.refresh()
        self.assertTrue(state.voyage_detail_model(key).available)

    def test_phase_e_gui_modules_import(self) -> None:
        for module in ["src.gui.dashboard_view", "src.gui.voyage_view", "src.gui.history_view", "src.gui.operational_models"]:
            self.assertIsNotNone(importlib.import_module(module))


class PhaseEPresentationTests(unittest.TestCase):
    def test_standard_movement_and_change_text(self) -> None:
        self.assertEqual(format_movement(0), "0 days")
        self.assertEqual(format_movement(-3), "-3 days earlier")
        self.assertEqual(history_change_message("ETA", None, "2026-09-14", old_unavailable=True), "ETA changed to 14.09.2026 (previous value unavailable)")


if __name__ == "__main__":
    unittest.main()
