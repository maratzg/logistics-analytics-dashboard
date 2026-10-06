from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .analytical_filters import FilterContext, apply_current_filters, apply_history_filters
from .advanced_analytics import (
    cancellations_by_vessel,
    cancellations_by_voyage,
    cancellations_by_week,
    history_events_by_month,
    largest_cumulative_eta_movement_voyages,
    largest_eta_movement_voyages,
    material_revisions_by_vessel,
    most_unstable_voyages_by_eta_revisions,
    prepare_chart_series,
    teu_by_vessel,
    voyage_comparison_table,
    voyage_instance_options,
    voyage_performance_table,
    vessel_schedule_performance,
)
from .analytics import (
    calculate_history_metrics,
    calculate_revision_counts,
    calculate_weekly_metrics,
    get_vessel_summary,
    get_voyage_summary,
    rank_vessels_by_eta_revisions,
    rank_vessels_by_history_events,
    rank_voyages_by_eta_revisions,
    rank_voyages_by_history_events,
)
from .config import AppConfig, load_config, save_workbook_path
from .data_cleaner import clean_history, clean_weekly
from .excel_reader import ExcelWorkbookReader
from .filters import filter_history
from .history_processing import deduplicate_voyage_events, history_with_current_context, resolve_history_identities
from .gui.operational_models import (
    HistoryMode,
    OperationalDashboardModel,
    OperationalHistoryModel,
    VoyageBrowserModel,
    VoyageDetailModel,
    build_dashboard_model,
    build_history_model,
    build_voyage_browser_model,
    build_voyage_detail_model,
)
from .gui.secondary_models import (
    ComparisonPageModel,
    DataQualityPageModel,
    EntityAnalyticsPageModel,
    build_comparison_page_model,
    build_data_quality_page_model,
    build_entity_analytics_model,
)
from .operational_analytics import voyage_load_profiles
from .quality_analytics import generate_quality_issues
from .schedule_analytics import schedule_reliability_by_voyage, week_rollover_by_voyage
from .logging_setup import current_log_dir
from .platform_paths import user_config_dir
from .version import APP_NAME, APP_PURPOSE, APP_VERSION
from .workbook_health import WorkbookHealth, WorkbookHealthStatus, health_from_structure, health_message, validate_workbook
from .models import MetricsHistory, MetricsWeekly, WorkbookStructure
from .validators import ValidationIssue, cross_check_master_data, validate_history, validate_weekly


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
ALL_OPTION = "All"


@dataclass(frozen=True, slots=True)
class LoadedWorkbookData:
    workbook_path: Path
    structure: WorkbookStructure | None
    weekly_df: pd.DataFrame
    history_df: pd.DataFrame
    weekly_metrics: MetricsWeekly
    history_metrics: MetricsHistory
    issues: list[ValidationIssue]
    loaded_at: datetime
    weekly_raw_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    history_raw_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    voyage_history_df: pd.DataFrame | None = None
    master_data_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    master_data_raw_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    schema_issues: list[ValidationIssue] = field(default_factory=list)
    voyage_profiles_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    schedule_reliability_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    week_rollover_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    quality_issues_df: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass(frozen=True, slots=True)
class RefreshResult:
    success: bool
    message: str
    data: LoadedWorkbookData | None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class WorkbookSelectionResult:
    success: bool
    message: str
    health: WorkbookHealth
    refresh_result: RefreshResult | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class DashboardModel:
    workbook_filename: str
    load_status: str
    last_loaded: datetime | None
    has_weekly_data: bool
    has_history_data: bool
    weekly_metrics: MetricsWeekly
    history_metrics: MetricsHistory
    material_revision_counts: dict[str, int]
    top_vessels_by_events: pd.DataFrame
    top_vessels_by_eta_revisions: pd.DataFrame
    top_voyages_by_events: pd.DataFrame
    top_voyages_by_eta_revisions: pd.DataFrame
    teu_by_vessel: pd.DataFrame
    eta_revisions_by_vessel: pd.DataFrame
    history_events_over_time: pd.DataFrame
    cancellations_over_time: pd.DataFrame
    biggest_eta_movements: pd.DataFrame
    largest_cumulative_eta_movements: pd.DataFrame
    most_revised_voyages: pd.DataFrame
    highest_cancellations_by_vessel: pd.DataFrame
    highest_cancellations_by_voyage: pd.DataFrame
    empty_message: str | None = None
    issues: list[ValidationIssue] = field(default_factory=list)
    setup_required: bool = False
    setup_title: str | None = None
    setup_message: str | None = None


@dataclass(frozen=True, slots=True)
class SettingsModel:
    app_name: str
    app_version: str
    app_purpose: str
    configured_workbook_filename: str
    configured_workbook_path: str
    workbook_exists: bool
    load_status: str
    health_status: WorkbookHealthStatus
    health_errors: list[str]
    health_warnings: list[str]
    detected_sheets: list[str]
    last_successful_load: datetime | None
    user_config_path: Path | None
    user_config_dir: Path
    log_dir: Path
    expected_workbook_filename: str
    config_errors: list[str] = field(default_factory=list)
    config_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class HistoryExplorerModel:
    rows: pd.DataFrame
    matching_count: int
    empty_message: str | None = None


@dataclass(frozen=True, slots=True)
class SelectorOptions:
    history_filters: dict[str, list[str]]
    voyages: list[str]
    vessels: list[str]
    block_ids: list[str]


@dataclass(frozen=True, slots=True)
class VesselAnalyticsModel:
    vessel: str | None
    empty_message: str | None
    summary: Any | None
    material_revision_counts: dict[str, int]
    schedule_metrics: dict[str, Any]
    voyage_table: pd.DataFrame
    eta_movement_by_voyage: pd.DataFrame
    eta_revisions_by_voyage: pd.DataFrame
    teu_by_voyage: pd.DataFrame


@dataclass(frozen=True, slots=True)
class ComparisonOptions:
    labels: list[str]
    options: pd.DataFrame


@dataclass(frozen=True, slots=True)
class ComparisonModel:
    selected_count: int
    empty_message: str | None
    table: pd.DataFrame
    eta_movement_chart: pd.DataFrame
    eta_revisions_chart: pd.DataFrame
    volume_chart: pd.DataFrame


WorkbookLoader = Callable[[], LoadedWorkbookData]


class ApplicationState:
    """Own loaded workbook data and expose GUI-ready analytical state."""

    def __init__(
        self,
        config: AppConfig,
        *,
        loader: WorkbookLoader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self._loader = loader
        self._clock = clock or datetime.now
        self.data: LoadedWorkbookData | None = None
        self.analytical_filter_context = FilterContext()
        self._view_model_cache: dict[tuple[Any, ...], Any] = {}
        self.last_error: Exception | None = None
        self.health = validate_workbook(
            None,
            required_sheets=config.required_sheets,
            optional_sheets=config.optional_sheets,
        )
        self.load_status = "Not loaded"

    @property
    def workbook_filename(self) -> str:
        if self.config.workbook_path is None:
            return "Not configured"
        return self.config.workbook_path.name

    @property
    def last_loaded(self) -> datetime | None:
        return self.data.loaded_at if self.data else None

    def set_analytical_filter_context(self, context: FilterContext | None) -> None:
        selected = context or FilterContext()
        if selected != self.analytical_filter_context:
            self._view_model_cache.clear()
        self.analytical_filter_context = selected

    def clear_analytical_filter_context(self) -> None:
        self.analytical_filter_context = FilterContext()
        self._view_model_cache.clear()

    def filtered_weekly(self) -> pd.DataFrame:
        if self.data is None:
            return pd.DataFrame()
        return apply_current_filters(self.data.weekly_df, self.analytical_filter_context)

    def filtered_history(self) -> pd.DataFrame:
        if self.data is None:
            return pd.DataFrame()
        return apply_history_filters(
            self.data.history_df,
            self.analytical_filter_context,
            current_df=self.data.weekly_df,
        )

    def refresh(self) -> RefreshResult:
        if self._loader is None:
            path = self.config.workbook_path
            if path is None or not path.exists() or path.suffix.lower() not in {".xlsm", ".xlsx"}:
                health = validate_workbook(
                    path,
                    required_sheets=self.config.required_sheets,
                    optional_sheets=self.config.optional_sheets,
                )
                self.health = health
                self.last_error = None
                preserving = self.data is not None
                self.load_status = _status_text(health.status, preserving_existing_data=preserving)
                return RefreshResult(False, health_message(health, preserving_existing_data=preserving), self.data)

        try:
            loaded = self._load_current_config()
            if self._loader is not None:
                self.health = WorkbookHealth(
                    status=WorkbookHealthStatus.READY,
                    path=loaded.workbook_path,
                    filename=loaded.workbook_path.name,
                    exists=True,
                    structure=loaded.structure,
                )
            else:
                self.health = health_from_structure(
                    loaded.workbook_path,
                    loaded.structure or WorkbookStructure([], []),
                    required_sheets=self.config.required_sheets,
                    optional_sheets=self.config.optional_sheets,
                    compatibility_issues=loaded.schema_issues,
                )
                if not self.health.can_load:
                    preserving = self.data is not None
                    self.load_status = _status_text(self.health.status, preserving_existing_data=preserving)
                    return RefreshResult(False, health_message(self.health, preserving_existing_data=preserving), self.data)
            self.data = loaded
            self._view_model_cache.clear()
            self.last_error = None
            self.load_status = "Loaded with warnings" if self.health.status == WorkbookHealthStatus.READY_WITH_WARNINGS else "Loaded successfully"
            LOGGER.info("Workbook loaded successfully: %s", loaded.workbook_path.name)
            message = "Workbook loaded with warnings." if self.health.status == WorkbookHealthStatus.READY_WITH_WARNINGS else "Workbook loaded successfully."
            return RefreshResult(True, message, loaded)
        except Exception as exc:
            LOGGER.exception("Workbook refresh failed")
            self.last_error = exc
            if self.data is not None:
                self.load_status = "Refresh failed; showing previously loaded data"
                return RefreshResult(False, "Workbook could not be refreshed. The previously loaded data is still being shown.", self.data, exc)
            self.load_status = "Load failed"
            return RefreshResult(False, "Workbook could not be loaded. Check OneDrive sync or update the workbook location in Settings.", None, exc)

    def validate_configured_workbook(self) -> WorkbookHealth:
        self.health = validate_workbook(
            self.config.workbook_path,
            required_sheets=self.config.required_sheets,
            optional_sheets=self.config.optional_sheets,
        )
        self.load_status = _status_text(self.health.status, preserving_existing_data=self.data is not None)
        LOGGER.info("Workbook validation status: %s", self.health.status.value)
        return self.health

    def change_workbook(self, workbook_path: str | Path) -> WorkbookSelectionResult:
        health = validate_workbook(
            workbook_path,
            required_sheets=self.config.required_sheets,
            optional_sheets=self.config.optional_sheets,
        )
        self.health = health
        if not health.can_load:
            self.load_status = _status_text(health.status, preserving_existing_data=self.data is not None)
            LOGGER.warning("Rejected workbook selection with status %s: %s", health.status.value, workbook_path)
            return WorkbookSelectionResult(
                success=False,
                message="Selected workbook was not saved because it could not be validated.",
                health=health,
            )

        try:
            self.config = save_workbook_path(health.path or workbook_path, existing_config=self.config)
            LOGGER.info("Saved workbook configuration: %s", self.config.workbook_path.name if self.config.workbook_path else "not configured")
        except Exception as exc:
            LOGGER.exception("Failed to save workbook configuration")
            return WorkbookSelectionResult(
                success=False,
                message="Workbook validated, but the configuration file could not be saved.",
                health=health,
                error=exc,
            )

        refresh_result = self.refresh()
        return WorkbookSelectionResult(
            success=refresh_result.success,
            message=refresh_result.message,
            health=self.health,
            refresh_result=refresh_result,
            error=refresh_result.error,
        )

    def settings_model(self) -> SettingsModel:
        path = self.config.workbook_path
        return SettingsModel(
            app_name=APP_NAME,
            app_version=APP_VERSION,
            app_purpose=APP_PURPOSE,
            configured_workbook_filename=path.name if path else "Not configured",
            configured_workbook_path=str(path) if path else "Not configured",
            workbook_exists=bool(path and path.exists()),
            load_status=self.load_status,
            health_status=self.health.status,
            health_errors=list(self.health.errors),
            health_warnings=list(self.health.warnings),
            detected_sheets=list(self.health.detected_sheets),
            last_successful_load=self.last_loaded,
            user_config_path=self.config.user_config_path,
            user_config_dir=self.config.user_config_path.parent if self.config.user_config_path else user_config_dir(),
            log_dir=current_log_dir(),
            expected_workbook_filename=self.config.expected_workbook_filename,
            config_errors=list(self.config.config_errors),
            config_warnings=list(self.config.config_warnings),
        )

    def _load_current_config(self) -> LoadedWorkbookData:
        if self._loader is not None:
            return self._loader()
        return load_workbook_data(self.config, loaded_at=self._clock())

    def dashboard_model(self) -> DashboardModel:
        if self.data is None:
            empty = _empty_dashboard_message(self.health, self.last_error)
            return DashboardModel(
                workbook_filename=self.workbook_filename,
                load_status=self.load_status,
                last_loaded=None,
                has_weekly_data=False,
                has_history_data=False,
                weekly_metrics=MetricsWeekly(0, 0, 0, 0.0, 0.0, 0.0),
                history_metrics=MetricsHistory(0, 0, 0, 0, 0, 0, 0),
                material_revision_counts=_empty_material_counts(),
                top_vessels_by_events=pd.DataFrame(),
                top_vessels_by_eta_revisions=pd.DataFrame(),
                top_voyages_by_events=pd.DataFrame(),
                top_voyages_by_eta_revisions=pd.DataFrame(),
                teu_by_vessel=pd.DataFrame(),
                eta_revisions_by_vessel=pd.DataFrame(),
                history_events_over_time=pd.DataFrame(),
                cancellations_over_time=pd.DataFrame(),
                biggest_eta_movements=pd.DataFrame(),
                largest_cumulative_eta_movements=pd.DataFrame(),
                most_revised_voyages=pd.DataFrame(),
                highest_cancellations_by_vessel=pd.DataFrame(),
                highest_cancellations_by_voyage=pd.DataFrame(),
                empty_message=empty,
                issues=[],
                setup_required=True,
                setup_title=_setup_title(self.health.status),
                setup_message=empty,
            )

        weekly = self.filtered_weekly()
        history = self.filtered_history()
        voyage_history = deduplicate_voyage_events(history)
        has_weekly = _has_operational_weekly_rows(weekly)
        has_history = _has_records(history)
        empty_message = None
        if not has_weekly and not has_history:
            empty_message = "Workbook loaded successfully. No active operational or history records are currently available."
        elif not has_weekly:
            empty_message = "No active WEEKLY operational records are currently available."

        return DashboardModel(
            workbook_filename=self.workbook_filename,
            load_status=self.load_status,
            last_loaded=self.last_loaded,
            has_weekly_data=has_weekly,
            has_history_data=has_history,
            weekly_metrics=calculate_weekly_metrics(weekly),
            history_metrics=calculate_history_metrics(history),
            material_revision_counts=_material_revision_counts(voyage_history),
            top_vessels_by_events=rank_vessels_by_history_events(history, limit=5),
            top_vessels_by_eta_revisions=rank_vessels_by_eta_revisions(voyage_history, limit=5),
            top_voyages_by_events=rank_voyages_by_history_events(voyage_history, limit=5),
            top_voyages_by_eta_revisions=rank_voyages_by_eta_revisions(voyage_history, limit=5),
            teu_by_vessel=prepare_chart_series(teu_by_vessel(weekly, limit=10), label_column="Vessel", value_column="TEU", limit=10),
            eta_revisions_by_vessel=prepare_chart_series(
                material_revisions_by_vessel(voyage_history, "ETA", limit=10),
                label_column="Vessel",
                value_column="ETA revisions",
                limit=10,
            ),
            history_events_over_time=history_events_by_month(history),
            cancellations_over_time=cancellations_by_week(weekly),
            biggest_eta_movements=largest_eta_movement_voyages(weekly, voyage_history, limit=5),
            largest_cumulative_eta_movements=largest_cumulative_eta_movement_voyages(weekly, voyage_history, limit=5),
            most_revised_voyages=most_unstable_voyages_by_eta_revisions(weekly, voyage_history, limit=5),
            highest_cancellations_by_vessel=cancellations_by_vessel(weekly, limit=5),
            highest_cancellations_by_voyage=cancellations_by_voyage(weekly, limit=5),
            empty_message=empty_message,
            issues=self.data.issues,
        )

    def operational_dashboard_model(self) -> OperationalDashboardModel:
        if self.data is None:
            return build_dashboard_model(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), self.analytical_filter_context)
        key = ("phase-e-dashboard", id(self.data), repr(self.analytical_filter_context))
        if key not in self._view_model_cache:
            self._view_model_cache[key] = build_dashboard_model(
                self.data.weekly_df,
                self.data.history_df,
                self.data.quality_issues_df,
                self.analytical_filter_context,
            )
        return self._view_model_cache[key]

    def voyage_browser_model(self) -> VoyageBrowserModel:
        if self.data is None:
            return VoyageBrowserModel(pd.DataFrame(), 0, "Workbook is not loaded.")
        key = ("phase-e-voyages", id(self.data), repr(self.analytical_filter_context))
        if key not in self._view_model_cache:
            self._view_model_cache[key] = build_voyage_browser_model(
                self.data.weekly_df,
                self.data.history_df,
                self.data.quality_issues_df,
                self.analytical_filter_context,
            )
        return self._view_model_cache[key]

    def voyage_detail_model(self, identity_key: str) -> VoyageDetailModel:
        if self.data is None:
            return VoyageDetailModel(identity_key, False, "Workbook is not loaded.")
        key = ("phase-e-voyage-detail", id(self.data), identity_key)
        if key not in self._view_model_cache:
            self._view_model_cache[key] = build_voyage_detail_model(
                self.data.weekly_df,
                self.data.history_df,
                self.data.quality_issues_df,
                identity_key,
            )
        return self._view_model_cache[key]

    def operational_history_model(
        self,
        *,
        mode: HistoryMode = "grouped",
        field_name: Any | None = None,
        user: Any | None = None,
        start_date: Any | None = None,
        end_date: Any | None = None,
        search: str | None = None,
    ) -> OperationalHistoryModel:
        if self.data is None:
            return OperationalHistoryModel(pd.DataFrame(), mode, 0, 0, [ALL_OPTION], [ALL_OPTION], "Workbook is not loaded.")
        key = (
            "phase-e-history",
            id(self.data),
            repr(self.analytical_filter_context),
            mode,
            str(field_name),
            str(user),
            str(start_date),
            str(end_date),
            str(search),
        )
        if key not in self._view_model_cache:
            self._view_model_cache[key] = build_history_model(
                self.data.weekly_df,
                self.data.history_df,
                self.analytical_filter_context,
                mode=mode,
                field_name=field_name,
                user=user,
                start_date=start_date,
                end_date=end_date,
                search=search,
            )
        return self._view_model_cache[key]

    def vessel_analytics_page_model(self, selected_key: str | None = None) -> EntityAnalyticsPageModel:
        return self._entity_analytics_page_model("vessel", selected_key)

    def service_analytics_page_model(self, selected_key: str | None = None) -> EntityAnalyticsPageModel:
        return self._entity_analytics_page_model("service", selected_key)

    def customer_analytics_page_model(self, selected_key: str | None = None) -> EntityAnalyticsPageModel:
        return self._entity_analytics_page_model("customer", selected_key)

    def _entity_analytics_page_model(self, kind: str, selected_key: str | None) -> EntityAnalyticsPageModel:
        if self.data is None:
            return build_entity_analytics_model(
                pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), kind, self.analytical_filter_context, selected_key=selected_key  # type: ignore[arg-type]
            )
        key = ("phase-f-entity", kind, id(self.data), repr(self.analytical_filter_context), selected_key)
        if key not in self._view_model_cache:
            self._view_model_cache[key] = build_entity_analytics_model(
                self.data.weekly_df,
                self.data.history_df,
                self.data.quality_issues_df,
                kind,  # type: ignore[arg-type]
                self.analytical_filter_context,
                selected_key=selected_key,
            )
        return self._view_model_cache[key]

    def comparison_page_model(self, selected_keys: Iterable[str] | None = None) -> ComparisonPageModel:
        selected = tuple(str(value) for value in (selected_keys or []))
        if self.data is None:
            return build_comparison_page_model(pd.DataFrame(), pd.DataFrame(), self.analytical_filter_context, selected_keys=selected)
        key = ("phase-f-comparison", id(self.data), repr(self.analytical_filter_context), selected)
        if key not in self._view_model_cache:
            self._view_model_cache[key] = build_comparison_page_model(
                self.data.weekly_df,
                self.data.history_df,
                self.analytical_filter_context,
                selected_keys=selected,
            )
        return self._view_model_cache[key]

    def data_quality_page_model(
        self,
        *,
        severity: Any | None = None,
        category: Any | None = None,
        search: str | None = None,
    ) -> DataQualityPageModel:
        if self.data is None:
            return build_data_quality_page_model(pd.DataFrame(), pd.DataFrame(), self.analytical_filter_context)
        key = (
            "phase-f-quality",
            id(self.data),
            repr(self.analytical_filter_context),
            str(severity),
            str(category),
            str(search),
        )
        if key not in self._view_model_cache:
            self._view_model_cache[key] = build_data_quality_page_model(
                self.data.weekly_df,
                self.data.quality_issues_df,
                self.analytical_filter_context,
                severity=severity,
                category=category,
                search=search,
            )
        return self._view_model_cache[key]

    def selector_options(self) -> SelectorOptions:
        if self.data is None:
            return SelectorOptions(_empty_history_filter_options(), [ALL_OPTION], [ALL_OPTION], [ALL_OPTION])

        weekly = self.filtered_weekly()
        history = self.filtered_history()
        history_filters = {
            "Vessel": _options_from_column(history, "Vessel"),
            "Voyage": _options_from_column(history, "Voyage"),
            "Week": _options_from_column(history, "Week"),
            "Month": _options_from_column(history, "History Month"),
            "Year": _options_from_column(history, "History Year"),
            "User": _options_from_column(history, "User"),
            "Field": _options_from_column(history, "Field"),
            "Booking number": _options_from_column(history, "Booking number"),
        }

        return SelectorOptions(
            history_filters=history_filters,
            voyages=_options_from_frames([weekly, history], "Voyage"),
            vessels=_options_from_frames([weekly, history], "Vessel"),
            block_ids=_options_from_frames([weekly, history], "BlockID"),
        )

    def history_model(self, filters: dict[str, Any] | None = None) -> HistoryExplorerModel:
        if self.data is None or self.data.history_df.empty:
            return HistoryExplorerModel(_history_display_frame(pd.DataFrame()), 0, "No history records are currently available.")

        filters = filters or {}
        history = self.filtered_history()
        filtered = filter_history(
            history,
            vessel=_filter_value(filters.get("Vessel")),
            voyage=_filter_value(filters.get("Voyage")),
            week=_filter_value(filters.get("Week")),
            month=_filter_value(filters.get("Month")),
            year=_filter_value(filters.get("Year")),
            user=_filter_value(filters.get("User")),
            field=_filter_value(filters.get("Field")),
            booking_number=_filter_value(filters.get("Booking number")),
        )
        display = _history_display_frame(filtered, newest_first=True)
        empty = "No history events match the selected filters." if display.empty else None
        return HistoryExplorerModel(display, int(len(display)), empty)

    def voyage_values_for(self, voyage: Any | None = None) -> dict[str, list[str]]:
        if self.data is None:
            return {"Vessel": [ALL_OPTION], "BlockID": [ALL_OPTION]}
        scoped_weekly = self.filtered_weekly()
        scoped_history = history_with_current_context(self.filtered_history())
        if _filter_value(voyage) is None:
            weekly = scoped_weekly
            history = scoped_history
        else:
            from .filters import filter_weekly

            weekly = filter_weekly(scoped_weekly, voyage=voyage)
            history = filter_history(scoped_history, voyage=voyage)
        return {
            "Vessel": _options_from_frames([weekly, history], "Vessel"),
            "BlockID": _options_from_frames([weekly, history], "BlockID"),
        }

    def voyage_summary(self, voyage: Any, *, vessel: Any | None = None, block_id: Any | None = None):
        if self.data is None or _filter_value(voyage) is None:
            return None
        weekly = self.filtered_weekly()
        voyage_history = deduplicate_voyage_events(self.filtered_history())
        return get_voyage_summary(
            weekly,
            voyage_history,
            voyage,
            vessel=_filter_value(vessel),
            block_id=_filter_value(block_id),
        )

    def vessel_analytics(self, vessel: Any | None) -> VesselAnalyticsModel:
        if self.data is None:
            return _empty_vessel_model(None, "Workbook is not loaded.")
        selected_vessel = _filter_value(vessel)
        if selected_vessel is None:
            if len(self.selector_options().vessels) <= 1:
                return _empty_vessel_model(None, "No vessels are currently available.")
            return _empty_vessel_model(None, "Select a vessel to view analytics.")

        weekly = self.filtered_weekly()
        voyage_history = deduplicate_voyage_events(self.filtered_history())
        summary = get_vessel_summary(weekly, voyage_history, selected_vessel)
        voyage_table = voyage_performance_table(weekly, voyage_history, vessel=selected_vessel)
        vessel_history = filter_history(history_with_current_context(voyage_history), vessel=selected_vessel)
        schedule = _schedule_metrics_for_vessel(weekly, voyage_history, selected_vessel, voyage_table)

        empty_message = None
        if voyage_table.empty and summary.history_event_count == 0:
            empty_message = "No operational or history analytics are available for this vessel."

        return VesselAnalyticsModel(
            vessel=str(selected_vessel),
            empty_message=empty_message,
            summary=summary,
            material_revision_counts=_material_revision_counts(vessel_history),
            schedule_metrics=schedule,
            voyage_table=voyage_table,
            eta_movement_by_voyage=prepare_chart_series(voyage_table, label_column="Label", value_column="Net ETA movement", limit=12, keep_zero=True),
            eta_revisions_by_voyage=prepare_chart_series(voyage_table, label_column="Label", value_column="ETA revisions", limit=12),
            teu_by_voyage=prepare_chart_series(voyage_table, label_column="Label", value_column="TEU", limit=12),
        )

    def comparison_options(self) -> ComparisonOptions:
        if self.data is None:
            return ComparisonOptions([ALL_OPTION], pd.DataFrame())
        options = voyage_instance_options(self.filtered_weekly(), deduplicate_voyage_events(self.filtered_history()))
        labels = [ALL_OPTION] + options["Label"].tolist() if not options.empty else [ALL_OPTION]
        return ComparisonOptions(labels, options)

    def comparison_model(self, selected_labels: Iterable[str]) -> ComparisonModel:
        if self.data is None:
            return _empty_comparison_model("Workbook is not loaded.")

        options = self.comparison_options().options
        if options.empty:
            return _empty_comparison_model("At least two voyage instances are required for comparison.")

        selected = [label for label in selected_labels if _filter_value(label) is not None]
        selected = list(dict.fromkeys(selected))
        if len(selected) < 2:
            return _empty_comparison_model("Select at least two voyage instances to compare.")

        keys = options[options["Label"].isin(selected)]["IdentityKey"].tolist()
        table = voyage_comparison_table(self.filtered_weekly(), deduplicate_voyage_events(self.filtered_history()), keys)
        if table.empty:
            return _empty_comparison_model("Selected voyage instances could not be compared.")

        return ComparisonModel(
            selected_count=int(len(table)),
            empty_message=None,
            table=table,
            eta_movement_chart=prepare_chart_series(table, label_column="Label", value_column="Net ETA movement", keep_zero=True),
            eta_revisions_chart=prepare_chart_series(table, label_column="Label", value_column="ETA revisions", keep_zero=True),
            volume_chart=prepare_chart_series(table, label_column="Label", value_column="TEU", keep_zero=True),
        )


def create_application_state(
    config_path: str | Path | None = None,
    *,
    user_config_path: str | Path | None = None,
) -> ApplicationState:
    return ApplicationState(load_config(config_path, user_config_path=user_config_path))


def load_workbook_data(config: AppConfig, *, loaded_at: datetime | None = None) -> LoadedWorkbookData:
    if config.workbook_path is None:
        raise ValueError("Workbook path is not configured.")
    reader = ExcelWorkbookReader(config.workbook_path)
    snapshot = reader.read_snapshot()

    weekly_clean = clean_weekly(snapshot.weekly_df)
    history_clean = clean_history(snapshot.history_df)
    master_clean = clean_weekly(snapshot.master_data_df)
    resolved_history = resolve_history_identities(history_clean.dataframe, weekly_clean.dataframe)
    voyage_history = deduplicate_voyage_events(resolved_history)
    voyage_profiles = voyage_load_profiles(weekly_clean.dataframe)
    week_rollover = week_rollover_by_voyage(weekly_clean.dataframe, voyage_history)
    schedule_reliability = schedule_reliability_by_voyage(
        weekly_clean.dataframe,
        voyage_history,
        rollover_df=week_rollover,
    )
    quality_issues = generate_quality_issues(
        weekly_clean.dataframe,
        resolved_history,
        weekly_raw_df=snapshot.weekly_df,
    )

    weekly_validation = validate_weekly(weekly_clean.dataframe)
    history_validation = validate_history(resolved_history)
    master_cross_check = cross_check_master_data(weekly_clean.dataframe, master_clean.dataframe)
    issues = (
        snapshot.read_issues
        + snapshot.schema_issues
        + weekly_clean.issues
        + history_clean.issues
        + weekly_validation
        + history_validation
        + master_cross_check
    )

    return LoadedWorkbookData(
        workbook_path=config.workbook_path,
        structure=snapshot.structure,
        weekly_df=weekly_clean.dataframe,
        history_df=resolved_history,
        weekly_metrics=calculate_weekly_metrics(weekly_clean.dataframe),
        history_metrics=calculate_history_metrics(resolved_history),
        issues=issues,
        loaded_at=loaded_at or datetime.now(),
        weekly_raw_df=snapshot.weekly_df,
        history_raw_df=snapshot.history_df,
        voyage_history_df=voyage_history,
        master_data_df=master_clean.dataframe,
        master_data_raw_df=snapshot.master_data_df,
        schema_issues=snapshot.read_issues + snapshot.schema_issues,
        voyage_profiles_df=voyage_profiles,
        schedule_reliability_df=schedule_reliability,
        week_rollover_df=week_rollover,
        quality_issues_df=quality_issues,
    )


def _status_text(status: WorkbookHealthStatus, *, preserving_existing_data: bool = False) -> str:
    if preserving_existing_data and status not in {WorkbookHealthStatus.READY, WorkbookHealthStatus.READY_WITH_WARNINGS}:
        return "Refresh failed; showing previously loaded data"
    labels = {
        WorkbookHealthStatus.READY: "Ready",
        WorkbookHealthStatus.READY_WITH_WARNINGS: "Ready with warnings",
        WorkbookHealthStatus.NOT_CONFIGURED: "Workbook not configured",
        WorkbookHealthStatus.FILE_NOT_FOUND: "Workbook file not found",
        WorkbookHealthStatus.INVALID_WORKBOOK: "Invalid workbook",
        WorkbookHealthStatus.LOAD_ERROR: "Workbook load error",
    }
    return labels.get(status, "Unknown")


def _empty_dashboard_message(health: WorkbookHealth, error: Exception | None) -> str | None:
    if health.status == WorkbookHealthStatus.NOT_CONFIGURED:
        return "Workbook not configured.\n\nSelect the SharePoint/OneDrive-synced Excel workbook to begin."
    if health.status == WorkbookHealthStatus.FILE_NOT_FOUND:
        return "Workbook could not be loaded.\n\nCheck OneDrive sync or update the workbook location in Settings."
    if health.status == WorkbookHealthStatus.INVALID_WORKBOOK:
        details = "\n".join(health.errors[:3])
        return f"Workbook could not be loaded because its structure is not valid for this dashboard.{chr(10) + chr(10) + details if details else ''}"
    if health.status == WorkbookHealthStatus.LOAD_ERROR or error is not None:
        return "Workbook could not be loaded.\n\nTechnical details were written to the application log."
    return None


def _setup_title(status: WorkbookHealthStatus) -> str:
    if status == WorkbookHealthStatus.NOT_CONFIGURED:
        return "Workbook not configured"
    if status == WorkbookHealthStatus.FILE_NOT_FOUND:
        return "Workbook unavailable"
    if status == WorkbookHealthStatus.INVALID_WORKBOOK:
        return "Invalid workbook"
    if status == WorkbookHealthStatus.LOAD_ERROR:
        return "Workbook load error"
    return "Workbook setup"


def _empty_history_filter_options() -> dict[str, list[str]]:
    return {key: [ALL_OPTION] for key in ["Vessel", "Voyage", "Week", "Month", "Year", "User", "Field", "Booking number"]}


def _options_from_column(df: pd.DataFrame, column: str) -> list[str]:
    if df.empty or column not in df.columns:
        return [ALL_OPTION]
    values = _unique_values(df[column].tolist())
    return [ALL_OPTION] + values


def _options_from_frames(frames: list[pd.DataFrame], column: str) -> list[str]:
    values: list[Any] = []
    for frame in frames:
        if column in frame.columns:
            values.extend(frame[column].tolist())
    return [ALL_OPTION] + _unique_values(values)


def _unique_values(values: list[Any]) -> list[str]:
    normalized: dict[str, str] = {}
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if not text or text.casefold() == "nan":
            continue
        normalized.setdefault(text.casefold(), text)
    return sorted(normalized.values(), key=str.casefold)


def _filter_value(value: Any | None) -> Any | None:
    if value is None:
        return None
    if str(value).strip().casefold() == ALL_OPTION.casefold():
        return None
    if str(value).strip() == "":
        return None
    return value


def _history_display_frame(history_df: pd.DataFrame, *, newest_first: bool = False) -> pd.DataFrame:
    columns = [
        "Timestamp",
        "User",
        "Vessel",
        "Voyage",
        "Booking number",
        "Field",
        "OldValue",
        "NewValue",
        "Week",
        "RowID",
    ]
    if history_df.empty:
        return pd.DataFrame(columns=columns)

    display = history_df.copy()
    if "Timestamp" in display.columns:
        display["_timestamp_sort"] = pd.to_datetime(display["Timestamp"], errors="coerce")
        display = display.sort_values(by="_timestamp_sort", ascending=not newest_first, kind="mergesort", na_position="last")
        display = display.drop(columns=["_timestamp_sort"])
    existing_columns = [column for column in columns if column in display.columns]
    return display[existing_columns].reset_index(drop=True)


def _has_operational_weekly_rows(df: pd.DataFrame) -> bool:
    if df.empty:
        return False
    if "_is_operational" not in df.columns:
        return False
    return bool(df["_is_operational"].fillna(False).astype(bool).any())


def _has_records(df: pd.DataFrame) -> bool:
    return not df.empty and bool(df.notna().any(axis=1).any())


def _voyage_history_frame(data: LoadedWorkbookData) -> pd.DataFrame:
    return data.voyage_history_df if data.voyage_history_df is not None else data.history_df


def _material_revision_counts(history_df: pd.DataFrame) -> dict[str, int]:
    counts = _empty_material_counts()
    if history_df.empty or "RowID" not in history_df.columns:
        return counts

    by_row = calculate_revision_counts(history_df, "RowID")
    if by_row.empty:
        return counts

    column_map = {
        "ETA": "ETA_revisions",
        "ETD": "ETD_revisions",
        "Cut-Off": "Cut_Off_revisions",
        "ETA T/S": "ETA_T_S_revisions",
        "Vessel": "Vessel_revisions",
        "Voyage": "Voyage_revisions",
    }
    for label, column in column_map.items():
        if column in by_row.columns:
            counts[label] = int(pd.to_numeric(by_row[column], errors="coerce").fillna(0).sum())
    return counts


def _empty_material_counts() -> dict[str, int]:
    return {"ETA": 0, "ETD": 0, "Cut-Off": 0, "ETA T/S": 0, "Vessel": 0, "Voyage": 0}


def _empty_vessel_model(vessel: str | None, message: str) -> VesselAnalyticsModel:
    return VesselAnalyticsModel(
        vessel=vessel,
        empty_message=message,
        summary=None,
        material_revision_counts=_empty_material_counts(),
        schedule_metrics={},
        voyage_table=pd.DataFrame(),
        eta_movement_by_voyage=pd.DataFrame(),
        eta_revisions_by_voyage=pd.DataFrame(),
        teu_by_voyage=pd.DataFrame(),
    )


def _empty_comparison_model(message: str) -> ComparisonModel:
    return ComparisonModel(
        selected_count=0,
        empty_message=message,
        table=pd.DataFrame(),
        eta_movement_chart=pd.DataFrame(),
        eta_revisions_chart=pd.DataFrame(),
        volume_chart=pd.DataFrame(),
    )


def _schedule_metrics_for_vessel(
    weekly_df: pd.DataFrame,
    history_df: pd.DataFrame,
    vessel: Any,
    voyage_table: pd.DataFrame,
) -> dict[str, Any]:
    performance = vessel_schedule_performance(weekly_df, history_df)
    if performance.empty:
        return {
            "average_net_eta_movement": None,
            "average_absolute_eta_movement": None,
            "maximum_delay": None,
            "maximum_early_movement": None,
            "average_eta_revisions_per_voyage": None,
            "most_revised_voyage": None,
        }
    row = performance[performance["Vessel"].map(str).str.casefold() == str(vessel).casefold()]
    if row.empty:
        return {
            "average_net_eta_movement": None,
            "average_absolute_eta_movement": None,
            "maximum_delay": None,
            "maximum_early_movement": None,
            "average_eta_revisions_per_voyage": None,
            "most_revised_voyage": None,
        }
    first = row.iloc[0]
    most_revised = first.get("Most revised Voyage")
    if voyage_table.empty or pd.to_numeric(voyage_table["ETA revisions"], errors="coerce").fillna(0).max() == 0:
        most_revised = None
    return {
        "average_net_eta_movement": first.get("Average net ETA movement"),
        "average_absolute_eta_movement": first.get("Average absolute ETA movement"),
        "maximum_delay": first.get("Maximum delay"),
        "maximum_early_movement": first.get("Maximum early movement"),
        "average_eta_revisions_per_voyage": first.get("Average ETA revisions per Voyage"),
        "most_revised_voyage": most_revised,
    }
