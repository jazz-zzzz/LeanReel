"""文件列表唯一数据源 — FileTableStore 持有所有行数据和勾选状态"""
import threading

from PySide6.QtCore import QObject, Signal

from leanreel.utils.threading_contract import require_main_thread
from leanreel.domain.models import FileSnapshot, FileRow


class FileTableStore(QObject):
    """文件列表唯一数据源 — 所有视图和控制器只读写这一个对象。"""

    rows_rebuilt = Signal()
    row_updated = Signal(int, object)       # index, FileRow
    checked_changed = Signal()

    def __init__(self):
        super().__init__()
        self._rows: list[FileRow] = []
        self._by_key: dict[tuple[int, str], int] = {}
        self._checked: set[tuple[int, str]] = set()
        self._strategies: list | None = None
        self._lock = threading.Lock()  # 保护 rebuild/update_row 并发

    # ── 写入 ──

    def rebuild(self, rows: list[FileRow], strategies=None, keep_checked: bool = True):
        """用新行列表全量替换当前数据并发出 ``rows_rebuilt`` 信号。"""
        require_main_thread("FileTableStore.rebuild")
        with self._lock:
            if not keep_checked:
                self._checked.clear()
            else:
                valid = {r.key for r in rows}
                self._checked = {k for k in self._checked if k in valid}
            self._rows = list(rows)
            self._by_key = {r.key: i for i, r in enumerate(self._rows)}
            self._strategies = strategies
        self.rows_rebuilt.emit()

    def update_row(self, key: tuple[int, str], snap: FileSnapshot, match=None, decision=None):
        """更新单行的快照，发出 ``row_updated`` 信号。线程安全。"""
        require_main_thread("FileTableStore.update_row")
        with self._lock:
            idx = self._by_key.get(key)
            if idx is None:
                return
            row = self._rows[idx]
            row.snap = snap
            if match is not None:
                row.match = match
            if decision is not None:
                row.decision = decision
        self.row_updated.emit(idx, row)

    def set_checked(self, key: tuple[int, str], state: bool):
        """设置单行的勾选状态。仅当状态实际变化时发出 ``checked_changed`` 信号。"""
        require_main_thread("FileTableStore.set_checked")
        changed = False
        if state:
            if key not in self._checked:
                self._checked.add(key)
                changed = True
        else:
            if key in self._checked:
                self._checked.discard(key)
                changed = True
        if changed:
            self.checked_changed.emit()

    def toggle_checked(self, key: tuple[int, str]):
        """翻转单行的勾选状态，发出 ``checked_changed`` 信号。"""
        require_main_thread("FileTableStore.toggle_checked")
        if key in self._checked:
            self._checked.discard(key)
        else:
            self._checked.add(key)
        self.checked_changed.emit()

    # ── 查询 ──

    def count(self) -> int:
        return len(self._rows)

    def row_at(self, index: int) -> FileRow:
        return self._rows[index]

    def row_by_key(self, key: tuple[int, str]) -> FileRow | None:
        idx = self._by_key.get(key)
        return self._rows[idx] if idx is not None else None

    def is_checked(self, key: tuple[int, str]) -> bool:
        return key in self._checked

    def checked_keys(self) -> list[tuple[int, str]]:
        return sorted(self._checked)

    def rows(self) -> tuple[FileRow, ...]:
        return tuple(self._rows)

    def row_by_relative_path(self, relative_path: str) -> FileRow | None:
        for row in self._rows:
            if row.snap.relative_path == relative_path:
                return row
        return None

    def folder_stats(self) -> dict[str, int]:
        """返回 文件夹名 -> 总大小 的映射。"""
        stats: dict[str, int] = {}
        for row in self._rows:
            stats[row.folder_name] = stats.get(row.folder_name, 0) + row.snap.size_bytes
        return stats
