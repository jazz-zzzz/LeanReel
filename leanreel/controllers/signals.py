"""应用信号定义 — 集中管理所有跨组件信号契约"""
from PySide6.QtCore import QObject, Signal

from leanreel.domain.models import FileSnapshot, MatchResult, Strategy
from leanreel.executor.worker import EncodeTask


class AppSignals(QObject):
    """线程安全的跨组件信号总线。

    每个信号有明确的参数类型约定，避免 Shiboken 类型转换警告。
    """

    # ── 扫描信号 ──

    probed = Signal(FileSnapshot, object)
    """探测完成 — (FileSnapshot, MatchResult|None)"""

    all_done = Signal()
    """全部探测任务完成"""

    progress = Signal(int, int)
    """探测进度 — (done: int, total: int)"""

    # ── 预扫描信号 ──

    scan_ready = Signal(list, list, int)
    """文件遍历完成 — (placeholders: list[FileSnapshot], folder_inputs: list, token: int)"""

    scan_resolved = Signal(list, list, int)
    """缓存解析完成 — (snapshots: list[FileSnapshot], folder_inputs: list, token: int)"""

    library_cache_loaded = Signal(list, int)
    """库缓存加载完成 — (snapshots: list[FileSnapshot], token: int)"""

    probe_result = Signal(object, int)
    """单个探测结果 — (snapshot: FileSnapshot, token: int)"""

    strategies_ready = Signal(list)
    """后台策略排序完成 — (strategies: list[Strategy])"""

    # ── 编码信号 ──

    task_updated = Signal(EncodeTask)
    """编码任务状态更新 — (EncodeTask)"""

    encoding_done = Signal()
    """全部编码任务完成"""
