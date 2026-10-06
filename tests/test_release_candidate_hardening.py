from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.analytical_filters import FilterContext, apply_history_filters
from src.data_cleaner import clean_history, clean_weekly
from src.gui.exporting import export_visible_csv
from src.gui.operational_models import build_history_model, build_voyage_detail_model
from src.gui.secondary_models import build_comparison_page_model, identity_for_quality_issue
from src.history_processing import (
    IDENTITY_AMBIGUOUS,
    IDENTITY_RESOLVED,
    deduplicate_voyage_events,
    resolve_history_identities,
)
from src.operational_analytics import voyage_load_profiles
from src.quality_analytics import generate_quality_issues
from src.schedule_analytics import schedule_reliability_by_voyage, week_rollover_by_voyage


def _weekly(*rows: dict[str, object]) -> pd.DataFrame:
    return clean_weekly(pd.DataFrame(rows)).dataframe


def _history(weekly: pd.DataFrame, *rows: dict[str, object]) -> pd.DataFrame:
    cleaned = clean_history(pd.DataFrame(rows)).dataframe
    return resolve_history_identities(cleaned, weekly)


def _current_move_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Week": 37,
        "Vessel": "TEST VESSEL",
        "Voyage": "MOVE001",
        "ETA": "2026-09-20",
        "ETD": "2026-09-22",
        "Booking number": "BK-MOVE",
        "CNTR AMT": 4,
        "SIZE": 4,
        "TYPE": "HC",
        "GWT": 60000,
        "POL": "RIX",
        "POD": "RTM",
        "CUSTOMER": "TEST CUSTOMER",
        "BlockID": "2026-W37",
        "RowID": "2026-W36|R05",
        "LoadStatus": "Empty",
    }
    row.update(overrides)
    return row


def _relocation_history_rows(row_id: str = "2026-W36|R05") -> list[dict[str, object]]:
    common = {
        "User": "employee.one",
        "RowID": row_id,
        "Vessel": "TEST VESSEL",
        "Voyage": "MOVE001",
        "Booking number": "BK-MOVE",
    }
    return [
        {
            **common,
            "Timestamp": "2026-09-01 10:00",
            "BlockID": "2026-W36",
            "Week": 36,
            "Field": "GWT",
            "OldValue": 58000,
            "NewValue": 60000,
        },
        {
            **common,
            "Timestamp": "2026-09-02 10:00",
            "BlockID": "2026-W37",
            "Week": 37,
            "Field": "Week",
            "OldValue": 36,
            "NewValue": 37,
        },
        {
            **common,
            "Timestamp": "2026-09-03 10:00",
            "BlockID": "2026-W37",
            "Week": 37,
            "Field": "LoadStatus",
            "OldValue": "Loaded",
            "NewValue": "Empty",
        },
    ]


class RelocationIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly = _weekly(_current_move_row())
        self.history = _history(self.weekly, *_relocation_history_rows())
        self.quality = generate_quality_issues(self.weekly, self.history)
        self.identity_key = voyage_load_profiles(self.weekly).iloc[0]["IdentityKey"]

    def test_row_id_resolves_current_context_without_rewriting_event_context(self) -> None:
        before_move = self.history.iloc[0]
        self.assertEqual(before_move["RowID"], "2026-W36|R05")
        self.assertEqual(before_move["BlockID"], "2026-W36")
        self.assertEqual(before_move["Week"], 36)
        self.assertEqual(before_move["Current BlockID"], "2026-W37")
        self.assertEqual(before_move["Current Week"], 37)
        self.assertEqual(before_move["Identity Resolution"], IDENTITY_RESOLVED)

    def test_pre_and_post_relocation_history_is_one_voyage_detail_timeline(self) -> None:
        detail = build_voyage_detail_model(self.weekly, self.history, self.quality, self.identity_key)
        self.assertTrue(detail.available)
        self.assertEqual(len(detail.raw_timeline), 3)
        self.assertEqual(set(detail.raw_timeline["Field"]), {"GWT", "Week", "LoadStatus"})
        self.assertEqual(set(detail.raw_timeline["IdentityKey"]), {self.identity_key})
        self.assertEqual(set(detail.raw_timeline["RowID"]), {"2026-W36|R05"})

    def test_week_relocation_is_exactly_one_event_and_creates_no_fake_changes(self) -> None:
        fields = self.history["Field"].tolist()
        self.assertEqual(fields.count("Week"), 1)
        self.assertEqual(fields.count("GWT"), 1)
        self.assertNotIn("CNTR AMT", fields)
        self.assertNotIn("SIZE", fields)
        self.assertNotIn("Vessel", fields)
        self.assertNotIn("Voyage", fields)

    def test_schedule_and_rollover_use_current_voyage_without_ghost_instance(self) -> None:
        schedule = schedule_reliability_by_voyage(self.weekly, self.history)
        rollover = week_rollover_by_voyage(self.weekly, self.history)
        self.assertEqual(schedule["IdentityKey"].tolist(), [self.identity_key])
        self.assertEqual(rollover["IdentityKey"].tolist(), [self.identity_key])
        self.assertEqual(int(rollover.iloc[0]["Week Change Count"]), 1)
        self.assertEqual(int(rollover.iloc[0]["Original Week"]), 36)
        self.assertEqual(int(rollover.iloc[0]["Current Week"]), 37)

    def test_current_week_filter_keeps_pre_relocation_events_by_row_id(self) -> None:
        filtered = apply_history_filters(self.history, FilterContext(week=37), current_df=self.weekly)
        self.assertEqual(len(filtered), 3)
        self.assertIn("2026-W36", set(filtered["BlockID"]))

    def test_history_search_supports_row_id_user_and_current_context(self) -> None:
        self.assertEqual(build_history_model(self.weekly, self.history, search="2026-W36|R05").matching_count, 3)
        self.assertEqual(build_history_model(self.weekly, self.history, search="employee.one").matching_count, 3)
        self.assertEqual(build_history_model(self.weekly, self.history, search="2026-W37").matching_count, 3)

    def test_row_id_prefix_mismatch_is_not_a_quality_issue(self) -> None:
        text = " ".join(self.quality.get("Message", pd.Series(dtype=object)).astype(str).tolist()).casefold()
        self.assertNotIn("prefix", text)
        self.assertNotIn("does not match blockid", text)
        self.assertNotIn("does not match week", text)

    def test_empty_reservation_with_same_row_id_does_not_make_history_ambiguous(self) -> None:
        weekly = _weekly(
            _current_move_row(),
            {"Week": 36, "BlockID": "2026-W36", "RowID": "2026-W36|R05"},
        )
        history = _history(weekly, *_relocation_history_rows())
        self.assertEqual(set(history["Identity Resolution"]), {IDENTITY_RESOLVED})

    def test_duplicate_current_operational_row_id_is_critical_and_history_is_ambiguous(self) -> None:
        weekly = _weekly(
            _current_move_row(),
            _current_move_row(**{"Booking number": "BK-OTHER", "Voyage": "MOVE002"}),
        )
        history = _history(weekly, *_relocation_history_rows())
        self.assertEqual(set(history["Identity Resolution"]), {IDENTITY_AMBIGUOUS})
        quality = generate_quality_issues(weekly, history)
        critical = quality[quality["Severity"].eq("Critical")]
        self.assertTrue((critical["Category"] == "Duplicate identity").any())
        self.assertTrue((critical["Category"] == "Ambiguous history identity").any())
        ambiguous_issue = critical[critical["Category"].eq("Ambiguous history identity")].iloc[0]
        self.assertIsNone(identity_for_quality_issue(ambiguous_issue))

    def test_voyage_deduplication_uses_resolved_current_context(self) -> None:
        weekly = _weekly(
            _current_move_row(),
            _current_move_row(**{"RowID": "2026-W36|R06", "Booking number": "BK-2", "CNTR AMT": 1}),
        )
        common_event = {
            "Timestamp": "2026-09-01 09:00",
            "User": "employee.one",
            "BlockID": "2026-W36",
            "Week": 36,
            "Vessel": "TEST VESSEL",
            "Voyage": "MOVE001",
            "Field": "ETA",
            "OldValue": "2026-09-19",
            "NewValue": "2026-09-20",
        }
        history = _history(
            weekly,
            {**common_event, "RowID": "2026-W36|R05", "Booking number": "BK-MOVE"},
            {**common_event, "RowID": "2026-W36|R06", "Booking number": "BK-2"},
        )
        grouped = deduplicate_voyage_events(history)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(int(grouped.iloc[0]["_source_event_count"]), 2)


class FinalContractRegressionTests(unittest.TestCase):
    def test_golden_loaded_empty_and_cancelled_quantities(self) -> None:
        weekly = _weekly(
            _current_move_row(**{"RowID": "r1", "CNTR AMT": 3, "SIZE": 2, "GWT": 30000, "LoadStatus": ""}),
            _current_move_row(**{"RowID": "r2", "CNTR AMT": 4, "SIZE": 4, "GWT": 80000, "LoadStatus": "loaded"}),
            _current_move_row(**{"RowID": "r3", "CNTR AMT": 2, "SIZE": 2, "GWT": 4000, "LoadStatus": "EMPTY"}),
            _current_move_row(**{"RowID": "r4", "CNTR AMT": 3, "SIZE": 4, "GWT": 12000, "LoadStatus": "Empty"}),
            _current_move_row(**{"RowID": "r5", "CNTR AMT": 5, "SIZE": 4, "GWT": 100000, "LoadStatus": "Loaded", "RowStatus": "Cancelled"}),
            _current_move_row(**{"RowID": "r6", "CNTR AMT": 7, "SIZE": 2, "GWT": 14000, "LoadStatus": "Empty", "RowStatus": "Cancelled"}),
        )
        profiles = voyage_load_profiles(weekly)
        row = profiles.iloc[0]
        self.assertEqual(row["Loaded Containers"], 7)
        self.assertEqual(row["Empty Containers"], 5)
        self.assertEqual(row["Total Containers"], 12)
        self.assertEqual(row["Loaded TEU"], 11)
        self.assertEqual(row["Empty TEU"], 8)
        self.assertEqual(row["Total TEU"], 19)
        self.assertEqual(row["Loaded GWT"], 110000)
        self.assertEqual(row["Empty GWT"], 16000)
        self.assertEqual(row["Total GWT"], 126000)
        self.assertEqual(row["Cancelled rows"], 2)

    def test_compare_exposes_loaded_empty_teu_and_gwt_after_relocation(self) -> None:
        weekly = _weekly(
            _current_move_row(),
            _current_move_row(
                **{
                    "Week": 38,
                    "Vessel": "OTHER VESSEL",
                    "Voyage": "KEEP002",
                    "BlockID": "2026-W38",
                    "RowID": "opaque-record-2",
                    "Booking number": "BK-KEEP",
                    "CNTR AMT": 2,
                    "SIZE": 2,
                    "GWT": 20000,
                    "LoadStatus": "Loaded",
                }
            ),
        )
        history = _history(weekly, *_relocation_history_rows())
        candidates = build_comparison_page_model(weekly, history).candidates
        keys = candidates["IdentityKey"].tolist()
        model = build_comparison_page_model(weekly, history, selected_keys=keys)
        self.assertEqual(len(model.rows), 2)
        for column in ["Loaded TEU", "Empty TEU", "Loaded GWT", "Empty GWT"]:
            self.assertIn(column, model.rows.columns)

    def test_export_rejects_excel_destination_but_csv_still_works(self) -> None:
        frame = pd.DataFrame([{"Metric": "Containers", "Value": 12}])
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory) / "operational.xlsm"
            allowed = Path(directory) / "comparison.csv"
            blocked_result = export_visible_csv(frame, blocked)
            allowed_result = export_visible_csv(frame, allowed)
            self.assertFalse(blocked_result.success)
            self.assertFalse(blocked.exists())
            self.assertTrue(allowed_result.success)
            self.assertTrue(allowed.exists())

    def test_windows_setup_uses_python_313_project_venv_and_launcher_does_not_install(self) -> None:
        root = Path(__file__).resolve().parents[1]
        setup = (root / "install_dependencies.bat").read_text(encoding="utf-8")
        launcher = (root / "launch_history_dashboard.bat").read_text(encoding="utf-8")
        hidden_launcher = (root / "launch_history_dashboard.vbs").read_text(encoding="utf-8")
        self.assertIn("-3.13", setup)
        self.assertIn("-m venv .venv", setup)
        self.assertIn(".venv\\Scripts\\python.exe", setup)
        self.assertIn(".venv\\Scripts\\pythonw.exe", launcher)
        self.assertNotIn("pip install", launcher.casefold())
        self.assertIn("pythonw.exe", hidden_launcher)


if __name__ == "__main__":
    unittest.main()
