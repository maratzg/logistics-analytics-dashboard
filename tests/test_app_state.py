from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.app_state import ApplicationState, LoadedWorkbookData
from src.config import AppConfig
from src.data_cleaner import clean_history, clean_weekly
from src.excel_reader import EXPECTED_WEEKLY_COLUMNS
from src.models import MetricsHistory, MetricsWeekly
from src.validators import EXPECTED_HISTORY_COLUMNS


def config() -> AppConfig:
    return AppConfig(
        workbook_path=Path("/tmp/source.xlsm"),
        required_sheets=["WEEKLY", "LOG_HISTORY"],
        optional_sheets=[],
        max_issue_details=25,
    )


def weekly_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return clean_weekly(pd.DataFrame(columns=EXPECTED_WEEKLY_COLUMNS)).dataframe

    hydrated = []
    for index, row in enumerate(rows, start=1):
        base = {
            "Week": 35,
            "Vessel": "VESSEL A",
            "Voyage": "V001",
            "ETA": "2026-09-05",
            "ETD": "2026-09-06",
            "Cut-Off": "2026-09-04",
            "ETA T/S": "2026-09-10",
            "Booking number": f"BK{index:03d}",
            "CNTR AMT": 1,
            "SIZE": 2,
            "GWT": 10,
            "CUSTOMER": "Customer",
            "POD": "RIX",
            "RowStatus": "",
            "CancelReason": "",
            "Summary": 1,
            "TEU": 1,
            "TS": 10,
            "BlockID": "2026-W35",
            "RowID": f"2026-W35|R{index:02d}",
        }
        base.update(row)
        hydrated.append(base)
    return clean_weekly(pd.DataFrame(hydrated)).dataframe


def history_frame(events: list[dict]) -> pd.DataFrame:
    if not events:
        return clean_history(pd.DataFrame(columns=EXPECTED_HISTORY_COLUMNS)).dataframe

    hydrated = []
    for index, event in enumerate(events, start=1):
        base = {
            "Timestamp": f"2026-09-02 10:{index:02d}",
            "User": "tester",
            "BlockID": "2026-W35",
            "RowID": "2026-W35|R01",
            "Week": 35,
            "Vessel": "VESSEL A",
            "Voyage": "V001",
            "Booking number": "BK001",
            "Comments 1": "",
            "Comments 2": "",
            "CancelReason": "",
            "Field": "ETA",
            "OldValue": "05.09.2026",
            "NewValue": "07.09.2026",
            "Year": 2026,
            "Month": 9,
        }
        base.update(event)
        hydrated.append(base)
    return clean_history(pd.DataFrame(hydrated)).dataframe


def loaded(weekly: pd.DataFrame, history: pd.DataFrame, *, loaded_at: datetime | None = None) -> LoadedWorkbookData:
    active = weekly[weekly["_is_operational"]] if "_is_operational" in weekly.columns else weekly
    cancelled = active["RowStatus"].astype(str).str.upper().eq("CANCELLED") if "RowStatus" in active.columns else pd.Series(dtype=bool)
    return LoadedWorkbookData(
        workbook_path=Path("/tmp/source.xlsm"),
        structure=None,
        weekly_df=weekly,
        history_df=history,
        weekly_metrics=MetricsWeekly(
            valid_operational_rows=int(len(active)),
            cancelled_rows=int(cancelled.sum()),
            unique_block_count=int(active["BlockID"].nunique()) if "BlockID" in active.columns else 0,
            total_summary=float(pd.to_numeric(active.get("Summary", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
            total_teu=float(pd.to_numeric(active.get("TEU", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
            total_ts=float(pd.to_numeric(active.get("TS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        ),
        history_metrics=MetricsHistory(
            history_records=int(len(history)),
            eta_changes=int(history["Field"].astype(str).str.strip().eq("ETA").sum()) if "Field" in history.columns else 0,
            etd_changes=0,
            cut_off_changes=0,
            vessel_changes=int(history["Field"].astype(str).str.strip().eq("Vessel").sum()) if "Field" in history.columns else 0,
            voyage_changes=int(history["Field"].astype(str).str.strip().eq("Voyage").sum()) if "Field" in history.columns else 0,
            eta_ts_changes=0,
        ),
        issues=[],
        loaded_at=loaded_at or datetime(2026, 9, 2, 10, 30),
    )


class AppStateTests(unittest.TestCase):
    def test_application_state_loads_valid_dataframes(self) -> None:
        state = ApplicationState(config(), loader=lambda: loaded(weekly_frame([{}]), history_frame([{}])))

        result = state.refresh()

        self.assertTrue(result.success)
        self.assertIsNotNone(state.data)
        self.assertEqual(state.data.weekly_metrics.valid_operational_rows, 1)
        self.assertEqual(state.data.history_metrics.history_records, 1)

    def test_refresh_replaces_data_after_successful_reload(self) -> None:
        calls = [
            loaded(weekly_frame([{"Vessel": "VESSEL A"}]), history_frame([])),
            loaded(weekly_frame([{"Vessel": "VESSEL B"}]), history_frame([])),
        ]
        state = ApplicationState(config(), loader=lambda: calls.pop(0))

        state.refresh()
        state.refresh()

        self.assertEqual(state.data.weekly_df.iloc[0]["Vessel"], "VESSEL B")

    def test_failed_refresh_preserves_last_good_data(self) -> None:
        calls = [loaded(weekly_frame([{"Vessel": "VESSEL A"}]), history_frame([]))]

        def loader() -> LoadedWorkbookData:
            if calls:
                return calls.pop(0)
            raise FileNotFoundError("missing workbook")

        state = ApplicationState(config(), loader=loader)
        first = state.refresh()
        second = state.refresh()

        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertEqual(state.data.weekly_df.iloc[0]["Vessel"], "VESSEL A")
        self.assertIn("previously loaded", state.load_status)

    def test_dynamic_history_filter_options_are_generated(self) -> None:
        state = ApplicationState(
            config(),
            loader=lambda: loaded(
                weekly_frame([]),
                history_frame([{"Vessel": "VESSEL A", "Field": "ETA"}, {"Vessel": "VESSEL B", "Field": "Vessel"}]),
            ),
        )
        state.refresh()

        options = state.selector_options().history_filters

        self.assertEqual(options["Vessel"], ["All", "VESSEL A", "VESSEL B"])
        self.assertEqual(options["Field"], ["All", "ETA", "Vessel"])

    def test_voyage_selector_values_are_generated_from_weekly_and_history(self) -> None:
        state = ApplicationState(
            config(),
            loader=lambda: loaded(
                weekly_frame([{"Voyage": "V001"}]),
                history_frame([{"Voyage": "V002", "RowID": "2026-W35|R02"}]),
            ),
        )
        state.refresh()

        options = state.selector_options()

        self.assertEqual(options.voyages, ["All", "V001", "V002"])

    def test_empty_weekly_produces_dashboard_empty_state_model(self) -> None:
        state = ApplicationState(config(), loader=lambda: loaded(weekly_frame([]), history_frame([{}])))
        state.refresh()

        model = state.dashboard_model()

        self.assertFalse(model.has_weekly_data)
        self.assertTrue(model.has_history_data)
        self.assertIn("No active WEEKLY", model.empty_message or "")

    def test_empty_history_produces_history_empty_state_model(self) -> None:
        state = ApplicationState(config(), loader=lambda: loaded(weekly_frame([{}]), history_frame([])))
        state.refresh()

        model = state.history_model()

        self.assertEqual(model.matching_count, 0)
        self.assertIn("No history records", model.empty_message or "")

    def test_ambiguity_state_is_surfaced(self) -> None:
        state = ApplicationState(
            config(),
            loader=lambda: loaded(
                weekly_frame(
                    [
                        {"Vessel": "VESSEL A", "Voyage": "V001", "BlockID": "2026-W35", "RowID": "2026-W35|R01"},
                        {"Vessel": "VESSEL B", "Voyage": "V001", "BlockID": "2026-W36", "RowID": "2026-W36|R01"},
                    ]
                ),
                history_frame([]),
            ),
        )
        state.refresh()

        summary = state.voyage_summary("V001")

        self.assertTrue(summary.is_ambiguous)
        self.assertGreaterEqual(len(summary.candidate_groups), 2)

    def test_dashboard_kpis_use_material_revisions_not_raw_event_counts(self) -> None:
        state = ApplicationState(
            config(),
            loader=lambda: loaded(
                weekly_frame([{"ETA": "2026-09-07"}]),
                history_frame(
                    [
                        {"OldValue": "", "NewValue": "05.09.2026"},
                        {"OldValue": "05.09.2026", "NewValue": "07.09.2026"},
                    ]
                ),
            ),
        )
        state.refresh()

        model = state.dashboard_model()

        self.assertEqual(model.history_metrics.history_records, 2)
        self.assertEqual(model.material_revision_counts["ETA"], 1)

    def test_history_filters_work_together_in_state_model(self) -> None:
        state = ApplicationState(
            config(),
            loader=lambda: loaded(
                weekly_frame([]),
                history_frame(
                    [
                        {"Vessel": "VESSEL A", "Timestamp": "2026-09-02 10:00", "Year": 2026, "Field": "ETA"},
                        {"Vessel": "VESSEL A", "Timestamp": "2025-09-02 10:00", "Year": 2025, "Field": "ETA"},
                        {"Vessel": "VESSEL B", "Timestamp": "2026-09-02 10:00", "Year": 2026, "Field": "ETA"},
                    ]
                ),
            ),
        )
        state.refresh()

        model = state.history_model({"Vessel": "VESSEL A", "Year": "2026", "Field": "eta"})

        self.assertEqual(model.matching_count, 1)
        self.assertEqual(model.rows.iloc[0]["Vessel"], "VESSEL A")


if __name__ == "__main__":
    unittest.main()
