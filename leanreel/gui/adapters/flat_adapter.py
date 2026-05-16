"""平铺表格适配器 — 连接 FileTableStore 到 QTableWidget"""
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QComboBox

from leanreel.gui.utils import _format_bytes
from leanreel.gui.file_list import (
    SortableTableWidgetItem, _COLOR_CODEC_OK, _COLOR_CODEC_MISSING,
    _COLOR_PROBE_FAILED, _COLOR_HDR_DV,
)


class FlatAdapter(QObject):
    """监听 FileTableStore 信号，自动同步 QTableWidget。"""

    def __init__(self, store, table: QTableWidget, strategies=None):
        super().__init__()
        self._store = store
        self._table = table
        self._row_key: list[tuple] = []
        self._combo_created = False
        store.rows_rebuilt.connect(self._on_rebuild)
        store.row_updated.connect(self._on_row_updated)
        store.checked_changed.connect(self._on_checked_changed)

    # ── rebuild ──

    def _on_rebuild(self):
        store = self._store
        self._table.setSortingEnabled(False)
        self._table.blockSignals(True)
        self._table.clearContents()
        self._table.setRowCount(store.count())
        self._row_key = []
        self._combo_created = False
        for i in range(store.count()):
            row = store.row_at(i)
            self._row_key.append(row.key)
            self._render_row(i, row)
        self._table.blockSignals(False)

    def _render_row(self, table_row: int, row):
        key = row.key
        d = row.decision
        snap = row.snap
        # 列0: 勾选框
        check = QTableWidgetItem()
        check.setData(Qt.UserRole, key)
        if d and d.processable:
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        else:
            check.setFlags(Qt.ItemIsUserCheckable)
            check.setToolTip(d.tooltip if d else "")
        check.setCheckState(Qt.Checked if self._store.is_checked(key) else Qt.Unchecked)
        self._table.setItem(table_row, 0, check)
        # 列1: 文件名
        name = QTableWidgetItem(snap.file_name)
        name.setData(Qt.UserRole, key)
        self._table.setItem(table_row, 1, name)
        # 列2: 体积
        self._table.setItem(table_row, 2,
            SortableTableWidgetItem(_format_bytes(snap.size_bytes), snap.size_bytes))
        # 列3: 编码
        codec_text = self._format_codec(snap)
        codec = QTableWidgetItem(codec_text)
        if snap.video_codec:
            codec.setForeground(_COLOR_CODEC_OK)
        elif d and d.status_key == "probe_failed":
            codec.setForeground(_COLOR_PROBE_FAILED)
            codec.setToolTip(snap.probe_error or "")
        else:
            codec.setForeground(_COLOR_CODEC_MISSING)
        self._table.setItem(table_row, 3, codec)
        # 列4: HDR
        hdr_text = getattr(snap.hdr_type, "value", str(snap.hdr_type)) if snap.hdr_type else "SDR"
        hdr = QTableWidgetItem(hdr_text)
        from leanreel.gui.file_list import _COLOR_HDR_HDR10, _COLOR_HDR_SDR
        hdr_val = hdr_text
        if "DV" in hdr_val or "Dolby" in hdr_val:
            hdr.setForeground(_COLOR_HDR_DV)
        elif "HDR10" in hdr_val:
            hdr.setForeground(_COLOR_HDR_HDR10)
        else:
            hdr.setForeground(_COLOR_HDR_SDR)
        self._table.setItem(table_row, 4, hdr)
        # 列5: 策略（先文本，QComboBox 延后）
        strategy_text = d.strategy_text if d else "—"
        strategy_item = QTableWidgetItem(strategy_text)
        strategy_item.setToolTip(d.tooltip if d else "")
        if d and d.status_key == "protected":
            strategy_item.setForeground(_COLOR_HDR_DV)
        elif d and d.status_key == "probe_failed":
            strategy_item.setForeground(_COLOR_PROBE_FAILED)
        self._table.setItem(table_row, 5, strategy_item)
        # 列6: 预计结果
        self._table.setItem(table_row, 6,
            SortableTableWidgetItem(d.result_text if d else "—", d.result_sort if d else -1))

    def _format_codec(self, snap) -> str:
        codec = snap.video_codec
        if not codec:
            if snap.probe_ok is False and snap.probe_error:
                return "探测失败"
            if snap.probe_ok is False:
                return "探测中..."
            return "未识别"
        res = snap.video_width or snap.video_height
        res_str = f" {snap.video_width}x{snap.video_height}" if (snap.video_width and snap.video_height) else ""
        return f"{codec}{res_str}"

    # ── update ──

    def _on_row_updated(self, idx: int, row):
        table_row = self._find_table_row(row.key)
        if table_row is not None:
            self._render_row(table_row, row)

    def _find_table_row(self, key) -> int | None:
        """扫描表格实际行查找匹配的 key（排序后行号可能与插入顺序不同）。"""
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 1)  # 列 1 的文件名存储了 key
            if item is not None and item.data(Qt.UserRole) == key:
                return i
        return None

    # ── checked ──

    def _on_checked_changed(self):
        """同步所有勾选框状态（按视觉行号扫描，兼容排序后的表格）。"""
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 0)
            if item is not None and item.flags() & Qt.ItemIsEnabled:
                key = item.data(Qt.UserRole)
                if isinstance(key, tuple) and len(key) == 2:
                    state = Qt.Checked if self._store.is_checked(key) else Qt.Unchecked
                    if item.checkState() != state:
                        item.setCheckState(state)

    def create_combo_cells(self, combo_factory):
        """在全部行渲染后异步创建 QComboBox（接受工厂函数）。"""
        if self._combo_created:
            return
        for i in range(self._table.rowCount()):
            row = self._store.row_at(i)
            if row is None or row.decision is None or not row.decision.processable:
                continue
            name_item = self._table.item(i, 1)
            if name_item is None:
                continue
            key = name_item.data(Qt.UserRole)
            if isinstance(key, tuple) and len(key) == 2:
                rel = key[1]
            else:
                rel = str(key) if key else ""
            if not rel:
                continue
            old = self._table.item(i, 5)
            current_text = old.text() if old else ""
            combo = combo_factory(rel, current_text)
            self._table.setCellWidget(i, 5, combo)
        self._combo_created = True
