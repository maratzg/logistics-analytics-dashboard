from __future__ import annotations


WEEKLY_INPUT_COLUMNS = [
    "Week",
    "Vessel",
    "Voyage",
    "ETA",
    "ETD",
    "Cut-Off",
    "ETA T/S",
    "Comments 1",
    "Booking number",
    "O/V",
    "SVC",
    "Booking status",
    "CNTR AMT",
    "SIZE",
    "TYPE",
    "GWT",
    "POL",
    "EU TS",
    "POD CODE",
    "POD",
    "CUSTOMER",
    "Comments 2",
    "RowStatus",
    "CancelReason",
]

LEGACY_CALCULATED_COLUMNS = ["Summary", "TEU", "TS"]
IDENTIFIER_COLUMNS = ["BlockID", "RowID"]
LOAD_STATUS_COLUMN = "LoadStatus"
V2_CALCULATED_COLUMNS = [
    "Loaded Containers",
    "Empty Containers",
    "Total Containers",
    "Loaded 20ft",
    "Empty 20ft",
    "Total 20ft",
    "Loaded 40ft",
    "Empty 40ft",
    "Total 40ft",
    "Loaded TEU",
    "Empty TEU",
    "Total TEU",
    "Loaded GWT",
    "Empty GWT",
    "Total GWT",
]

ANALYTICAL_ONLY_COLUMNS = [
    "Unclassified Containers",
    "Unclassified TEU",
    "Unclassified GWT",
]

OPERATIONAL_PAYLOAD_COLUMNS = [
    "Vessel",
    "Voyage",
    "ETA",
    "ETD",
    "Cut-Off",
    "ETA T/S",
    "Comments 1",
    "Booking number",
    "O/V",
    "SVC",
    "Booking status",
    "CNTR AMT",
    "SIZE",
    "TYPE",
    "GWT",
    "POL",
    "EU TS",
    "POD CODE",
    "POD",
    "CUSTOMER",
    "Comments 2",
]

CALCULATED_COLUMNS = LEGACY_CALCULATED_COLUMNS + V2_CALCULATED_COLUMNS
EXPECTED_WEEKLY_COLUMNS = (
    WEEKLY_INPUT_COLUMNS
    + LEGACY_CALCULATED_COLUMNS
    + IDENTIFIER_COLUMNS
    + [LOAD_STATUS_COLUMN]
    + V2_CALCULATED_COLUMNS
)
EXPECTED_MASTER_COLUMNS = list(EXPECTED_WEEKLY_COLUMNS)

REQUIRED_OPERATIONAL_COLUMNS = [
    "Week",
    "RowID",
    "BlockID",
    "RowStatus",
    "CNTR AMT",
    "SIZE",
    "GWT",
]

EXPECTED_HISTORY_COLUMNS = [
    "Timestamp",
    "User",
    "BlockID",
    "RowID",
    "Week",
    "Vessel",
    "Voyage",
    "Booking number",
    "Comments 1",
    "Comments 2",
    "CancelReason",
    "Field",
    "OldValue",
    "NewValue",
    "Year",
    "Month",
]

SCHEDULE_FIELDS = ("ETA", "ETD", "Cut-Off", "ETA T/S")
EXPANDED_HISTORY_FIELDS = (
    "Week",
    "Vessel",
    "Voyage",
    "ETA",
    "ETD",
    "Cut-Off",
    "ETA T/S",
    "Booking status",
    "LoadStatus",
    "CNTR AMT",
    "SIZE",
    "TYPE",
    "GWT",
    "RowStatus",
    "CancelReason",
)

HISTORY_VOYAGE_EVENT_KEY = [
    "BlockID",
    "Vessel",
    "Voyage",
    "Field",
    "Timestamp",
    "OldValue",
    "NewValue",
]

LEGACY_UNAVAILABLE_VALUES = {"[bulk edit]"}


assert len(EXPECTED_WEEKLY_COLUMNS) == 45
