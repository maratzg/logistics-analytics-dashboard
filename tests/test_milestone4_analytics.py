from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.advanced_analytics import (
    cancellations_by_vessel,
    history_events_by_month,
    history_events_by_quarter,
    largest_cumulative_eta_movement_voyages,
    largest_eta_movement_voyages,
    material_revisions_by_vessel,
    material_revisions_by_voyage,
    operational_by_vessel,
    prepare_chart_series,
    voyage_comparison_table,
    voyage_instance_options,
    voyage_performance_table,
    vessel_schedule_performance,
)
from src.analytics import get_voyage_summary
from src.app_state import ApplicationState, LoadedWorkbookData
from src.config import AppConfig
from src.data_cleaner import clean_history, clean_weekly
from src.excel_reader import EXPECTED_WEEKLY_COLUMNS
from src.models import MetricsHistory, MetricsWeekly
from src.validators import EXPECTED_HISTORY_COLUMNS


def weekly_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return clean_weekly(pd.DataFrame(columns=EXPECTED_WEEKLY_COLUMNS)).dataframe

    hydrated = []
    for row in rows:
        base = {
            "Week": 35,
            "Vessel": "VESSEL A",
            "Voyage": "A1",
            "ETA": "2026-09-05",
            "ETD": "2026-09-06",
            "Cut-Off": "2026-09-04",
            "ETA T/S": "2026-09-12",
            "Comments 1": "",
            "Booking number": "BK",
            "O/V": "",
            "SVC": "",
            "Booking status": "",
            "CNTR AMT": 1,
            "SIZE": 2,
            "TYPE": "",
            "GWT": 10,
            "POL": "",
            "EU TS": "",
            "POD CODE": "",
            "POD": "RIX",
            "CUSTOMER": "Customer",
            "Comments 2": "",
            "RowStatus": "",
            "CancelReason": "",
            "Summary": 1,
            "TEU": 1,
            "TS": 10,
            "BlockID": "2026-W35",
            "RowID": "2026-W35|R01",
        }
        base.update(row)
        hydrated.append(base)
    return clean_weekly(pd.DataFrame(hydrated)).dataframe


def history_frame(events: list[dict]) -> pd.DataFrame:
    if not events:
        return clean_history(pd.DataFrame(columns=EXPECTED_HISTORY_COLUMNS)).dataframe

    hydrated = []
    for event in events:
        base = {
            "Timestamp": "2026-09-02 10:00",
            "User": "tester",
            "BlockID": "2026-W35",
            "RowID": "2026-W35|R01",
            "Week": 35,
            "Vessel": "VESSEL A",
            "Voyage": "A1",
            "Booking number": "BK",
            "Comments 1": "",
            "Comments 2": "",
            "CancelReason": "",
            "Field": "ETA",
            "OldValue": "01.09.2026",
            "NewValue": "05.09.2026",
            "Year": 2026,
            "Month": 9,
        }
        base.update(event)
        hydrated.append(base)
    return clean_history(pd.DataFrame(hydrated)).dataframe


def sample_weekly() -> pd.DataFrame:
    return weekly_frame(
        [
            {"Vessel": "VESSEL A", "Voyage": "A1", "BlockID": "2026-W35", "RowID": "2026-W35|R01", "Booking number": "BK-A1-1", "Summary": 1, "TEU": 1, "TS": 10, "GWT": 10, "ETA": "2026-09-05"},
            {"Vessel": "VESSEL A", "Voyage": "A1", "BlockID": "2026-W35", "RowID": "2026-W35|R02", "Booking number": "BK-A1-2", "Summary": 2, "TEU": 4, "TS": 20, "CNTR AMT": 2, "SIZE": 4, "GWT": 20, "ETA": "2026-09-05"},
            {"Vessel": "VESSEL A", "Voyage": "A2", "BlockID": "2026-W36", "RowID": "2026-W36|R01", "Booking number": "BK-A2-1", "Summary": 1, "TEU": 1, "TS": 8, "GWT": 8, "ETA": "2026-09-09"},
            {"Vessel": "VESSEL A", "Voyage": "A2", "BlockID": "2026-W36", "RowID": "2026-W36|R02", "Booking number": "BK-A2-X", "RowStatus": "Cancelled", "Summary": 0, "TEU": 0, "TS": 0, "ETA": "2026-09-09"},
            {"Vessel": "VESSEL B", "Voyage": "B1", "BlockID": "2026-W37", "RowID": "2026-W37|R01", "Booking number": "BK-B1-1", "Summary": 3, "TEU": 3, "TS": 30, "CNTR AMT": 3, "GWT": 30, "ETA": "2026-09-15"},
            {"Vessel": "VESSEL A", "Voyage": "AMB", "BlockID": "2026-W38", "RowID": "2026-W38|R01", "Booking number": "BK-AMB-A", "Summary": 1, "TEU": 1, "TS": 4, "GWT": 4, "ETA": "2026-09-20"},
            {"Vessel": "VESSEL B", "Voyage": "AMB", "BlockID": "2026-W39", "RowID": "2026-W39|R01", "Booking number": "BK-AMB-B", "Summary": 1, "TEU": 1, "TS": 5, "GWT": 5, "ETA": "2026-09-20"},
        ]
    )


def sample_history() -> pd.DataFrame:
    return history_frame(
        [
            {"Timestamp": "2026-08-20 09:00", "Vessel": "VESSEL A", "Voyage": "A1", "BlockID": "2026-W35", "RowID": "2026-W35|R01", "OldValue": "01.09.2026", "NewValue": "07.09.2026"},
            {"Timestamp": "2026-09-01 09:00", "Vessel": "VESSEL A", "Voyage": "A1", "BlockID": "2026-W35", "RowID": "2026-W35|R01", "OldValue": "07.09.2026", "NewValue": "05.09.2026"},
            {"Timestamp": "2026-09-02 09:00", "Vessel": "VESSEL A", "Voyage": "A1", "BlockID": "2026-W35", "RowID": "2026-W35|R01", "Field": "ETD", "OldValue": "06.09.2026", "NewValue": "08.09.2026"},
            {"Timestamp": "2026-09-03 09:00", "Vessel": "VESSEL A", "Voyage": "A1", "BlockID": "2026-W35", "RowID": "2026-W35|R01", "Field": "Cut-Off", "OldValue": "30.08.2026", "NewValue": "31.08.2026"},
            {"Timestamp": "2026-09-04 09:00", "Vessel": "VESSEL A", "Voyage": "A1", "BlockID": "2026-W35", "RowID": "2026-W35|R01", "Field": "ETA T/S", "OldValue": "12.09.2026", "NewValue": "13.09.2026"},
            {"Timestamp": "2026-09-15 09:00", "Vessel": "VESSEL A", "Voyage": "A2", "BlockID": "2026-W36", "RowID": "2026-W36|R01", "OldValue": "10.09.2026", "NewValue": "09.09.2026"},
            {"Timestamp": "2026-10-01 09:00", "Vessel": "VESSEL B", "Voyage": "B1", "BlockID": "2026-W37", "RowID": "2026-W37|R01", "Field": "Vessel", "OldValue": "OLD VESSEL", "NewValue": "VESSEL B"},
            {"Timestamp": "2026-10-02 09:00", "Vessel": "VESSEL B", "Voyage": "B1", "BlockID": "2026-W37", "RowID": "2026-W37|R01", "Field": "Voyage", "OldValue": "B0", "NewValue": "B1"},
        ]
    )


def config() -> AppConfig:
    return AppConfig(Path("/tmp/source.xlsm"), ["WEEKLY", "LOG_HISTORY"], [], 25)


def loaded(weekly: pd.DataFrame, history: pd.DataFrame) -> LoadedWorkbookData:
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
            etd_changes=int(history["Field"].astype(str).str.strip().eq("ETD").sum()) if "Field" in history.columns else 0,
            cut_off_changes=int(history["Field"].astype(str).str.strip().eq("Cut-Off").sum()) if "Field" in history.columns else 0,
            vessel_changes=int(history["Field"].astype(str).str.strip().eq("Vessel").sum()) if "Field" in history.columns else 0,
            voyage_changes=int(history["Field"].astype(str).str.strip().eq("Voyage").sum()) if "Field" in history.columns else 0,
            eta_ts_changes=int(history["Field"].astype(str).str.strip().eq("ETA T/S").sum()) if "Field" in history.columns else 0,
        ),
        issues=[],
        loaded_at=datetime(2026, 9, 2, 10, 30),
    )


class Milestone4AnalyticsTests(unittest.TestCase):
    def test_teu_ts_summary_aggregation_by_vessel(self) -> None:
        result = operational_by_vessel(sample_weekly())
        vessel_a = result[result["Vessel"] == "VESSEL A"].iloc[0]

        self.assertEqual(vessel_a["TEU"], 7)
        self.assertEqual(vessel_a["TS"], 42)
        self.assertEqual(vessel_a["Summary"], 5)

    def test_cancellation_aggregation(self) -> None:
        result = cancellations_by_vessel(sample_weekly())

        self.assertEqual(result.iloc[0]["Vessel"], "VESSEL A")
        self.assertEqual(result.iloc[0]["Cancelled rows"], 1)

    def test_history_events_by_month_and_quarter(self) -> None:
        by_month = history_events_by_month(sample_history())
        by_quarter = history_events_by_quarter(sample_history())

        self.assertEqual(dict(zip(by_month["History Month"], by_month["History events"], strict=False)), {"2026-08": 1, "2026-09": 5, "2026-10": 2})
        self.assertEqual(dict(zip(by_quarter["History Quarter"], by_quarter["History events"], strict=False)), {"2026 Q3": 6, "2026 Q4": 2})

    def test_material_eta_revisions_by_vessel_and_voyage(self) -> None:
        by_vessel = material_revisions_by_vessel(sample_history(), "ETA")
        by_voyage = material_revisions_by_voyage(sample_history(), "ETA")

        self.assertEqual(int(by_vessel[by_vessel["Vessel"] == "VESSEL A"].iloc[0]["ETA revisions"]), 3)
        a1 = by_voyage[by_voyage["Voyage"] == "A1"].iloc[0]
        a2 = by_voyage[by_voyage["Voyage"] == "A2"].iloc[0]
        self.assertEqual(int(a1["ETA revisions"]), 2)
        self.assertEqual(int(a2["ETA revisions"]), 1)

    def test_average_eta_movement_by_vessel(self) -> None:
        result = vessel_schedule_performance(sample_weekly(), sample_history())
        vessel_a = result[result["Vessel"] == "VESSEL A"].iloc[0]

        self.assertAlmostEqual(vessel_a["Average net ETA movement"], 1.0)
        self.assertAlmostEqual(vessel_a["Average absolute ETA movement"], 5 / 3)
        self.assertEqual(vessel_a["Maximum delay"], 4)
        self.assertEqual(vessel_a["Maximum early movement"], -1)

    def test_largest_eta_movement_and_cumulative_rankings(self) -> None:
        net = largest_eta_movement_voyages(sample_weekly(), sample_history())
        cumulative = largest_cumulative_eta_movement_voyages(sample_weekly(), sample_history())

        self.assertEqual(net.iloc[0]["Voyage"], "A1")
        self.assertEqual(net.iloc[0]["Abs net ETA movement"], 4)
        self.assertEqual(cumulative.iloc[0]["Voyage"], "A1")
        self.assertEqual(cumulative.iloc[0]["Cumulative ETA movement"], 8)

    def test_voyage_comparison_data_generation(self) -> None:
        weekly = sample_weekly()
        history = sample_history()
        options = voyage_instance_options(weekly, history)
        selected = options[options["Voyage"].isin(["A1", "A2"])]["IdentityKey"].tolist()

        comparison = voyage_comparison_table(weekly, history, selected)

        self.assertEqual(len(comparison), 2)
        self.assertEqual(set(comparison["Voyage"]), {"A1", "A2"})
        self.assertEqual(comparison[comparison["Voyage"] == "A1"].iloc[0]["Net ETA movement"], 4)
        self.assertEqual(comparison[comparison["Voyage"] == "A2"].iloc[0]["Net ETA movement"], -1)

    def test_comparison_identity_disambiguation_and_ambiguous_voyage_protection(self) -> None:
        weekly = sample_weekly()
        history = sample_history()
        options = voyage_instance_options(weekly, history)
        ambiguous_options = options[options["Voyage"] == "AMB"]
        summary = get_voyage_summary(weekly, history, "AMB")

        self.assertEqual(len(ambiguous_options), 2)
        self.assertNotEqual(ambiguous_options.iloc[0]["IdentityKey"], ambiguous_options.iloc[1]["IdentityKey"])
        self.assertTrue(summary.is_ambiguous)

    def test_vessel_page_view_model(self) -> None:
        state = ApplicationState(config(), loader=lambda: loaded(sample_weekly(), sample_history()))
        state.refresh()

        model = state.vessel_analytics("VESSEL A")

        self.assertEqual(model.summary.total_teu, 7)
        self.assertEqual(model.material_revision_counts["ETA"], 3)
        self.assertEqual(len(model.voyage_table), 3)

    def test_empty_vessel_and_empty_comparison_state(self) -> None:
        state = ApplicationState(config(), loader=lambda: loaded(weekly_frame([]), history_frame([])))
        state.refresh()

        vessel_model = state.vessel_analytics("All")
        comparison_model = state.comparison_model([])

        self.assertIn("No vessels", vessel_model.empty_message or "")
        self.assertIn("At least two voyage", comparison_model.empty_message or "")

    def test_chart_input_generation_empty_and_nan_handling(self) -> None:
        empty = prepare_chart_series(pd.DataFrame(), label_column="Label", value_column="Value")
        nan_source = pd.DataFrame({"Label": ["A", "B"], "Value": [float("nan"), 2]})
        cleaned = prepare_chart_series(nan_source, label_column="Label", value_column="Value")

        self.assertTrue(empty.empty)
        self.assertEqual(len(cleaned), 1)
        self.assertFalse(cleaned["Value"].isna().any())
        self.assertEqual(cleaned.iloc[0]["Label"], "B")

    def test_refresh_updates_milestone4_dashboard_analytics(self) -> None:
        calls = [
            loaded(weekly_frame([{"Vessel": "VESSEL A", "TEU": 1}]), history_frame([])),
            loaded(weekly_frame([{"Vessel": "VESSEL B", "TEU": 5}]), history_frame([])),
        ]
        state = ApplicationState(config(), loader=lambda: calls.pop(0))

        state.refresh()
        first = state.dashboard_model().teu_by_vessel.iloc[0]["Label"]
        state.refresh()
        second = state.dashboard_model().teu_by_vessel.iloc[0]["Label"]

        self.assertEqual(first, "VESSEL A")
        self.assertEqual(second, "VESSEL B")

    def test_voyage_performance_table_preserves_no_change_voyage_as_zero_movement(self) -> None:
        table = voyage_performance_table(sample_weekly(), sample_history())
        b1 = table[table["Voyage"] == "B1"].iloc[0]

        self.assertEqual(b1["ETA revisions"], 0)
        self.assertEqual(b1["Net ETA movement"], 0)


if __name__ == "__main__":
    unittest.main()
