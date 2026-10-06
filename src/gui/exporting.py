from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


@dataclass(frozen=True, slots=True)
class CsvExportResult:
    success: bool
    message: str
    path: Path | None = None
    row_count: int = 0


def export_visible_csv(
    frame: pd.DataFrame,
    destination: str | Path,
    *,
    visible_columns: Iterable[str] | None = None,
) -> CsvExportResult:
    """Export a local analytical view without touching the source workbook."""

    if frame.empty:
        return CsvExportResult(False, "There are no visible analytical rows to export.")
    columns = list(visible_columns) if visible_columns is not None else [name for name in frame.columns if not str(name).startswith("_")]
    columns = [name for name in columns if name in frame.columns]
    if not columns:
        return CsvExportResult(False, "There are no visible analytical columns to export.")
    path = Path(destination).expanduser()
    if path.suffix.lower() != ".csv":
        return CsvExportResult(False, "Analytical exports must use a .csv file. The Excel source workbook is never an export destination.")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[columns].to_csv(path, index=False, encoding="utf-8-sig", date_format="%d.%m.%Y %H:%M")
    return CsvExportResult(True, f"Exported {len(frame):,} rows to {path.name}.", path, len(frame))
