"""应用共享状态 — 所有 Controller 通过此对象共享可变状态"""
from dataclasses import dataclass, field
from leanreel.domain.models import FileSnapshot, Strategy


@dataclass
class AppState:
    """应用级共享状态。Controller 通过此对象读写。

    不持有 Qt 信号 — 状态变更通过 Store (FileTableStore) 或回调通知。
    """
    current_snapshots: list[FileSnapshot] = field(default_factory=list)
    current_folder_paths: dict[int, str] = field(default_factory=dict)
    strategy_overrides: dict = field(default_factory=dict)
    active_custom_path: str | None = None

    # 扫描控制
    refresh_running: bool = False
    scan_token: int = 0

    def reset(self):
        """完全重置状态"""
        self.current_snapshots = []
        self.current_folder_paths = {}
        self.strategy_overrides = {}
        self.active_custom_path = None
        self.refresh_running = False
        self.scan_token = 0
