"""应用信号定义 — 集中管理所有跨组件信号契约"""
from PySide6.QtCore import QObject, Signal

from leanreel.domain.models import FileSnapshot


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

    scan_ready = Signal(object, object, int)
    """文件遍历完成 — (placeholders, folder_inputs, token)"""

    scan_resolved = Signal(object, object, int)
    """缓存解析完成 — (snapshots, folder_inputs, token)"""

    library_cache_loaded = Signal(object, int)
    """库缓存加载完成 — (snapshots, token)"""

    probe_result = Signal(object, int)
    """单个探测结果 — (snapshot, token)"""

    strategies_ready = Signal(object)
    """后台策略排序完成 — (strategies)"""

    # ── 编码信号 ──

    task_updated = Signal(object)
    """编码任务状态更新 — (EncodeTask)"""

    encoding_done = Signal()
    """全部编码任务完成"""
