from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def open_folder(path: str | Path, *, create: bool = True) -> tuple[bool, str | None]:
    folder = Path(path).expanduser()
    try:
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        elif not folder.exists():
            return False, "Folder does not exist."
        system = platform.system()
        if system == "Windows":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
