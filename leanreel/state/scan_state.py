"""扫描状态 — 每个文件夹独立的扫描进度"""
from dataclasses import dataclass


@dataclass
class ScanState:
    """单个文件夹的扫描/探测状态。"""
    running: bool = False
    token: int = 0
    total_files: int = 0
    done_files: int = 0

    @property
    def finished(self) -> bool:
        return self.total_files > 0 and self.done_files >= self.total_files

    def reset(self):
        self.running = False
        self.token = 0
        self.total_files = 0
        self.done_files = 0
