from __future__ import annotations

import unittest

import pandas as pd

from src.analytical_filters import FilterContext, HistoryPeriodContext, apply_current_filters, apply_history_filters
from src.anomaly_detection import detect_explainable_anomalies, distribution_summary
from src.cargo_evolution import cargo_evolution_foundation, forecast_readiness
from src.comparison_analytics import comparison_candidates, compare_voyage_instances
from src.data_cleaner import clean_history, clean_weekly
from src.entity_analytics import customer_analytics, route_destination_analytics, service_analytics
from src.history_analytics import booking_churn, cancellation_events, cancellation_reasons, cancellation_summary_by
from src.history_processing import deduplicate_voyage_events
from src.operational_analytics import (
    empty_container_analytics,
    equipment_mix,
    safe_divide,
    voyage_load_profiles,
    weight_intensity_profiles,
)
from src.quality_analytics import generate_quality_issues
from src.schedule_analytics import (
    aggregate_schedule_reliability,
    aggregate_week_rollover,
    material_schedule_events,
    schedule_reliability_by_voyage,
    week_rollover_by_voyage,
)
from src.time_analytics import current_period_aggregation, history_period_aggregation


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


def cleaned_weekly(rows: list[dict[str, object]]) -> pd.DataFrame:
    return clean_weekly(pd.DataFrame(rows)).dataframe


def cleaned_history(rows: list[dict[str, object]]) -> pd.DataFrame:
    return clean_history(pd.DataFrame(rows)).dataframe


class PhaseCCarriedForwardTests(unittest.TestCase):
    def test_generated_identity_rows_are_not_analytical_rows(self) -> None:
        generated = {"Week": 39, "BlockID": "opaque-generated", "RowID": "opaque-empty-row"}
        frame = cleaned_weekly([generated, generated, weekly_row()])

        self.assertTrue(bool(frame.iloc[0]["_has_stable_identity"]))
        self.assertFalse(bool(frame.iloc[0]["_has_operational_payload"]))
        self.assertFalse(bool(frame.iloc[0]["_is_operational"]))
        self.assertEqual(len(voyage_load_profiles(frame)), 1)
        quality = generate_quality_issues(frame, cleaned_history([]))
        self.assertNotIn("Duplicate identity", set(quality["Category"]))
        self.assertFalse((generate_quality_issues(frame, cleaned_history([]))["Category"] == "Duplicate identity").any())

    def test_incomplete_voyage_identity_is_not_merged_into_a_profile(self) -> None:
        frame = cleaned_weekly(
            [
                weekly_row(RowID="ambiguous-1", BlockID=""),
                weekly_row(RowID="ambiguous-2", BlockID=""),
                weekly_row(RowID="complete"),
            ]
        )

        profiles = voyage_load_profiles(frame)
        self.assertEqual(frame["_is_operational"].sum(), 3)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles.iloc[0]["BlockID"], "opaque-block-a")

    def test_explicit_cancellation_without_remaining_cargo_payload_is_retained(self) -> None:
        frame = cleaned_weekly(
            [
                {
                    "Week": 39,
                    "BlockID": "opaque-cancelled-block",
                    "RowID": "opaque-cancelled-row",
                    "RowStatus": "Cancelled",
                    "CancelReason": "Removed booking",
                }
            ]
        )

        self.assertTrue(bool(frame.iloc[0]["_is_operational"]))
        self.assertEqual(voyage_load_profiles(frame).shape[0], 0)

    def test_unknown_load_status_remains_in_totals_but_not_splits(self) -> None:
        frame = cleaned_weekly([weekly_row(LoadStatus="unexpected", **{"CNTR AMT": 3, "SIZE": 4, "GWT": 20})])
        profile = voyage_load_profiles(frame).iloc[0]

        self.assertEqual(profile["Total Containers"], 3)
        self.assertEqual(profile["Total TEU"], 6)
        self.assertEqual(profile["Total GWT"], 20)
        self.assertEqual(profile["Unclassified Containers"], 3)
        self.assertEqual(profile["Loaded Containers"], 0)
        self.assertEqual(profile["Empty Containers"], 0)


class PhaseCFilteringAndOperationalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly = cleaned_weekly(
            [
                weekly_row(),
                weekly_row(RowID="opaque-row-2", **{"Booking number": "BK-2", "LoadStatus": "Empty", "CNTR AMT": 3, "SIZE": 4, "GWT": 18}),
                weekly_row(RowID="opaque-row-3", **{"Booking number": "BK-3", "LoadStatus": "mystery", "CNTR AMT": 1, "SIZE": 4, "GWT": 5}),
                weekly_row(RowID="opaque-row-4", **{"Booking number": "BK-4", "RowStatus": "Cancelled", "CancelReason": "Customer request", "CNTR AMT": 5, "SIZE": 4, "GWT": 30}),
                weekly_row(RowID="opaque-row-b", BlockID="opaque-block-b", Vessel="VESSEL B", Voyage="V002", Week=40, SVC="S2", POL="TALLINN", POD="HAMBURG", **{"POD CODE": "DEHAM", "CUSTOMER": "Bob", "Booking number": "BK-5", "ETA": "2026-10-03", "ETD": "2026-10-04", "CNTR AMT": 4, "SIZE": 2, "GWT": 24}),
            ]
        )

    def test_shared_filter_context(self) -> None:
        context = FilterContext(vessel="vessel b", week=40, eta_month="2026-10", eta_year=2026, svc="s2", pol="tallinn", pod="hamburg", customer="bob", load_status="loaded")
        result = apply_current_filters(self.weekly, context)
        self.assertEqual(result["RowID"].tolist(), ["opaque-row-b"])

    def test_voyage_profile_ratios_equipment_and_intensity(self) -> None:
        profile = voyage_load_profiles(self.weekly, FilterContext(voyage="V001")).iloc[0]
        self.assertEqual(profile["Active rows"], 3)
        self.assertEqual(profile["Cancelled rows"], 1)
        self.assertEqual(profile["Total Containers"], 6)
        self.assertEqual(profile["Loaded Containers"], 2)
        self.assertEqual(profile["Empty Containers"], 3)
        self.assertEqual(profile["Unclassified Containers"], 1)
        self.assertAlmostEqual(profile["Loaded %"], 2 / 6)
        self.assertAlmostEqual(profile["Empty Container Ratio"], 3 / 5)
        self.assertEqual(profile["Total TEU"], 10)
        self.assertEqual(profile["Unclassified TEU"], 2)
        self.assertEqual(profile["Total 20ft"], 2)
        self.assertEqual(profile["Total 40ft"], 4)
        self.assertAlmostEqual(profile["Cancellation Rate"], 0.25)
        self.assertAlmostEqual(profile["Loaded GWT / Loaded TEU"], 6)

    def test_empty_equipment_and_weight_views(self) -> None:
        empty = empty_container_analytics(self.weekly, "Vessel")
        mix = equipment_mix(self.weekly, "Vessel")
        intensity = weight_intensity_profiles(self.weekly)
        self.assertIn("Unclassified TEU", empty.columns)
        self.assertAlmostEqual(mix.iloc[0]["Total 40ft Share"], 4 / 6)
        self.assertEqual(len(intensity), 2)
        self.assertIsNone(safe_divide(1, 0))

    def test_current_time_aggregation_and_trailing_average(self) -> None:
        result = current_period_aggregation(self.weekly, "ETA Month", trailing_window=2)
        self.assertEqual(result["ETA Month"].tolist(), ["2026-09", "2026-10"])
        self.assertTrue(pd.isna(result.iloc[0]["Total TEU 2-Period Average"]))
        self.assertFalse(pd.isna(result.iloc[1]["Total TEU 2-Period Average"]))


class PhaseCHistoryAndScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly = cleaned_weekly([weekly_row(), weekly_row(RowID="opaque-row-2", **{"Booking number": "BK-2"})])
        self.history = cleaned_history(
            [
                history_row(RowID="opaque-row-0", OldValue="[bulk edit]", NewValue="2026-09-12", Timestamp="2026-09-09 09:00:00"),
                history_row(RowID="opaque-row-1"),
                history_row(RowID="opaque-row-2", **{"Booking number": "BK-2"}),
                history_row(RowID="opaque-row-1", Timestamp="2026-09-11 10:00:00", OldValue="2026-09-14", NewValue="2026-09-15"),
                history_row(RowID="opaque-row-1", Field="Week", Timestamp="2026-09-10 11:00:00", OldValue=37, NewValue=38),
                history_row(RowID="opaque-row-2", **{"Booking number": "BK-2", "Field": "Week", "Timestamp": "2026-09-10 11:00:00", "OldValue": 37, "NewValue": 38}),
                history_row(RowID="opaque-row-1", Field="Week", Timestamp="2026-09-11 11:00:00", OldValue=38, NewValue=39),
            ]
        )

    def test_voyage_event_deduplication_edge_cases(self) -> None:
        extra = cleaned_history(
            [
                history_row(RowID="r1"),
                history_row(RowID="r2"),
                history_row(RowID="r3", NewValue="2026-09-13"),
                history_row(RowID="r4", Timestamp="2026-09-10 10:01:00"),
                history_row(RowID="r5", Vessel="VESSEL B", Voyage="V002", BlockID="opaque-block-b"),
                history_row(RowID="r6", BlockID=""),
                history_row(RowID="r7", BlockID=""),
            ]
        )
        result = deduplicate_voyage_events(extra)
        self.assertEqual(len(result), 6)
        self.assertEqual(result["_source_event_count"].max(), 2)

    def test_eta_net_cumulative_largest_and_timestamps(self) -> None:
        result = schedule_reliability_by_voyage(self.weekly, self.history)
        row = result.iloc[0]
        self.assertEqual(row["ETA Revision Count"], 2)
        self.assertEqual(row["Net ETA Movement"], 3)
        self.assertEqual(row["Cumulative ETA Movement"], 3)
        self.assertEqual(row["Largest Single ETA Revision"], 2)
        self.assertEqual(row["Week Change Count"], 2)
        self.assertEqual(len(material_schedule_events(self.history, "ETA")), 3)

    def test_week_rollover_and_malformed_week(self) -> None:
        malformed = cleaned_history([history_row(Field="Week", OldValue="bad", NewValue=39)])
        result = week_rollover_by_voyage(self.weekly, pd.concat([self.history, malformed], ignore_index=True))
        row = result.iloc[0]
        self.assertEqual(row["Original Week"], 37)
        self.assertEqual(row["Current Week"], 39)
        self.assertEqual(row["Week Change Count"], 2)
        self.assertEqual(row["Net Week Movement"], 2)
        self.assertEqual(row["Unavailable Week Events"], 1)
        summary = aggregate_week_rollover(result, "SVC")
        self.assertEqual(summary.iloc[0]["% Moved Multiple Weeks"], 1)

    def test_schedule_aggregation_and_history_periods(self) -> None:
        reliability = schedule_reliability_by_voyage(self.weekly, self.history)
        summary = aggregate_schedule_reliability(reliability, "SVC")
        history_period = history_period_aggregation(self.history, "History Quarter", voyage_events=True)
        filtered = apply_history_filters(self.history, periods=HistoryPeriodContext(year=2026, quarter="2026 Q3"))
        self.assertEqual(summary.iloc[0]["% Voyages Delayed"], 1)
        self.assertEqual(history_period.iloc[0]["History Events"], 5)
        self.assertEqual(len(filtered), len(self.history))

    def test_booking_churn_and_cancellation_event_are_distinct(self) -> None:
        cancellation = cleaned_history([history_row(Field="Row Status", OldValue="Active", NewValue="Cancelled")])
        combined = pd.concat([self.history, cancellation], ignore_index=True)
        churn = booking_churn(combined, level="Voyage")
        self.assertGreaterEqual(churn.iloc[0]["ETA Revisions"], 2)
        self.assertEqual(churn.iloc[0]["Cancellation Events"], 1)
        self.assertEqual(len(cancellation_events(combined)), 1)


class PhaseCEntityQualityAndReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weekly = cleaned_weekly(
            [
                weekly_row(),
                weekly_row(RowID="r2", **{"Booking number": "BK-2", "CUSTOMER": " alice ", "LoadStatus": "Empty", "CNTR AMT": 1, "SIZE": 4}),
                weekly_row(RowID="r3", BlockID="block-b", Vessel="VESSEL B", Voyage="V002", SVC="S2", **{"Booking number": "BK-3", "CUSTOMER": "Bob", "POD": "HAMBURG", "POD CODE": "DEHAM"}),
                weekly_row(RowID="r4", **{"Booking number": "BK-4", "RowStatus": "Cancelled", "CancelReason": "Customer request"}),
            ]
        )
        self.history = cleaned_history(
            [
                history_row(),
                history_row(Field="Week", OldValue=38, NewValue=39),
                history_row(Field="RowStatus", OldValue="Active", NewValue="Cancelled"),
            ]
        )

    def test_customer_service_route_and_cancellation_analytics(self) -> None:
        customers = customer_analytics(self.weekly)
        services = service_analytics(self.weekly, self.history)
        routes = route_destination_analytics(self.weekly)
        cancellations = cancellation_summary_by(self.weekly, "SVC")
        reasons = cancellation_reasons(self.weekly)
        self.assertEqual(len(customers), 2)
        self.assertEqual(customers.iloc[0]["CUSTOMER"], "Alice")
        self.assertEqual(len(services), 2)
        self.assertIn("Major PODs", services.columns)
        self.assertEqual(len(routes), 2)
        self.assertEqual(int(cancellations["Cancelled rows"].sum()), 1)
        self.assertEqual(reasons.iloc[0]["CancelReason"], "Customer request")

    def test_quality_engine_detects_required_structured_issues(self) -> None:
        raw = pd.DataFrame(
            [
                weekly_row(RowID="dup", Week="bad", Vessel="", Voyage="V001", LoadStatus="mystery", **{"Booking number": "SAME", "CNTR AMT": -1, "SIZE": 3, "TYPE": "", "POD CODE": ""}),
                weekly_row(RowID="dup", **{"Booking number": "SAME"}),
            ]
        )
        cleaned = clean_weekly(raw).dataframe
        history = cleaned_history([history_row(RowID="orphan")])
        issues = generate_quality_issues(cleaned, history, weekly_raw_df=raw)
        categories = set(issues["Category"])
        self.assertTrue({"Duplicate identity", "Negative quantity", "Invalid equipment", "Unexpected status", "Invalid week", "Orphan history"}.issubset(categories))
        self.assertTrue({"Critical", "Warning"}.issubset(set(issues["Severity"])))
        self.assertEqual(list(issues.columns)[0:3], ["Severity", "Category", "Message"])

    def test_anomaly_detection_and_insufficient_sample(self) -> None:
        profiles = pd.DataFrame(
            {
                "IdentityKey": [f"v{i}" for i in range(10)],
                "SVC": ["S1"] * 10,
                "Empty TEU Ratio": [0.1] * 9 + [0.9],
                "ETA Revision Count": [1] * 9 + [9],
            }
        )
        anomalies = detect_explainable_anomalies(profiles, baseline_group="SVC", minimum_sample=8)
        self.assertFalse(anomalies.empty)
        self.assertTrue(anomalies["Reason"].str.contains("percentile").all())
        self.assertIsNone(distribution_summary(pd.Series([1, 2, 3]), minimum_sample=5))
        self.assertTrue(detect_explainable_anomalies(profiles.head(3), minimum_sample=5).empty)

    def test_cargo_evolution_incomplete_and_forecast_readiness(self) -> None:
        weekly = cleaned_weekly([weekly_row(ETD="2026-09-30", **{"CNTR AMT": 10})])
        history = cleaned_history(
            [
                history_row(Field="CNTR AMT", Timestamp="2026-09-20", OldValue=5, NewValue=10),
                history_row(Field="CNTR AMT", Timestamp="2026-09-10", OldValue="", NewValue=5),
            ]
        )
        curve = cargo_evolution_foundation(weekly, history)
        day_14 = curve[curve["Days Before ETD"].eq(14)].iloc[0]
        self.assertEqual(day_14["Containers"], 5)
        self.assertTrue(pd.isna(day_14["TEU"]))

        incomplete = cargo_evolution_foundation(weekly, cleaned_history([]))
        self.assertFalse(bool(incomplete.iloc[0]["Complete"]))
        readiness = forecast_readiness(weekly, curve)
        self.assertEqual(readiness.iloc[0]["Readiness Status"], "Insufficient history")

    def test_comparison_engine_two_to_five_and_identity_safety(self) -> None:
        candidates = comparison_candidates(self.weekly, self.history)
        keys = candidates["IdentityKey"].tolist()
        compared = compare_voyage_instances(self.weekly, self.history, keys)
        self.assertEqual(len(compared), 2)
        self.assertEqual(compared["IdentityKey"].tolist(), keys)
        with self.assertRaises(ValueError):
            compare_voyage_instances(self.weekly, self.history, keys[:1])

    def test_empty_datasets_are_safe(self) -> None:
        empty = cleaned_weekly([])
        empty_history = cleaned_history([])
        self.assertTrue(voyage_load_profiles(empty).empty)
        self.assertTrue(schedule_reliability_by_voyage(empty, empty_history).empty)
        self.assertTrue(customer_analytics(empty).empty)
        self.assertTrue(generate_quality_issues(empty, empty_history).empty)


if __name__ == "__main__":
    unittest.main()
