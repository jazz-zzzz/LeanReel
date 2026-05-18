"""扫描状态 — 每个文件夹独立的扫描进度"""
from dataclasses import dataclass


@dataclass
class ScanState:
    """单个扫描批次的探测状态。anchor_folder_id 用于判断属于哪个库。"""
    running: bool = False
    token: int = 0
    total_files: int = 0
    done_files: int = 0
    anchor_folder_id: int = 0     # 关联的文件夹，用于切库时匹配

    @property
    def finished(self) -> bool:
        return self.total_files > 0 and self.done_files >= self.total_files

    def reset(self):
        self.running = False
        self.token = 0
        self.total_files = 0
        self.done_files = 0
