from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from .excel_reader import SUPPORTED_WORKBOOK_EXTENSIONS, ExcelWorkbookReader
from .models import WorkbookStructure
from .validators import ValidationIssue


class WorkbookHealthStatus(str, Enum):
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    INVALID_WORKBOOK = "INVALID_WORKBOOK"
    LOAD_ERROR = "LOAD_ERROR"


@dataclass(frozen=True, slots=True)
class WorkbookHealth:
    status: WorkbookHealthStatus
    path: Path | None
    filename: str
    exists: bool
    detected_sheets: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.now)
    structure: WorkbookStructure | None = None

    @property
    def can_load(self) -> bool:
        return self.status in {WorkbookHealthStatus.READY, WorkbookHealthStatus.READY_WITH_WARNINGS}


def validate_workbook(
    workbook_path: str | Path | None,
    *,
    required_sheets: list[str] | tuple[str, ...] | None = None,
    optional_sheets: list[str] | tuple[str, ...] | None = None,
) -> WorkbookHealth:
    required = list(required_sheets or ["WEEKLY", "LOG_HISTORY"])
    optional = list(optional_sheets or [])

    if workbook_path is None or str(workbook_path).strip() == "":
        return WorkbookHealth(
            status=WorkbookHealthStatus.NOT_CONFIGURED,
            path=None,
            filename="Not configured",
            exists=False,
            errors=["Workbook path is not configured."],
        )

    path = Path(workbook_path).expanduser()
    filename = path.name or str(path)
    if path.suffix.lower() not in SUPPORTED_WORKBOOK_EXTENSIONS:
        return WorkbookHealth(
            status=WorkbookHealthStatus.INVALID_WORKBOOK,
            path=path,
            filename=filename,
            exists=path.exists(),
            errors=[f"Unsupported workbook extension: {path.suffix or '(none)'}. Supported extensions: {', '.join(sorted(SUPPORTED_WORKBOOK_EXTENSIONS))}."],
        )

    if not path.exists():
        return WorkbookHealth(
            status=WorkbookHealthStatus.FILE_NOT_FOUND,
            path=path,
            filename=filename,
            exists=False,
            errors=["Workbook file was not found. Check OneDrive sync or update the workbook location in Settings."],
        )

    try:
        snapshot = ExcelWorkbookReader(path).read_snapshot()
        structure = snapshot.structure
    except Exception as exc:
        return WorkbookHealth(
            status=WorkbookHealthStatus.LOAD_ERROR,
            path=path,
            filename=filename,
            exists=True,
            errors=[f"Workbook could not be opened read-only: {type(exc).__name__}: {exc}"],
        )

    return health_from_structure(
        path,
        structure,
        required_sheets=required,
        optional_sheets=optional,
        compatibility_issues=snapshot.read_issues + snapshot.schema_issues,
    )


def health_from_structure(
    workbook_path: str | Path,
    structure: WorkbookStructure,
    *,
    required_sheets: list[str] | tuple[str, ...] | None = None,
    optional_sheets: list[str] | tuple[str, ...] | None = None,
    compatibility_issues: list[ValidationIssue] | None = None,
) -> WorkbookHealth:
    """Build health status from an already-read snapshot without reopening it."""

    path = Path(workbook_path).expanduser()
    required = list(required_sheets or ["WEEKLY", "LOG_HISTORY"])
    optional = list(optional_sheets or [])
    available = {sheet.upper() for sheet in structure.sheet_names}
    missing_required = [sheet for sheet in required if sheet.upper() not in available]
    missing_optional = [sheet for sheet in optional if sheet.upper() not in available]

    errors = [f"Required sheet is missing: {sheet}" for sheet in missing_required]
    warnings = [f"Optional sheet is missing: {sheet}" for sheet in missing_optional]
    for issue in compatibility_issues or []:
        target = errors if issue.severity == "ERROR" else warnings
        message = issue.message if issue.location is None else f"{issue.message} [{issue.location}]"
        if message not in target:
            target.append(message)
    if errors:
        status = WorkbookHealthStatus.INVALID_WORKBOOK
    elif warnings:
        status = WorkbookHealthStatus.READY_WITH_WARNINGS
    else:
        status = WorkbookHealthStatus.READY

    return WorkbookHealth(
        status=status,
        path=path,
        filename=path.name or str(path),
        exists=True,
        detected_sheets=structure.sheet_names,
        errors=errors,
        warnings=warnings,
        structure=structure,
    )


def health_message(health: WorkbookHealth, *, preserving_existing_data: bool = False) -> str:
    if health.status == WorkbookHealthStatus.READY:
        return "Workbook is ready."
    if health.status == WorkbookHealthStatus.READY_WITH_WARNINGS:
        return "Workbook loaded with warnings."
    if health.status == WorkbookHealthStatus.NOT_CONFIGURED:
        return "Workbook not configured. Select the SharePoint/OneDrive-synced Excel workbook to begin."
    if preserving_existing_data:
        return "Workbook could not be refreshed. The previously loaded data is still being shown."
    if health.status == WorkbookHealthStatus.FILE_NOT_FOUND:
        return "Workbook could not be loaded. Check OneDrive sync or update the workbook location in Settings."
    if health.status == WorkbookHealthStatus.INVALID_WORKBOOK:
        return "Workbook could not be loaded because its structure is not valid for this dashboard."
    return "Workbook could not be loaded. Technical details were written to the application log."
