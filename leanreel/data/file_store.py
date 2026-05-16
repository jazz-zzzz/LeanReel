"""文件表格数据存储 — Observable 数据源，通过 Qt 信号通知视图更新"""
from PySide6.QtCore import QObject, Signal


class FileRow:
    """Store 中的一行数据，包含文件快照和决策展示信息。"""

    def __init__(self, snap, decision=None):
        self.snap = snap
        self.decision = decision

    @property
    def key(self) -> tuple:
        """返回 (library_folder_id, relative_path) 作为唯一标识。"""
        return (self.snap.library_folder_id, self.snap.relative_path)

    @property
    def folder_name(self) -> str:
        """从 relative_path 提取文件夹名称。"""
        p = str(self.snap.relative_path).replace("\\", "/").rsplit("/", 1)[0]
        return p or "."


class FileTableStore(QObject):
    """持有全部文件行的数据存储，通过 Qt 信号驱动视图更新。

    Signals:
        rows_rebuilt: 整表重建后触发（rebuild 调用后）。
        row_updated: 单行更新后触发，参数为 (idx, FileRow)。
        checked_changed: 勾选状态变更后触发。
    """

    rows_rebuilt = Signal()
    row_updated = Signal(int, object)  # (idx, FileRow)
    checked_changed = Signal()

    def __init__(self):
        super().__init__()
        self._rows: list[FileRow] = []
        self._checked: set[tuple] = set()

    # ── 写操作 ──

    def rebuild(self, rows: list[FileRow]):
        """替换全部行数据，清空勾选，触发 rows_rebuilt。"""
        self._rows = list(rows)
        self._checked.clear()
        self.rows_rebuilt.emit()

    def update_row(self, key: tuple, new_snap):
        """用新快照更新匹配 key 的行，触发 row_updated( idx, row )。"""
        for i, row in enumerate(self._rows):
            if row.key == key:
                row.snap = new_snap
                self.row_updated.emit(i, row)
                return

    def set_checked(self, key: tuple, checked: bool):
        """设置单行的勾选状态，触发 checked_changed。"""
        if checked:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        self.checked_changed.emit()

    # ── 读操作 ──

    def count(self) -> int:
        return len(self._rows)

    def row_at(self, index: int) -> FileRow:
        return self._rows[index]

    def row_by_key(self, key: tuple) -> FileRow | None:
        for row in self._rows:
            if row.key == key:
                return row
        return None

    def is_checked(self, key: tuple) -> bool:
        return key in self._checked

    def folder_stats(self) -> dict[str, int]:
        """返回 {folder_name: total_bytes} 字典。"""
        stats: dict[str, int] = {}
        for row in self._rows:
            stats[row.folder_name] = stats.get(row.folder_name, 0) + row.snap.size_bytes
        return stats
