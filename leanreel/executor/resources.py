"""Helpers for locating bundled command-line tools."""
from __future__ import annotations

import sys
from pathlib import Path


def bundled_resource_path(*parts: str) -> Path:
    """Return a resource path that works in source and PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath("resources", *parts)
