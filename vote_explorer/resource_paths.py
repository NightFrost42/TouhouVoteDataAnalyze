"""Resolve data files in source, folder-based, and single-file builds."""

from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
BUNDLED_ROOT = Path(getattr(sys, "_MEIPASS", PACKAGE_DIR))
EXTERNAL_DATA_MARKERS = (
    "rankings.csv",
    "ballot_totals.csv",
    "analysis_data_manifest.json",
    "analysis_character_metrics_all.csv",
)


def resolve_data_dir() -> Path:
    """Prefer an updateable data folder beside the EXE when one exists.

    Folder-based distributions keep ``data`` next to the executable so users
    can rebuild or replace the dataset without rebuilding the program.  A
    PyInstaller single-file build falls back to the copy extracted from the
    executable into ``sys._MEIPASS``.  Source runs continue to use the package
    directory's normal ``data`` folder.
    """

    if getattr(sys, "frozen", False):
        external = Path(sys.executable).resolve().parent / "data"
        if external.is_dir() and all((external / name).is_file() for name in EXTERNAL_DATA_MARKERS):
            return external
        return BUNDLED_ROOT / "data"
    return PACKAGE_DIR / "data"


DATA_DIR = resolve_data_dir()
