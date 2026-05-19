"""Shared mutable application state for controllers."""
from dataclasses import dataclass, field

from leanreel.domain.models import FileSnapshot
from leanreel.state.scan_state import ScanState


@dataclass
class AppState:
    """State shared by controllers.

    current_* fields describe the visible library/UI context.
    scan_states describes independent background scan batches by token.
    """

    current_snapshots: list[FileSnapshot] = field(default_factory=list)
    current_library_id: int | None = None
    current_folder_paths: dict[int, str] = field(default_factory=dict)
    strategy_overrides: dict = field(default_factory=dict)
    active_custom_path: str | None = None

    scan_token: int = 0
    library_token: int = 0
    active_scan_folder_id: int = 0
    scan_states: dict[int, ScanState] = field(default_factory=dict)

    def reset(self):
        self.current_snapshots = []
        self.current_library_id = None
        self.current_folder_paths = {}
        self.strategy_overrides = {}
        self.active_custom_path = None
        self.scan_token = 0
        self.library_token = 0
        self.active_scan_folder_id = 0
        self.scan_states.clear()
