from __future__ import annotations

import unittest

import pandas as pd

from src.analytics import calculate_history_metrics, calculate_weekly_metrics
from src.data_cleaner import clean_history, clean_weekly
from src.validators import validate_history, validate_weekly


class WeeklyValidationTests(unittest.TestCase):
    def test_valid_weekly_metrics(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    "Week": 35,
                    "Vessel": "A",
                    "Voyage": "V1",
                    "CNTR AMT": 2,
                    "SIZE": 4,
                    "GWT": 10,
                    "RowStatus": "",
                    "Summary": 2,
                    "TEU": 4,
                    "TS": 10,
                    "BlockID": "2026-W35",
                    "RowID": "2026-W35|R01",
                    "_source_excel_row": 10,
                }
            ]
        )
        cleaned = clean_weekly(raw)
        issues = validate_weekly(cleaned.dataframe)
        metrics = calculate_weekly_metrics(cleaned.dataframe)

        self.assertEqual(issues, [])
        self.assertEqual(metrics.valid_operational_rows, 1)
        self.assertEqual(metrics.unique_block_count, 1)
        self.assertEqual(metrics.total_teu, 4)

    def test_cancelled_rows_must_have_zero_calculations(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    "Week": 35,
                    "CNTR AMT": 2,
                    "SIZE": 4,
                    "GWT": 10,
                    "RowStatus": "Cancelled",
                    "Summary": 2,
                    "TEU": 4,
                    "TS": 10,
                    "BlockID": "2026-W35",
                    "RowID": "2026-W35|R01",
                    "_source_excel_row": 10,
                }
            ]
        )
        cleaned = clean_weekly(raw)
        issues = validate_weekly(cleaned.dataframe)

        self.assertTrue(any("Cancelled row has non-zero Summary" in issue.message for issue in issues))
        self.assertTrue(any(issue.severity == "ERROR" for issue in issues))

    def test_duplicate_row_id_is_error(self) -> None:
        raw = pd.DataFrame(
            [
                {"Week": 35, "RowStatus": "", "RowID": "2026-W35|R01", "BlockID": "2026-W35", "CNTR AMT": 1, "SIZE": 2, "GWT": 5, "Summary": 1, "TEU": 1, "TS": 5},
                {"Week": 35, "RowStatus": "", "RowID": "2026-W35|R01", "BlockID": "2026-W35", "CNTR AMT": 1, "SIZE": 2, "GWT": 5, "Summary": 1, "TEU": 1, "TS": 5},
            ]
        )
        cleaned = clean_weekly(raw)
        issues = validate_weekly(cleaned.dataframe)

        self.assertTrue(any("Duplicate RowID" in issue.message for issue in issues))


class HistoryValidationTests(unittest.TestCase):
    def test_history_metrics(self) -> None:
        raw = pd.DataFrame(
            [
                {"Timestamp": "2026-09-02 10:00", "User": "u", "BlockID": "2026-W35", "RowID": "2026-W35|R01", "Week": 35, "Field": "ETA"},
                {"Timestamp": "2026-09-02 10:01", "User": "u", "BlockID": "2026-W35", "RowID": "2026-W35|R02", "Week": 35, "Field": "Vessel"},
            ]
        )
        for column in ["Vessel", "Voyage", "Booking number", "Comments 1", "Comments 2", "CancelReason", "OldValue", "NewValue", "Year", "Month"]:
            raw[column] = None
        cleaned = clean_history(raw)
        issues = validate_history(cleaned.dataframe)
        metrics = calculate_history_metrics(cleaned.dataframe)

        self.assertEqual(issues, [])
        self.assertEqual(metrics.history_records, 2)
        self.assertEqual(metrics.eta_changes, 1)
        self.assertEqual(metrics.vessel_changes, 1)


if __name__ == "__main__":
    unittest.main()
