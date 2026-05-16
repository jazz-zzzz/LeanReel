"""文件列表单一数据源 — Store 模式"""
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

from leanreel.data.models import FileSnapshot
from leanreel.gui.file_list import MatchResult, FileDecisionDisplay


@dataclass
class FileRow:
    """文件列表中的一行 — 聚合快照、匹配结果和显示状态"""
    snap: FileSnapshot
    match: MatchResult | None = None
    decision: FileDecisionDisplay | None = None

    @property
    def key(self) -> tuple[int, str]:
        return (self.snap.library_folder_id, self.snap.relative_path)

    @property
    def folder_name(self) -> str:
        p = str(self.snap.relative_path).replace("\\", "/")
        if "/" in p:
            return p.rsplit("/", 1)[0]
        return "."


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
        self._filter_key: str = "all"
        self._strategies: list | None = None

    # ── 写入 ──

    def rebuild(self, rows: list[FileRow], strategies=None, keep_checked=True):
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
        idx = self._by_key.get(key)
        if idx is None:
            return
        row = self._rows[idx]
        row.snap = snap
        if match is not None:
            row.match = match
        self.row_updated.emit(idx, row)

    def set_checked(self, key, state: bool):
        if state:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        self.checked_changed.emit()

    def toggle_checked(self, key):
        self.set_checked(key, key not in self._checked)

    # ── 查询 ──

    def count(self) -> int:
        return len(self._rows)

    def row_at(self, index: int) -> FileRow:
        return self._rows[index]

    def row_by_key(self, key) -> FileRow | None:
        idx = self._by_key.get(key)
        return self._rows[idx] if idx is not None else None

    def is_checked(self, key) -> bool:
        return key in self._checked

    def checked_keys(self) -> list[tuple[int, str]]:
        return sorted(self._checked)

    def folder_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        for row in self._rows:
            stats[row.folder_name] = stats.get(row.folder_name, 0) + row.snap.size_bytes
        return stats

    def set_filter(self, filter_key: str):
        self._filter_key = filter_key

    def visible_rows(self) -> list[tuple[int, FileRow]]:
        result = []
        for i, row in enumerate(self._rows):
            if self._is_visible(row):
                result.append((i, row))
        return result

    def _is_visible(self, row: FileRow) -> bool:
        if self._filter_key == "all":
            return True
        d = row.decision
        if d is None:
            return self._filter_key != "checked"
        if self._filter_key == "processable":
            return d.processable
        if self._filter_key == "protected":
            return d.status_key == "protected"
        if self._filter_key == "probe_failed":
            return d.status_key == "probe_failed"
        if self._filter_key == "checked":
            return row.key in self._checked
        return True
