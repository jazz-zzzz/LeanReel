"""文件列表唯一数据源 — FileRow 和 FileTableStore"""
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from leanreel.data.models import FileSnapshot
from leanreel.gui.file_list import MatchResult, FileDecisionDisplay


@dataclass
class FileRow:
    """文件表格中的一行数据。

    ``key`` 是 (library_folder_id, relative_path) 元组，
    由 ``snap`` 自动推导。
    """
    snap: FileSnapshot
    match: MatchResult | None = field(default=None, repr=False)
    decision: FileDecisionDisplay | None = field(default=None, repr=False)

    @property
    def key(self) -> tuple[int, str]:
        return (self.snap.library_folder_id, self.snap.relative_path)

    @property
    def folder_name(self) -> str:
        name = str(self.snap.relative_path).replace("\\", "/").rsplit("/", 1)[0]
        return name or "."


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

    # ── 写入 ──

    def rebuild(self, rows: list[FileRow], strategies=None, keep_checked: bool = True):
        """用新行列表全量替换当前数据并发出 ``rows_rebuilt`` 信号。"""
        if not keep_checked:
            self._checked.clear()
        else:
            valid = {r.key for r in rows}
            self._checked = {k for k in self._checked if k in valid}
        self._rows = list(rows)
        self._by_key = {r.key: i for i, r in enumerate(self._rows)}
        self._strategies = strategies
        self.rows_rebuilt.emit()

    def update_row(self, key: tuple[int, str], snap: FileSnapshot, match=None):
        """更新单行的快照（和可选的匹配结果），发出 ``row_updated`` 信号。"""
        idx = self._by_key.get(key)
        if idx is None:
            return
        row = self._rows[idx]
        row.snap = snap
        if match is not None:
            row.match = match
        self.row_updated.emit(idx, row)

    def set_checked(self, key: tuple[int, str], state: bool):
        """设置单行的勾选状态，发出 ``checked_changed`` 信号。"""
        if state:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        self.checked_changed.emit()

    def toggle_checked(self, key: tuple[int, str]):
        """翻转单行的勾选状态，发出 ``checked_changed`` 信号。"""
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

    def folder_stats(self) -> dict[str, int]:
        """返回 文件夹名 -> 总大小 的映射。"""
        stats: dict[str, int] = {}
        for row in self._rows:
            stats[row.folder_name] = stats.get(row.folder_name, 0) + row.snap.size_bytes
        return stats
