"""应用信号定义 — 集中管理所有跨组件信号契约"""
from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    """线程安全的跨组件信号总线。

    每个信号有明确的参数类型约定，避免 Shiboken 类型转换警告。
    """

    # ── 扫描信号 ──

    probed = Signal(object, object)
    """探测完成 — (FileSnapshot, MatchResult|None)"""

    scan_finished = Signal(object, object, object, object)
    """扫描批次完成 — (list[FileSnapshot], folder_id:int|None, path:str|None, pending_jobs:list)"""

    all_done = Signal()
    """全部探测任务完成"""

    progress = Signal(int, int)
    """探测进度 — (done: int, total: int)"""

    # ── 编码信号 ──

    task_updated = Signal(object)
    """编码任务状态更新 — (EncodeTask)"""

    encoding_done = Signal()
    """全部编码任务完成"""
