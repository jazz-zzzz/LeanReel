"""Small cooperative cancellation primitive for background service work."""
from __future__ import annotations

import threading


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def throw_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise CancelledWork()


class CancelledWork(Exception):
    """Raised by cooperative workers when a scan batch is cancelled."""
