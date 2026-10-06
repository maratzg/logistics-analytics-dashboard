from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any


@dataclass(frozen=True, slots=True)
class TableInfo:
    name: str
    ref: str
    headers: list[str]


@dataclass(frozen=True, slots=True)
class SheetInfo:
    name: str
    state: str
    max_row: int
    max_column: int
    tables: list[TableInfo] = dataclass_field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WorkbookStructure:
    sheet_names: list[str]
    sheets: list[SheetInfo]


@dataclass(frozen=True, slots=True)
class MetricsWeekly:
    valid_operational_rows: int
    cancelled_rows: int
    unique_block_count: int
    total_summary: float
    total_teu: float
    total_ts: float
    active_rows: int = 0
    loaded_containers: float = 0.0
    empty_containers: float = 0.0
    unclassified_containers: float = 0.0
    total_containers: float = 0.0
    loaded_percent: float | None = None
    empty_percent: float | None = None
    loaded_20ft: float = 0.0
    empty_20ft: float = 0.0
    total_20ft: float = 0.0
    loaded_40ft: float = 0.0
    empty_40ft: float = 0.0
    total_40ft: float = 0.0
    loaded_teu: float = 0.0
    empty_teu: float = 0.0
    unclassified_teu: float = 0.0
    loaded_gwt: float = 0.0
    empty_gwt: float = 0.0
    unclassified_gwt: float = 0.0
    total_gwt: float = 0.0


@dataclass(frozen=True, slots=True)
class MetricsHistory:
    history_records: int
    eta_changes: int
    etd_changes: int
    cut_off_changes: int
    vessel_changes: int
    voyage_changes: int
    eta_ts_changes: int
    field_changes: dict[str, int] = dataclass_field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FieldReconstruction:
    field_name: str
    identity: dict[str, Any]
    original_raw: Any | None
    current_raw: Any | None
    latest_history_raw: Any | None
    current_source: str
    history_event_count: int
    material_revision_count: int
    original_parsed: Any | None = None
    current_parsed: Any | None = None
    warnings: list[str] = dataclass_field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ScheduleMovement:
    field_name: str
    identity: dict[str, Any]
    original_raw: Any | None
    current_raw: Any | None
    current_source: str
    history_event_count: int
    material_revision_count: int
    net_movement_days: float | None
    cumulative_movement_days: float | None
    original_date: Any | None = None
    current_date: Any | None = None
    warnings: list[str] = dataclass_field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VoyageSummary:
    vessel: str | None
    voyage: str | None
    block_ids: list[str]
    current_operational_row_count: int
    cancelled_row_count: int
    total_summary: float
    total_teu: float
    total_ts: float
    original_eta: Any | None
    current_eta: Any | None
    net_eta_movement_days: float | None
    cumulative_eta_movement_days: float | None
    eta_revision_count: int
    etd_revision_count: int
    cut_off_revision_count: int
    eta_ts_revision_count: int
    total_history_events: int
    affected_row_ids: list[str]
    timeline: Any
    is_ambiguous: bool = False
    ambiguity_reason: str | None = None
    candidate_groups: list[dict[str, Any]] = dataclass_field(default_factory=list)
    warnings: list[str] = dataclass_field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VesselSummary:
    vessel: str | None
    voyages: list[str]
    operational_rows: int
    cancelled_rows: int
    total_summary: float
    total_teu: float
    total_ts: float
    history_event_count: int
    eta_revision_count: int
    etd_revision_count: int
    cut_off_revision_count: int
    voyage_revision_count: int
    affected_row_ids: list[str]
    affected_block_ids: list[str]
    warnings: list[str] = dataclass_field(default_factory=list)
