"""应用共享状态 — 所有 Controller 通过此对象共享可变状态"""
from dataclasses import dataclass, field
from leanreel.domain.models import FileSnapshot, Strategy
from leanreel.state.scan_state import ScanState


@dataclass
class AppState:
    """应用级共享状态。Controller 通过此对象读写。"""

    current_snapshots: list[FileSnapshot] = field(default_factory=list)
    current_folder_paths: dict[int, str] = field(default_factory=dict)
    strategy_overrides: dict = field(default_factory=dict)
    active_custom_path: str | None = None

    # 多库扫描隔离
    scan_token: int = 0         # 扫描流程控制（per-scan，切库不动）
    library_token: int = 0      # 库切换控制（per-library）
    active_scan_folder_id: int = 0
    scan_states: dict[int, ScanState] = field(default_factory=dict)  # token → ScanState

    # 策略覆盖：按 library_folder_id 隔离
    strategy_overrides: dict = field(default_factory=dict)

    def reset(self):
        self.current_snapshots = []
        self.current_folder_paths = {}
        self.strategy_overrides = {}
        self.active_custom_path = None
        self.scan_token = 0
        self.library_token = 0
        self.active_scan_folder_id = 0
        self.scan_states.clear()
