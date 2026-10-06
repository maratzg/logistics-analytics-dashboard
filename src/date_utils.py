from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd


BLANK_TEXT_VALUES = {"", "-", "—", "none", "null", "nan", "nat"}


@dataclass(frozen=True, slots=True)
class DateParseResult:
    raw_value: Any
    parsed: pd.Timestamp | None
    warning: str | None = None


def is_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).replace("\xa0", " ").strip().casefold() not in BLANK_TEXT_VALUES


def normalize_text(value: Any) -> str:
    if not is_meaningful_value(value):
        return ""
    return " ".join(str(value).replace("\xa0", " ").split()).strip().casefold()


def parse_schedule_date(value: Any, *, field_name: str = "date") -> DateParseResult:
    """Parse schedule date values without changing the caller's raw value.

    The workbook/history can supply Excel datetimes, Python datetimes, Excel serial
    numbers, or common European/ISO date strings. Blank values are valid analytical
    states and do not produce warnings.
    """

    if not is_meaningful_value(value):
        return DateParseResult(value, None)

    if isinstance(value, pd.Timestamp):
        return DateParseResult(value, value)

    if isinstance(value, datetime):
        return DateParseResult(value, pd.Timestamp(value))

    if isinstance(value, date):
        return DateParseResult(value, pd.Timestamp(value))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return DateParseResult(value, None, _date_warning(field_name, value))
        # Excel's 1900-date-system serial dates. Keep the range deliberately sane.
        if 1 <= float(value) <= 100000:
            return DateParseResult(value, pd.to_datetime(value, unit="D", origin="1899-12-30"))
        return DateParseResult(value, None, _date_warning(field_name, value))

    text = " ".join(str(value).replace("\xa0", " ").strip().split())
    if not text:
        return DateParseResult(value, None)

    for fmt in _DATE_FORMATS:
        try:
            return DateParseResult(value, pd.Timestamp(datetime.strptime(text, fmt)))
        except ValueError:
            continue

    if _looks_like_dated_text(text):
        parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
        if not pd.isna(parsed):
            return DateParseResult(value, pd.Timestamp(parsed))

    return DateParseResult(value, None, _date_warning(field_name, value))


def days_between(start: pd.Timestamp | None, end: pd.Timestamp | None) -> float | None:
    if start is None or end is None:
        return None
    if pd.isna(start) or pd.isna(end):
        return None
    delta = pd.Timestamp(end) - pd.Timestamp(start)
    days = delta.total_seconds() / 86400
    if math.isclose(days, round(days), abs_tol=0.000001):
        return float(round(days))
    return float(days)


def _looks_like_dated_text(text: str) -> bool:
    has_year = bool(re.search(r"\b\d{4}\b", text))
    has_date_separator = any(separator in text for separator in [".", "/", "-", " "])
    return has_year and has_date_separator


def _date_warning(field_name: str, value: Any) -> str:
    return f"Unparseable date value for {field_name}: {value!r}"


_DATE_FORMATS = (
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%y",
    "%d.%m.%y %H:%M",
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
    "%d/%m/%y",
    "%d/%m/%y %H:%M",
    "%d-%m-%Y",
    "%d-%m-%Y %H:%M",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
)
