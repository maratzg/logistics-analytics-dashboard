from __future__ import annotations

from typing import Any

import pandas as pd

from src.date_utils import is_meaningful_value, parse_schedule_date


MISSING_TEXT = "—"
UNAVAILABLE_TEXT = "Unavailable"
SCHEDULE_FIELDS = {"ETA", "ETD", "Cut-Off", "ETA T/S"}


def format_voyage_identity(
    *,
    vessel: Any,
    voyage: Any,
    week: Any = None,
    eta: Any = None,
    pol: Any = None,
    pod: Any = None,
    block_id: Any = None,
    disambiguate: bool = False,
) -> str:
    """Create a human label while keeping the opaque ID secondary."""

    vessel_text = _display(vessel, "Unknown vessel")
    voyage_text = _display(voyage, "Unknown voyage")
    parts = [f"{vessel_text} · {voyage_text}"]
    context: list[str] = []
    if _meaningful(week):
        numeric = pd.to_numeric(pd.Series([week]), errors="coerce").iloc[0]
        context.append(f"Week {int(numeric) if not pd.isna(numeric) and float(numeric).is_integer() else str(week).strip()}")
    parsed_eta = pd.to_datetime(eta, errors="coerce")
    if not pd.isna(parsed_eta):
        context.append(f"ETA {parsed_eta.strftime('%d.%m.%Y')}")
    route = " → ".join(value for value in [_display(pol, ""), _display(pod, "")] if value)
    if route:
        context.append(route)
    if context:
        parts.append(" · ".join(context))
    if disambiguate and _meaningful(block_id):
        parts.append(f"ID {str(block_id).strip()}")
    return " — ".join(parts)


def _display(value: Any, fallback: str) -> str:
    return str(value).strip() if _meaningful(value) else fallback


def _meaningful(value: Any) -> bool:
    return is_meaningful_value(value)


def format_date(value: Any, *, unavailable: bool = False) -> str:
    if unavailable:
        return UNAVAILABLE_TEXT
    parsed = parse_schedule_date(value).parsed
    return parsed.strftime("%d.%m.%Y") if parsed is not None else MISSING_TEXT


def format_timestamp(value: Any) -> str:
    if not _meaningful(value):
        return MISSING_TEXT
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%d.%m.%Y %H:%M") if not pd.isna(parsed) else MISSING_TEXT


def format_number(value: Any, *, decimals: int | None = None) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return MISSING_TEXT
    number = float(numeric)
    precision = 0 if decimals is None and number.is_integer() else (2 if decimals is None else decimals)
    return f"{number:,.{precision}f}"


def format_percentage(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return MISSING_TEXT if pd.isna(numeric) else f"{float(numeric) * 100:.1f}%"


def format_movement(value: Any, *, unavailable: bool = False) -> str:
    if unavailable:
        return UNAVAILABLE_TEXT
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return UNAVAILABLE_TEXT
    days = float(numeric)
    amount = f"{abs(days):.0f}" if days.is_integer() else f"{abs(days):.1f}"
    if days > 0:
        return f"+{amount} days later"
    if days < 0:
        return f"-{amount} days earlier"
    return "0 days"


def format_history_value(field: Any, value: Any, *, unavailable: bool = False) -> str:
    if unavailable:
        return UNAVAILABLE_TEXT
    if not _meaningful(value):
        return MISSING_TEXT
    field_name = str(field).strip()
    if field_name in SCHEDULE_FIELDS:
        parsed = parse_schedule_date(value, field_name=field_name).parsed
        return parsed.strftime("%d.%m.%Y") if parsed is not None else str(value).strip()
    if field_name in {"Week", "CNTR AMT", "SIZE", "GWT"}:
        return format_number(value)
    return str(value).strip()


def history_change_message(field: Any, old_value: Any, new_value: Any, *, old_unavailable: bool = False) -> str:
    field_name = str(field).strip() if _meaningful(field) else "Value"
    label = {"CNTR AMT": "Booking quantity", "RowStatus": "Row status", "LoadStatus": "Load status"}.get(field_name, field_name)
    old_display = format_history_value(field_name, old_value, unavailable=old_unavailable)
    new_display = format_history_value(field_name, new_value)
    if old_unavailable:
        return f"{label} changed to {new_display} (previous value unavailable)"
    if old_display == MISSING_TEXT and new_display != MISSING_TEXT:
        return f"{label} set to {new_display}"
    if new_display == MISSING_TEXT and old_display != MISSING_TEXT:
        return f"{label} cleared (previously {old_display})"
    return f"{label} changed from {old_display} to {new_display}"
