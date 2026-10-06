from __future__ import annotations

import hashlib
import importlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.analytical_filters import FilterContext
from src.analytics import calculate_history_metrics, calculate_weekly_metrics
from src.app_state import ApplicationState, LoadedWorkbookData
from src.config import AppConfig
from src.comparison_analytics import comparison_candidates, compare_voyage_instances
from src.data_cleaner import clean_history, clean_weekly
from src.gui.exporting import export_visible_csv
from src.gui.presentation import UNAVAILABLE_TEXT, format_movement
from src.gui.secondary_models import (
    UNASSIGNED_KEY,
    build_comparison_page_model,
    build_data_quality_page_model,
    build_entity_analytics_model,
    identity_for_quality_issue,
)
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
        "CUSTOMER": "Acme",
        "RowStatus": "",
        "CancelReason": "",
        "BlockID": "opaque-block-a",
        "RowID": "opaque-row-a1",
        "LoadStatus": "Loaded",
    }
    row.update(overrides)
    return row


def history_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Timestamp": "2026-09-10 10:00:00",
        "User": "employee",
        "BlockID": "opaque-block-a",
        "RowID": "opaque-row-a1",
        "Week": 39,
        "Vessel": "VESSEL A",
        "Voyage": "V001",
        "Booking number": "BK-1",
        "Comments 1": "",
        "Comments 2": "",
        "CancelReason": "",
        "Field": "ETA",
        "OldValue": "2026-09-13",
        "NewValue": "2026-09-15",
    }
    row.update(overrides)
    return row


def fixture_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = pd.DataFrame(
        [
            weekly_row(),
            weekly_row(RowID="opaque-row-a2", **{"Booking number": "BK-2", "CUSTOMER": "  acme  ", "LoadStatus": "Empty", "CNTR AMT": 1, "SIZE": 4, "GWT": 0}),
            weekly_row(RowID="opaque-row-a3", **{"Booking number": "BK-3", "RowStatus": "Cancelled", "CancelReason": "Customer request", "CNTR AMT": 9, "SIZE": 4}),
            weekly_row(RowID="opaque-row-b", BlockID="opaque-block-b", Vessel="VESSEL B", Voyage="V001", Week=40, SVC="", **{"Booking number": "BK-4", "CUSTOMER": "", "POD": "HAMBURG", "POD CODE": "DEHAM", "ETA": "2026-10-03", "CNTR AMT": 3, "SIZE": 4, "GWT": 20, "LoadStatus": ""}),
            weekly_row(RowID="opaque-row-c", BlockID="opaque-block-c", Vessel="VESSEL C", Voyage="V003", Week=41, SVC="S2", **{"Booking number": "BK-5", "CUSTOMER": "Beta", "POD": "OSLO", "POD CODE": "NOOSL", "ETA": 20260913, "CNTR AMT": -1, "SIZE": 2, "GWT": 5}),
            weekly_row(RowID="opaque-row-d", BlockID="opaque-block-d", Vessel="VESSEL D", Voyage="V004", Week=42, SVC="S2", **{"Booking number": "BK-6", "CUSTOMER": "Delta", "ETA": "2026-10-15", "CNTR AMT": 4, "SIZE": 2, "GWT": 22}),
            weekly_row(RowID="opaque-row-e", BlockID="opaque-block-e", Vessel="VESSEL E", Voyage="V005", Week=43, SVC="S3", **{"Booking number": "BK-7", "CUSTOMER": "Echo", "ETA": "2026-10-22", "CNTR AMT": 5, "SIZE": 4, "GWT": 30}),
        ]
    )
    weekly = clean_weekly(raw).dataframe
    history = clean_history(
        pd.DataFrame(
            [
                history_row(),
                history_row(Field="Week", OldValue=38, NewValue=39, Timestamp="2026-09-11 10:00:00"),
                history_row(RowID="opaque-row-a2", **{"Booking number": "BK-2"}),
            ]
        )
    ).dataframe
    quality = generate_quality_issues(weekly, history, weekly_raw_df=raw)
    return weekly, history, quality


def loaded(weekly: pd.DataFrame, history: pd.DataFrame, quality: pd.DataFrame) -> LoadedWorkbookData:
    return LoadedWorkbookData(
        workbook_path=Path("/tmp/read-only-source.xlsm"),
        structure=None,
        weekly_df=weekly,
        history_df=history,
        weekly_metrics=calculate_weekly_metrics(weekly),
        history_metrics=calculate_history_metrics(history),
        issues=[],
        loaded_at=datetime(2026, 9, 15, 9, 0),
        quality_issues_df=quality,
    )


class VesselPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()

    def test_vessel_overview_contains_operational_metrics(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "vessel")
        vessel = model.overview[model.overview["Vessel"].eq("VESSEL A")].iloc[0]
        self.assertEqual(vessel["Voyage Count"], 1)
        self.assertEqual(vessel["Total Containers"], 3)
        self.assertEqual(vessel["Loaded Containers"], 2)
        self.assertEqual(vessel["Empty Containers"], 1)
        self.assertEqual(vessel["Cancellation Count"], 1)

    def test_selected_vessel_has_safe_voyage_drilldown(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "vessel", selected_key="vessel a")
        self.assertEqual(model.selected_label, "VESSEL A")
        self.assertEqual(model.voyages.iloc[0]["IdentityKey"], "vessel a||v001||opaque-block-a")

    def test_sparse_schedule_is_unavailable_not_zero(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "vessel")
        vessel_b = model.overview[model.overview["Vessel"].eq("VESSEL B")].iloc[0]
        self.assertTrue(pd.isna(vessel_b["Median Net ETA Movement"]))
        self.assertTrue(pd.isna(vessel_b["Week Rollover %"]))

    def test_vessel_page_respects_shared_filter(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "vessel", FilterContext(vessel="vessel b"))
        self.assertEqual(model.overview["Vessel"].tolist(), ["VESSEL B"])


class ServicePageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()

    def test_service_aggregation_and_selected_breakdowns(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "service", selected_key="s1")
        self.assertEqual(model.selected_label, "S1")
        self.assertEqual(model.summary["Customer Count"], 1)
        self.assertEqual(model.pod_breakdown.iloc[0]["POD"], "ROTTERDAM")
        self.assertEqual(model.customer_breakdown.iloc[0]["CUSTOMER"], "Acme")

    def test_service_voyage_drilldown_preserves_identity(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "service", selected_key="s1")
        self.assertEqual(model.voyages.iloc[0]["BlockID"], "opaque-block-a")

    def test_blank_service_is_explicit_unassigned(self) -> None:
        overview = build_entity_analytics_model(self.weekly, self.history, self.quality, "service")
        self.assertIn("Unassigned", overview.overview["SVC"].tolist())
        detail = build_entity_analytics_model(self.weekly, self.history, self.quality, "service", selected_key=UNASSIGNED_KEY)
        self.assertEqual(detail.selected_label, "Unassigned")
        self.assertEqual(detail.voyages.iloc[0]["Vessel"], "VESSEL B")


class CustomerPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()

    def test_case_and_whitespace_normalization(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "customer")
        self.assertEqual(model.overview[model.overview["CUSTOMER"].eq("Acme")]["Booking/Row Count"].iloc[0], 3)

    def test_blank_customer_is_explicit(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "customer")
        self.assertIn("Unassigned", model.overview["CUSTOMER"].tolist())

    def test_customer_teu_share_uses_safe_total(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "customer")
        shares = pd.to_numeric(model.overview["Share of Total TEU"], errors="coerce").dropna()
        self.assertAlmostEqual(float(shares.sum()), 1.0)

    def test_customer_detail_voyage_and_distributions(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "customer", selected_key="acme")
        self.assertEqual(model.voyages.iloc[0]["IdentityKey"], "vessel a||v001||opaque-block-a")
        self.assertEqual(model.pod_breakdown.iloc[0]["POD"], "ROTTERDAM")
        self.assertEqual(model.service_breakdown.iloc[0]["SVC"], "S1")

    def test_sparse_customer_trend_is_explained(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "customer", selected_key="acme")
        self.assertLess(len(model.trend), 2)
        self.assertIn("not enough ETA periods", model.detail_message or "")


class ComparisonPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()
        self.candidates = build_comparison_page_model(self.weekly, self.history).candidates
        self.keys = self.candidates["IdentityKey"].tolist()

    def test_exactly_two_voyages(self) -> None:
        model = build_comparison_page_model(self.weekly, self.history, selected_keys=self.keys[:2])
        self.assertEqual(len(model.rows), 2)

    def test_five_voyages(self) -> None:
        model = build_comparison_page_model(self.weekly, self.history, selected_keys=self.keys[:5])
        self.assertEqual(len(model.rows), 5)

    def test_duplicate_selection_is_rejected(self) -> None:
        model = build_comparison_page_model(self.weekly, self.history, selected_keys=[self.keys[0], self.keys[0]])
        self.assertIn("only once", model.error_message or "")

    def test_duplicate_voyage_text_remains_distinct(self) -> None:
        duplicate_text = self.candidates[self.candidates["Voyage"].eq("V001")]
        self.assertEqual(len(duplicate_text), 2)
        self.assertEqual(duplicate_text["IdentityKey"].nunique(), 2)

    def test_unavailable_history_is_not_zero(self) -> None:
        key_b = self.candidates[self.candidates["Vessel"].eq("VESSEL B")].iloc[0]["IdentityKey"]
        other = self.keys[0] if self.keys[0] != key_b else self.keys[1]
        model = build_comparison_page_model(self.weekly, self.history, selected_keys=[other, key_b])
        row_b = model.rows[model.rows["IdentityKey"].eq(key_b)].iloc[0]
        self.assertTrue(pd.isna(row_b["ETA Revision Count"]))
        self.assertEqual(format_movement(row_b["Net ETA Movement"]), UNAVAILABLE_TEXT)

    def test_comparison_contains_all_required_presentation_metrics(self) -> None:
        model = build_comparison_page_model(self.weekly, self.history, selected_keys=self.keys[:2])
        expected = {"Loaded Containers", "Empty Containers", "Largest ETA Revision", "GWT / Loaded TEU", "Cancellations"}
        self.assertTrue(expected.issubset(model.rows.columns))

    def test_phase_c_comparison_exposes_required_fields_and_reuses_candidates(self) -> None:
        candidates = comparison_candidates(self.weekly, self.history)
        expected = {"Week", "ETA", "Loaded Containers", "Empty Containers", "Largest Single ETA Revision"}
        self.assertTrue(expected.issubset(candidates.columns))
        selected = compare_voyage_instances(
            self.weekly,
            self.history,
            candidates["IdentityKey"].head(2).tolist(),
            candidates_df=candidates,
        )
        self.assertEqual(len(selected), 2)

    def test_comparison_drilldown_identity_is_safe(self) -> None:
        model = build_comparison_page_model(self.weekly, self.history, selected_keys=self.keys[:2])
        self.assertEqual(model.rows.iloc[0]["IdentityKey"].count("||"), 2)


class DataQualityPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()

    def test_severity_counts_and_category_filter(self) -> None:
        model = build_data_quality_page_model(self.weekly, self.quality)
        self.assertGreater(model.counts["Critical"], 0)
        category = model.rows.iloc[0]["Category"]
        filtered = build_data_quality_page_model(self.weekly, self.quality, category=category)
        self.assertEqual(set(filtered.rows["Category"]), {category})

    def test_text_search(self) -> None:
        model = build_data_quality_page_model(self.weekly, self.quality, search="20260913")
        self.assertTrue((model.rows["Category"] == "Invalid date").any())

    def test_known_invalid_date_remains_an_issue(self) -> None:
        raw_values = pd.to_numeric(self.quality["Raw Value"], errors="coerce")
        invalid = self.quality[(self.quality["Category"] == "Invalid date") & raw_values.eq(20260913)]
        self.assertFalse(invalid.empty)

    def test_blank_load_status_is_not_flagged(self) -> None:
        row_b = self.quality[self.quality["RowID"].eq("opaque-row-b")]
        unexpected = row_b[(row_b["Category"] == "Unexpected status") & (row_b["Field"] == "LoadStatus")]
        self.assertTrue(unexpected.empty)

    def test_issue_detail_and_complete_identity(self) -> None:
        issue = self.quality[self.quality["RowID"].eq("opaque-row-c")].iloc[0]
        self.assertEqual(identity_for_quality_issue(issue), "vessel c||v003||opaque-block-c")
        self.assertTrue(str(issue["Suggested Correction"]).strip())

    def test_incomplete_identity_has_no_voyage_drilldown(self) -> None:
        issue = pd.Series({"Vessel": "VESSEL A", "Voyage": "V001", "BlockID": ""})
        self.assertIsNone(identity_for_quality_issue(issue))

    def test_no_issues_state_is_clean(self) -> None:
        model = build_data_quality_page_model(self.weekly, self.quality.iloc[0:0])
        self.assertEqual(model.rows.shape[0], 0)
        self.assertIn("No issues found", model.empty_message or "")


class ExportAndIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly, self.history, self.quality = fixture_frames()

    def test_filtered_export_uses_human_columns_and_preserves_source(self) -> None:
        model = build_entity_analytics_model(self.weekly, self.history, self.quality, "vessel", FilterContext(vessel="VESSEL A"))
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.xlsm"
            source.write_bytes(b"read-only-workbook-sentinel")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            destination = Path(temp) / "vessels.csv"
            result = export_visible_csv(model.overview, destination, visible_columns=["Vessel", "Total TEU"])
            after = hashlib.sha256(source.read_bytes()).hexdigest()
            exported = pd.read_csv(destination)
        self.assertTrue(result.success)
        self.assertEqual(exported.columns.tolist(), ["Vessel", "Total TEU"])
        self.assertEqual(exported["Vessel"].tolist(), ["VESSEL A"])
        self.assertEqual(before, after)

    def test_empty_export_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "empty.csv"
            result = export_visible_csv(pd.DataFrame(), path)
            self.assertFalse(result.success)
            self.assertFalse(path.exists())

    def test_state_models_cache_without_reloading_workbook(self) -> None:
        calls = 0

        def loader() -> LoadedWorkbookData:
            nonlocal calls
            calls += 1
            return loaded(self.weekly, self.history, self.quality)

        state = ApplicationState(AppConfig(workbook_path=Path("/tmp/read-only-source.xlsm")), loader=loader)
        state.refresh()
        state.vessel_analytics_page_model()
        state.service_analytics_page_model()
        state.customer_analytics_page_model()
        state.comparison_page_model()
        state.data_quality_page_model()
        state.operational_dashboard_model()
        state.voyage_browser_model()
        state.operational_history_model()
        self.assertEqual(calls, 1)
        self.assertIs(state.vessel_analytics_page_model(), state.vessel_analytics_page_model())

    def test_shared_filter_context_reaches_all_secondary_models(self) -> None:
        state = ApplicationState(
            AppConfig(workbook_path=Path("/tmp/read-only-source.xlsm")),
            loader=lambda: loaded(self.weekly, self.history, self.quality),
        )
        state.refresh()
        state.set_analytical_filter_context(FilterContext(vessel="VESSEL B"))
        self.assertEqual(state.vessel_analytics_page_model().overview["Vessel"].tolist(), ["VESSEL B"])
        self.assertEqual(set(state.comparison_page_model().candidates["Vessel"]), {"VESSEL B"})

    def test_phase_e_routes_and_phase_f_modules_import(self) -> None:
        modules = [
            "src.gui.dashboard_view", "src.gui.voyage_view", "src.gui.history_view", "src.gui.entity_views",
            "src.gui.comparison_view", "src.gui.quality_view", "src.gui.secondary_models", "src.gui.app",
        ]
        for module in modules:
            self.assertIsNotNone(importlib.import_module(module))


if __name__ == "__main__":
    unittest.main()
