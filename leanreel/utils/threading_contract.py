"""Small runtime checks for keeping slow work off the Qt main thread."""

from __future__ import annotations

import threading

_MAIN_THREAD_ID: int | None = None


def capture_main_thread() -> int:
    """Record and return the thread that owns UI mutations."""
    global _MAIN_THREAD_ID
    if _MAIN_THREAD_ID is None:
        _MAIN_THREAD_ID = threading.get_ident()
    return _MAIN_THREAD_ID


def is_main_thread() -> bool:
    """Return True when running on the captured main thread."""
    return _MAIN_THREAD_ID is not None and threading.get_ident() == _MAIN_THREAD_ID


def require_main_thread(action: str = "UI mutation") -> None:
    """Raise if a UI/data mutation happens outside the captured main thread."""
    if _MAIN_THREAD_ID is None:
        return
    if threading.get_ident() != _MAIN_THREAD_ID:
        raise RuntimeError(f"{action} must run on the main thread")


def forbid_main_thread(action: str = "slow operation") -> None:
    """Raise if slow work is attempted on the captured main thread."""
    if _MAIN_THREAD_ID is None:
        return
    if threading.get_ident() == _MAIN_THREAD_ID:
        raise RuntimeError(f"{action} must not run on the main thread")


def _reset_for_tests() -> None:
    global _MAIN_THREAD_ID
    _MAIN_THREAD_ID = None
