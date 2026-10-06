from __future__ import annotations

from typing import Any

import pandas as pd


ANOMALY_COLUMNS = [
    "Entity",
    "Baseline Group",
    "Metric",
    "Actual Value",
    "Comparison Baseline",
    "Reason",
    "Severity",
    "Sample Size",
]

HIGH_SIGNALS = [
    "Empty TEU Ratio",
    "ETA Revision Count",
    "Cumulative ETA Movement",
    "Week Change Count",
    "Cancellation Rate",
]
TWO_SIDED_SIGNALS = ["Loaded GWT / Loaded TEU", "Total GWT / Total TEU", "Total 40ft Share"]


def distribution_summary(values: pd.Series, *, minimum_sample: int = 5) -> dict[str, float | int] | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if len(numeric) < minimum_sample:
        return None
    q10 = float(numeric.quantile(0.10))
    q25 = float(numeric.quantile(0.25))
    median = float(numeric.median())
    q75 = float(numeric.quantile(0.75))
    q90 = float(numeric.quantile(0.90))
    return {
        "Sample Size": int(len(numeric)),
        "P10": q10,
        "P25": q25,
        "Median": median,
        "P75": q75,
        "P90": q90,
        "IQR": q75 - q25,
    }


def detect_explainable_anomalies(
    analytical_df: pd.DataFrame,
    *,
    entity_column: str = "IdentityKey",
    baseline_group: str | None = None,
    minimum_sample: int = 8,
) -> pd.DataFrame:
    """Flag transparent distribution outliers; never produce a composite score."""

    if analytical_df.empty or entity_column not in analytical_df.columns:
        return pd.DataFrame(columns=ANOMALY_COLUMNS)
    if baseline_group and baseline_group in analytical_df.columns:
        groups = list(analytical_df.groupby(baseline_group, dropna=False, sort=True))
    else:
        groups = [("Overall", analytical_df)]

    output: list[dict[str, Any]] = []
    for group_value, group in groups:
        label = str(group_value) if pd.notna(group_value) else "Unspecified"
        for metric in HIGH_SIGNALS:
            _detect_metric(output, group, entity_column, label, metric, minimum_sample, two_sided=False)
        for metric in TWO_SIDED_SIGNALS:
            _detect_metric(output, group, entity_column, label, metric, minimum_sample, two_sided=True)
    return pd.DataFrame(output, columns=ANOMALY_COLUMNS)


def _detect_metric(
    output: list[dict[str, Any]],
    group: pd.DataFrame,
    entity_column: str,
    group_label: str,
    metric: str,
    minimum_sample: int,
    *,
    two_sided: bool,
) -> None:
    if metric not in group.columns:
        return
    summary = distribution_summary(group[metric], minimum_sample=minimum_sample)
    if summary is None:
        return
    numeric = pd.to_numeric(group[metric], errors="coerce")
    q10 = float(summary["P10"])
    q90 = float(summary["P90"])
    q25 = float(summary["P25"])
    q75 = float(summary["P75"])
    iqr = float(summary["IQR"])
    lower_fence = q25 - 1.5 * iqr
    upper_fence = q75 + 1.5 * iqr

    for index, actual in numeric.items():
        if pd.isna(actual):
            continue
        direction = None
        threshold = None
        if float(actual) > q90:
            direction = "above"
            threshold = q90
        elif two_sided and float(actual) < q10:
            direction = "below"
            threshold = q10
        if direction is None or threshold is None:
            continue
        severe = float(actual) > upper_fence or (two_sided and float(actual) < lower_fence)
        percentile_name = "90th" if direction == "above" else "10th"
        output.append(
            {
                "Entity": group.at[index, entity_column],
                "Baseline Group": group_label,
                "Metric": metric,
                "Actual Value": float(actual),
                "Comparison Baseline": f"median={float(summary['Median']):g}; {percentile_name} percentile={threshold:g}; IQR={iqr:g}",
                "Reason": f"{metric} {float(actual):g} is {direction} the observed {percentile_name} percentile ({threshold:g}) for {group_label}.",
                "Severity": "High" if severe else "Watch",
                "Sample Size": int(summary["Sample Size"]),
            }
        )
