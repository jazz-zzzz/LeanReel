"""树视图适配器 — 连接 FileTableStore 到 QTreeWidget"""
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from leanreel.gui.utils import _format_bytes
from leanreel.gui.theme import (
    _COLOR_CODEC_OK,
    _COLOR_CODEC_MISSING,
    _COLOR_PROBE_FAILED,
    _COLOR_HDR_DV,
    _COLOR_HDR_HDR10,
    _COLOR_HDR_SDR,
)
from leanreel.gui.file_list import _SortableTreeItem


class TreeAdapter(QObject):
    """监听 FileTableStore 信号，自动同步 QTreeWidget。"""

    def __init__(self, store, tree: QTreeWidget):
        super().__init__()
        self._store = store
        self._tree = tree
        self._folder_items: dict[str, QTreeWidgetItem] = {}
        self._child_by_key: dict[tuple[int, str], QTreeWidgetItem] = {}
        self._dirty = False
        store.rows_rebuilt.connect(self._on_rebuild)
        store.row_updated.connect(self._on_row_updated)
        store.checked_changed.connect(self._on_checked_changed)

    # ── 整表重建 ──

    def _on_rebuild(self):
        if self._tree.parent() is not None and not self._tree.isVisible():
            self._tree.clear()
            self._folder_items.clear()
            self._child_by_key.clear()
            self._dirty = True
            return
        self._rebuild_now()

    def ensure_current(self):
        if self._dirty:
            self._rebuild_now()

    def _rebuild_now(self):
        self._tree.blockSignals(True)
        self._tree.clear()
        self._folder_items.clear()
        self._child_by_key.clear()
        self._dirty = False
        store = self._store
        stats = store.folder_stats()
        for i in range(store.count()):
            row = store.row_at(i)
            fname = row.folder_name
            folder = self._folder_items.get(fname)
            if folder is None:
                total = stats.get(fname, 0)
                folder = _SortableTreeItem([fname, _format_bytes(total), "", "", "", ""])
                folder.setData(1, Qt.UserRole, total)
                folder.setData(0, Qt.UserRole, row.key[0])  # folder_id for context menu
                font = folder.font(0)
                font.setBold(True)
                folder.setFont(0, font)
                self._folder_items[fname] = folder
                self._tree.addTopLevelItem(folder)
            child = self._render_child(row)
            self._child_by_key[row.key] = child
            folder.addChild(child)
        self._tree.blockSignals(False)

    def _render_child(self, row) -> QTreeWidgetItem:
        d = row.decision
        snap = row.snap
        child = QTreeWidgetItem([
            snap.file_name,
            _format_bytes(snap.size_bytes),
            self._format_codec(snap),
            self._hdr_text(snap),
            d.strategy_text if d else "—",
            d.result_text if d else "—",
        ])
        child.setData(0, Qt.UserRole, row.key)
        child.setToolTip(0, d.tooltip if d else snap.file_name)
        if d and d.processable:
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            child.setCheckState(0, Qt.Checked if self._store.is_checked(row.key) else Qt.Unchecked)
        else:
            child.setFlags((child.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEnabled)
            child.setToolTip(0, d.tooltip if d else "")
        # 颜色
        if snap.video_codec:
            child.setForeground(2, _COLOR_CODEC_OK)
        elif d and d.status_key == "probe_failed":
            child.setForeground(2, _COLOR_PROBE_FAILED)
        else:
            child.setForeground(2, _COLOR_CODEC_MISSING)
        child.setForeground(3, self._hdr_color(snap))
        if d and d.status_key == "protected":
            child.setForeground(4, _COLOR_HDR_DV)
        elif d and d.status_key == "probe_failed":
            child.setForeground(4, _COLOR_PROBE_FAILED)
        return child

    # ── 单行更新 ──

    def _update_child(self, child, row):
        d = row.decision
        snap = row.snap
        child.setText(1, _format_bytes(snap.size_bytes))
        child.setText(2, self._format_codec(snap))
        child.setText(3, self._hdr_text(snap))
        child.setText(4, d.strategy_text if d else "—")
        child.setText(5, d.result_text if d else "—")
        child.setForeground(2, _COLOR_CODEC_OK if snap.video_codec else _COLOR_CODEC_MISSING)
        child.setForeground(3, self._hdr_color(snap))
        if d and d.status_key == "protected":
            child.setForeground(4, _COLOR_HDR_DV)
        elif d and d.status_key == "probe_failed":
            child.setForeground(4, _COLOR_PROBE_FAILED)
        else:
            child.setForeground(4, QColor())
        if d and d.processable:
            child.setFlags(child.flags() | Qt.ItemIsEnabled)
        else:
            child.setFlags((child.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEnabled)

    def _on_row_updated(self, idx, row):
        child = self._child_by_key.get(row.key)
        if child is None:
            return
        self._update_child(child, row)
        fname = row.folder_name
        folder = self._folder_items.get(fname)
        if folder:
            stats = self._store.folder_stats()
            total = stats.get(fname, 0)
            folder.setText(1, _format_bytes(total))
            folder.setData(1, Qt.UserRole, total)

    # ── 勾选同步 ──

    def _on_checked_changed(self):
        for key, child in self._child_by_key.items():
            if child.flags() & Qt.ItemIsEnabled:
                state = Qt.Checked if self._store.is_checked(key) else Qt.Unchecked
                if child.checkState(0) != state:
                    child.setCheckState(0, state)

    # ── 过滤 ──

    def apply_tree_filter(self, filter_key: str):
        for fname, folder in self._folder_items.items():
            visible = 0
            for i in range(folder.childCount()):
                child = folder.child(i)
                key = child.data(0, Qt.UserRole)
                row = self._store.row_by_key(key)
                hide = not self._child_visible(row, filter_key, key) if row else False
                child.setHidden(hide)
                if not hide:
                    visible += 1
            folder.setHidden(visible == 0)

    def _child_visible(self, row, filter_key, key) -> bool:
        if filter_key == "all":
            return True
        d = row.decision
        if d is None:
            return filter_key != "checked"
        if filter_key == "processable":
            return d.processable
        if filter_key == "protected":
            return d.status_key == "protected"
        if filter_key == "probe_failed":
            return d.status_key == "probe_failed"
        if filter_key == "checked":
            return self._store.is_checked(key)
        return True

    # ── 格式化工具 ──

    def _format_codec(self, snap) -> str:
        codec = snap.video_codec
        if not codec:
            if snap.probe_ok is False and snap.probe_error:
                return "探测失败"
            if snap.probe_ok is False:
                return "探测中..."
            return "未识别"
        if snap.video_width and snap.video_height:
            return f"{codec} {snap.video_width}x{snap.video_height}"
        return codec

    def _hdr_text(self, snap) -> str:
        return getattr(snap.hdr_type, "value", str(snap.hdr_type)) if snap.hdr_type else "SDR"

    def _hdr_color(self, snap) -> QColor:
        val = self._hdr_text(snap)
        if "DV" in val or "Dolby" in val:
            return _COLOR_HDR_DV
        if "HDR10" in val:
            return _COLOR_HDR_HDR10
        return _COLOR_HDR_SDR
