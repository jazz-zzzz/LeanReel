"""FileTableModel — QAbstractTableModel 适配 FileTableStore，零拷贝"""
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor

_COLUMNS = 7
_COL_CHECK = 0
_COL_NAME = 1
_COL_SIZE = 2
_COL_CODEC = 3
_COL_HDR = 4
_COL_STRATEGY = 5
_COL_RESULT = 6


class FileTableModel(QAbstractTableModel):
    """将 FileTableStore 适配为 QTableView 的数据模型。

    不持有数据副本 — 所有数据直接从 Store 读取。
    """

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store
        self._sort_col = -1
        self._sort_order = Qt.AscendingOrder
        self._visible_rows: list[int] = []  # store index → visual row
        self._filter_key = "all"
        self._edit_values: dict[tuple[int, int], str] = {}  # pending edit values

        store.rows_rebuilt.connect(self._on_rebuilt)
        store.row_updated.connect(self._on_row_updated)
        store.checked_changed.connect(self._on_checked_changed)

    # ── 必须实现的虚函数 ──

    def rowCount(self, parent=QModelIndex()):
        return len(self._visible_rows)

    def columnCount(self, parent=QModelIndex()):
        return _COLUMNS

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        store_idx = self._to_store_index(index.row())
        row = self._store.row_at(store_idx)
        if row is None:
            return None
        col = index.column()
        # 策略列正在编辑中 → 返回编辑值
        if col == _COL_STRATEGY and role in (Qt.DisplayRole, Qt.EditRole):
            ev = self._edit_values.get((index.row(), index.column()))
            if ev is not None:
                return ev
        d = row.decision
        snap = row.snap

        if role == Qt.DisplayRole:
            return self._display_text(col, snap, d)
        if role == Qt.UserRole:
            if col in (_COL_CHECK, _COL_NAME):
                return row.key  # 勾选和文件名列存储 key 供 selection/checkbox lookup
            return self._sort_value(col, snap, d)
        if role == Qt.CheckStateRole and col == _COL_CHECK:
            return Qt.Checked if self._store.is_checked(row.key) else Qt.Unchecked
        if role == Qt.ForegroundRole:
            return self._foreground(col, snap, d)
        if role == Qt.ToolTipRole:
            return self._tooltip(col, snap, d)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.column() == _COL_CHECK:
            store_idx = self._to_store_index(index.row())
            row = self._store.row_at(store_idx)
            if row:
                self._store.set_checked(row.key, value == Qt.Checked)
                return True
        # 策略列 EditRole → 存储编辑值供 dataChanged handler 读取
        if role == Qt.EditRole and index.column() == _COL_STRATEGY:
            key = (index.row(), index.column())
            if self._edit_values.get(key) == value:
                return True
            self._edit_values[key] = value
            self.dataChanged.emit(index, index, [Qt.EditRole])
            return True
        return False

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == _COL_CHECK:
            flags |= Qt.ItemIsUserCheckable
            store_idx = self._to_store_index(index.row())
            row = self._store.row_at(store_idx)
            if row and row.decision and not row.decision.processable:
                flags &= ~Qt.ItemIsEnabled
        return flags

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return ["", "文件名", "体积", "编码信息", "HDR", "处理策略", "预计结果"][section]
        return None

    # ── Store 信号响应 ──

    def _on_rebuilt(self):
        self.layoutAboutToBeChanged.emit()
        self._rebuild_visible()
        self.layoutChanged.emit()

    def _on_row_updated(self, idx: int, row):
        if self._filter_key != "all" or self._sort_col >= 0:
            self.layoutAboutToBeChanged.emit()
            self._rebuild_visible()
            self.layoutChanged.emit()
            return
        vis_row = self._to_visual(idx)
        if vis_row >= 0:
            self.dataChanged.emit(
                self.index(vis_row, 0),
                self.index(vis_row, _COLUMNS - 1),
            )

    def _on_checked_changed(self):
        if self._filter_key == "checked":
            self.layoutAboutToBeChanged.emit()
            self._rebuild_visible()
            self.layoutChanged.emit()
            return
        if self.rowCount() == 0:
            return
        # 只刷新复选框列
        top_left = self.index(0, _COL_CHECK)
        bottom_right = self.index(self.rowCount() - 1, _COL_CHECK)
        self.dataChanged.emit(top_left, bottom_right)

    # ── 排序 ──

    def sort(self, column, order=Qt.AscendingOrder):
        """用户点击列标题时 QTableView 调用此方法"""
        if column < 0 or column >= _COLUMNS:
            return
        self._sort_col = column
        self._sort_order = order
        key_func = self._sort_key(column)
        reverse = (order == Qt.DescendingOrder)
        self.layoutAboutToBeChanged.emit()
        self._visible_rows.sort(key=key_func, reverse=reverse)
        self.layoutChanged.emit()

    def _sort_key(self, column):
        def key(store_idx):
            row = self._store.row_at(store_idx)
            if row is None:
                return ""
            snap = row.snap
            d = row.decision
            if column == 0:
                return ""  # no sort for checkbox
            if column == 1:
                return snap.file_name.lower()
            if column == 2:
                return snap.size_bytes or 0
            if column == 3:
                return snap.video_codec or ""
            if column == 4:
                return getattr(snap.hdr_type, "value", "SDR") if snap.hdr_type else "SDR"
            if column == 5:
                return d.strategy_text if d else ""
            if column == 6:
                return d.result_sort if d else -1
            return ""
        return key

    # ── 内部 ──

    def _to_store_index(self, visual_row):
        return self._visible_rows[visual_row]

    def _to_visual(self, store_idx):
        try:
            return self._visible_rows.index(store_idx)
        except ValueError:
            return -1

    def _display_text(self, col, snap, d):
        from leanreel.gui.utils import _format_bytes
        if col == _COL_NAME:
            return snap.file_name
        if col == _COL_SIZE:
            return _format_bytes(snap.size_bytes)
        if col == _COL_CODEC:
            return self._format_codec_text(snap)
        if col == _COL_HDR:
            return getattr(snap.hdr_type, "value", str(snap.hdr_type)) if snap.hdr_type else "SDR"
        if col == _COL_STRATEGY:
            return d.strategy_text if d else "—"
        if col == _COL_RESULT:
            return d.result_text if d else "—"
        return ""

    def _format_codec_text(self, snap):
        codec = snap.video_codec
        if not codec:
            if snap.probe_ok is False and snap.probe_error:
                return "探测失败"
            if snap.probe_ok is False:
                return "探测中..."
            return "未识别"
        res = f" {snap.video_width}x{snap.video_height}" if (snap.video_width and snap.video_height) else ""
        return f"{codec}{res}"

    def _sort_value(self, col, snap, d):
        if col == _COL_SIZE:
            return snap.size_bytes
        if col == _COL_RESULT:
            return d.result_sort if d else -1
        return None

    def _foreground(self, col, snap, d):
        from leanreel.gui.file_list import (
            _COLOR_CODEC_OK, _COLOR_CODEC_MISSING, _COLOR_PROBE_FAILED,
            _COLOR_HDR_DV, _COLOR_HDR_HDR10, _COLOR_HDR_SDR,
        )
        if col == _COL_CODEC:
            if snap.video_codec:
                return _COLOR_CODEC_OK
            if d and d.status_key == "probe_failed":
                return _COLOR_PROBE_FAILED
            return _COLOR_CODEC_MISSING
        if col == _COL_HDR:
            hdr_val = getattr(snap.hdr_type, "value", "SDR") if snap.hdr_type else "SDR"
            if "DV" in hdr_val or "Dolby" in hdr_val:
                return _COLOR_HDR_DV
            if "HDR10" in hdr_val:
                return _COLOR_HDR_HDR10
            return _COLOR_HDR_SDR
        if col == _COL_STRATEGY:
            if d and d.status_key == "protected":
                return _COLOR_HDR_DV
            if d and d.status_key == "probe_failed":
                return _COLOR_PROBE_FAILED
        return None

    def _tooltip(self, col, snap, d):
        if col == _COL_CHECK:
            return d.tooltip if d and not (d and d.processable) else ""
        if col == _COL_STRATEGY:
            return d.tooltip if d else ""
        if col == _COL_CODEC and d and d.status_key == "probe_failed":
            return snap.probe_error or ""
        return ""

    # ── 过滤 ──

    def _rebuild_visible(self):
        self._visible_rows = [
            i for i in range(self._store.count())
            if self._is_visible(i)
        ]
        if self._sort_col >= 0:
            reverse = (self._sort_order == Qt.DescendingOrder)
            self._visible_rows.sort(key=self._sort_key(self._sort_col), reverse=reverse)

    def set_filter(self, filter_key: str):
        self._filter_key = filter_key
        self.layoutAboutToBeChanged.emit()
        self._rebuild_visible()
        self.layoutChanged.emit()

    def _is_visible(self, store_idx):
        if self._filter_key == "all":
            return True
        row = self._store.row_at(store_idx)
        d = row.decision if row else None
        if d is None:
            return self._filter_key != "checked"
        if self._filter_key == "processable":
            return d.processable
        if self._filter_key == "protected":
            return d.status_key == "protected"
        if self._filter_key == "probe_failed":
            return d.status_key == "probe_failed"
        if self._filter_key == "checked":
            return self._store.is_checked(row.key)
        return True
