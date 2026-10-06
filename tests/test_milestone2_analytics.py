from __future__ import annotations

import unittest

import pandas as pd

from src.analytics import (
    calculate_eta_movement,
    calculate_revision_counts,
    get_chronological_timeline,
    get_vessel_summary,
    get_voyage_summary,
    rank_vessels_by_eta_revisions,
    rank_voyages_by_history_events,
)
from src.data_cleaner import clean_history, clean_weekly
from src.excel_reader import EXPECTED_WEEKLY_COLUMNS
from src.filters import filter_history, filter_weekly
from src.validators import EXPECTED_HISTORY_COLUMNS


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
            "Comments 1": "",
            "Booking number": f"BK{index:03d}",
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
            "OldValue": "",
            "NewValue": "",
            "Year": 2026,
            "Month": 9,
        }
        base.update(event)
        hydrated.append(base)
    return clean_history(pd.DataFrame(hydrated)).dataframe


class FilteringTests(unittest.TestCase):
    def test_weekly_filters_can_be_combined_case_insensitively(self) -> None:
        weekly = weekly_frame(
            [
                {"Vessel": "VESSEL A", "Voyage": "V001", "RowID": "2026-W35|R01"},
                {"Vessel": "VESSEL B", "Voyage": "V002", "RowID": "2026-W35|R02"},
            ]
        )

        result = filter_weekly(weekly, vessel="vessel a", voyage="v001", year=2026, month=9)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["RowID"], "2026-W35|R01")

    def test_history_filter_normalizes_field_name(self) -> None:
        history = history_frame(
            [
                {"Field": " eta  ", "OldValue": "05.09.2026", "NewValue": "07.09.2026"},
                {"Field": "Vessel", "OldValue": "A", "NewValue": "B"},
            ]
        )

        result = filter_history(history, field="ETA")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["Field"], "eta")


class ScheduleMovementTests(unittest.TestCase):
    def test_eta_unchanged_without_history(self) -> None:
        weekly = weekly_frame([{"ETA": "2026-09-05"}])
        history = history_frame([])

        movement = calculate_eta_movement(weekly, history, row_id="2026-W35|R01")

        self.assertEqual(movement.history_event_count, 0)
        self.assertEqual(movement.material_revision_count, 0)
        self.assertEqual(movement.net_movement_days, 0)
        self.assertEqual(movement.cumulative_movement_days, 0)
        self.assertEqual(movement.current_source, "WEEKLY")

    def test_initial_eta_entry_is_retained_but_not_revision(self) -> None:
        weekly = weekly_frame([{"ETA": "2026-09-05"}])
        history = history_frame([{"OldValue": "", "NewValue": "05.09.2026"}])

        movement = calculate_eta_movement(weekly, history, row_id="2026-W35|R01")
        timeline = get_chronological_timeline(history, row_id="2026-W35|R01")

        self.assertEqual(len(timeline), 1)
        self.assertEqual(movement.history_event_count, 1)
        self.assertEqual(movement.material_revision_count, 0)
        self.assertEqual(movement.net_movement_days, 0)
        self.assertEqual(movement.cumulative_movement_days, 0)

    def test_one_eta_delay_counts_revision_and_movement(self) -> None:
        weekly = weekly_frame([{"ETA": "2026-09-07"}])
        history = history_frame([{"OldValue": "05.09.2026", "NewValue": "07.09.2026"}])

        movement = calculate_eta_movement(weekly, history, row_id="2026-W35|R01")

        self.assertEqual(movement.material_revision_count, 1)
        self.assertEqual(movement.net_movement_days, 2)
        self.assertEqual(movement.cumulative_movement_days, 2)

    def test_eta_later_then_earlier_separates_net_and_cumulative_movement(self) -> None:
        weekly = weekly_frame([{"ETA": "2026-09-06"}])
        history = history_frame(
            [
                {"Timestamp": "2026-09-02 10:01", "OldValue": "05.09.2026", "NewValue": "07.09.2026"},
                {"Timestamp": "2026-09-02 10:02", "OldValue": "07.09.2026", "NewValue": "06.09.2026"},
            ]
        )

        movement = calculate_eta_movement(weekly, history, row_id="2026-W35|R01")

        self.assertEqual(movement.material_revision_count, 2)
        self.assertEqual(movement.net_movement_days, 1)
        self.assertEqual(movement.cumulative_movement_days, 3)

    def test_invalid_date_history_value_does_not_crash_and_warns(self) -> None:
        weekly = weekly_frame([{"ETA": "2026-09-07"}])
        history = history_frame([{"OldValue": "not a date", "NewValue": "07.09.2026"}])

        movement = calculate_eta_movement(weekly, history, row_id="2026-W35|R01")

        self.assertEqual(movement.material_revision_count, 0)
        self.assertTrue(any("Unparseable date value" in warning for warning in movement.warnings))

    def test_populated_to_blank_is_retained_but_not_normal_schedule_shift(self) -> None:
        weekly = weekly_frame([{"ETA": None}])
        history = history_frame([{"OldValue": "05.09.2026", "NewValue": ""}])

        movement = calculate_eta_movement(weekly, history, row_id="2026-W35|R01")
        timeline = get_chronological_timeline(history, row_id="2026-W35|R01")

        self.assertEqual(len(timeline), 1)
        self.assertEqual(movement.history_event_count, 1)
        self.assertEqual(movement.material_revision_count, 0)
        self.assertIsNone(movement.net_movement_days)


class SummaryAndRankingTests(unittest.TestCase):
    def test_multiple_row_ids_under_same_voyage_are_summarized_when_not_ambiguous(self) -> None:
        weekly = weekly_frame(
            [
                {"RowID": "2026-W35|R01", "Booking number": "BK001"},
                {"RowID": "2026-W35|R02", "Booking number": "BK002"},
            ]
        )
        history = history_frame([{"RowID": "2026-W35|R01", "OldValue": "05.09.2026", "NewValue": "07.09.2026"}])

        summary = get_voyage_summary(weekly, history, "V001")

        self.assertFalse(summary.is_ambiguous)
        self.assertEqual(summary.current_operational_row_count, 2)
        self.assertEqual(summary.total_summary, 2)
        self.assertEqual(summary.affected_row_ids, ["2026-W35|R01", "2026-W35|R02"])

    def test_same_voyage_identifier_across_vessels_or_blocks_is_ambiguous(self) -> None:
        weekly = weekly_frame(
            [
                {"Vessel": "VESSEL A", "Voyage": "V001", "BlockID": "2026-W35", "RowID": "2026-W35|R01"},
                {"Vessel": "VESSEL B", "Voyage": "V001", "BlockID": "2026-W36", "RowID": "2026-W36|R01"},
            ]
        )
        history = history_frame([])

        ambiguous = get_voyage_summary(weekly, history, "V001")
        resolved = get_voyage_summary(weekly, history, "V001", vessel="VESSEL A", block_id="2026-W35")

        self.assertTrue(ambiguous.is_ambiguous)
        self.assertIn("multiple vessels", ambiguous.ambiguity_reason or "")
        self.assertFalse(resolved.is_ambiguous)
        self.assertEqual(resolved.current_operational_row_count, 1)

    def test_cancelled_rows_are_retained_but_excluded_from_operational_totals(self) -> None:
        weekly = weekly_frame(
            [
                {"RowID": "2026-W35|R01", "Summary": 2, "TEU": 2, "TS": 20, "CNTR AMT": 2, "GWT": 20},
                {"RowID": "2026-W35|R02", "RowStatus": "Cancelled", "Summary": 0, "TEU": 0, "TS": 0, "CNTR AMT": 2, "GWT": 20},
            ]
        )
        history = history_frame([])

        summary = get_voyage_summary(weekly, history, "V001")

        self.assertEqual(summary.current_operational_row_count, 1)
        self.assertEqual(summary.cancelled_row_count, 1)
        self.assertEqual(summary.total_summary, 2)

    def test_empty_weekly_still_allows_history_summary(self) -> None:
        weekly = weekly_frame([])
        history = history_frame([{"Vessel": "VESSEL A", "OldValue": "05.09.2026", "NewValue": "07.09.2026"}])

        summary = get_vessel_summary(weekly, history, "VESSEL A")

        self.assertEqual(summary.operational_rows, 0)
        self.assertEqual(summary.history_event_count, 1)
        self.assertEqual(summary.eta_revision_count, 1)

    def test_empty_history_is_safe(self) -> None:
        weekly = weekly_frame([{"ETA": "2026-09-05"}])
        history = history_frame([])

        timeline = get_chronological_timeline(history, row_id="2026-W35|R01")
        movement = calculate_eta_movement(weekly, history, row_id="2026-W35|R01")

        self.assertTrue(timeline.empty)
        self.assertEqual(movement.history_event_count, 0)
        self.assertEqual(movement.material_revision_count, 0)

    def test_vessel_and_voyage_change_events_are_counted_as_text_revisions(self) -> None:
        history = history_frame(
            [
                {"Field": "Vessel", "OldValue": "OLD VESSEL", "NewValue": "NEW VESSEL"},
                {"Field": "Voyage", "OldValue": "V001", "NewValue": "V002"},
            ]
        )

        counts = calculate_revision_counts(history, "RowID")

        self.assertEqual(int(counts.iloc[0]["Vessel_revisions"]), 1)
        self.assertEqual(int(counts.iloc[0]["Voyage_revisions"]), 1)

    def test_rankings_return_structured_tables(self) -> None:
        history = history_frame(
            [
                {"Vessel": "VESSEL A", "Voyage": "V001", "OldValue": "05.09.2026", "NewValue": "07.09.2026"},
                {"Vessel": "VESSEL A", "Voyage": "V001", "OldValue": "07.09.2026", "NewValue": "08.09.2026"},
                {"Vessel": "VESSEL B", "Voyage": "V002", "RowID": "2026-W35|R02", "OldValue": "05.09.2026", "NewValue": "06.09.2026"},
            ]
        )

        vessels = rank_vessels_by_eta_revisions(history)
        voyages = rank_voyages_by_history_events(history)

        self.assertEqual(vessels.iloc[0]["Vessel"], "VESSEL A")
        self.assertEqual(int(vessels.iloc[0]["ETA_revisions"]), 2)
        self.assertEqual(voyages.iloc[0]["Voyage"], "V001")
        self.assertEqual(int(voyages.iloc[0]["total_history_events"]), 2)


if __name__ == "__main__":
    unittest.main()
