from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .config import DEFAULT_EXPECTED_WORKBOOK_FILENAME
from .excel_reader import SUPPORTED_WORKBOOK_EXTENSIONS


@dataclass(frozen=True, slots=True)
class WorkbookDiscoveryResult:
    candidates: list[Path]
    searched_roots: list[Path]
    skipped_roots: list[Path] = field(default_factory=list)
    directories_scanned: int = 0
    truncated: bool = False


def discover_workbooks(
    *,
    expected_filename: str | None = DEFAULT_EXPECTED_WORKBOOK_FILENAME,
    roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    max_depth: int = 5,
    max_directories: int = 1500,
) -> WorkbookDiscoveryResult:
    """Search likely synced folders for the expected workbook filename.

    The helper is intentionally bounded. It assists workbook selection but never
    silently changes configuration and never scans an entire drive.
    """

    candidate_roots = [Path(root).expanduser() for root in roots] if roots is not None else default_discovery_roots()
    searched_roots: list[Path] = []
    skipped_roots: list[Path] = []
    candidates: dict[str, Path] = {}
    scanned = 0
    truncated = False

    for root in candidate_roots:
        if not root.exists() or not root.is_dir():
            skipped_roots.append(root)
            continue
        searched_roots.append(root)
        queue: deque[tuple[Path, int]] = deque([(root, 0)])
        while queue:
            current, depth = queue.popleft()
            scanned += 1
            if scanned > max_directories:
                truncated = True
                queue.clear()
                break

            try:
                entries = list(current.iterdir())
            except OSError:
                continue

            for entry in entries:
                if entry.is_file() and _is_candidate_file(entry, expected_filename):
                    candidates.setdefault(str(entry.resolve()), entry)
                elif depth < max_depth and entry.is_dir() and not _should_skip_directory(entry):
                    queue.append((entry, depth + 1))

    return WorkbookDiscoveryResult(
        candidates=sorted(candidates.values(), key=lambda path: str(path).casefold()),
        searched_roots=searched_roots,
        skipped_roots=skipped_roots,
        directories_scanned=scanned,
        truncated=truncated,
    )


def default_discovery_roots() -> list[Path]:
    roots: list[Path] = []
    user_profile = os.environ.get("USERPROFILE")
    home = Path(user_profile).expanduser() if user_profile else Path.home()
    if home.exists():
        roots.extend(_onedrive_directories(home))
        documents = home / "Documents"
        if documents.exists():
            roots.append(documents)
    return _unique_paths(roots)


def _onedrive_directories(home: Path) -> list[Path]:
    try:
        children = list(home.iterdir())
    except OSError:
        return []
    return [child for child in children if child.is_dir() and child.name.casefold().startswith("onedrive")]


def _is_candidate_file(path: Path, expected_filename: str | None) -> bool:
    if path.suffix.lower() not in SUPPORTED_WORKBOOK_EXTENSIONS:
        return False
    if expected_filename:
        return path.name.casefold() == expected_filename.casefold()
    return True


def _should_skip_directory(path: Path) -> bool:
    name = path.name.casefold()
    return name in {
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        "$recycle.bin",
        "appdata",
    }


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique
