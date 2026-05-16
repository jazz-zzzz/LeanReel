"""FlatAdapter 测试"""
import pytest
from PySide6.QtWidgets import QTableWidget
from PySide6.QtCore import Qt

from leanreel.data.file_store import FileTableStore, FileRow
from leanreel.data.models import FileSnapshot, HDRType
from leanreel.gui.file_list import MatchResult, FileDecisionDisplay


def _text(table, row, col):
    m = table.model()
    return str(m.data(m.index(row, col), Qt.DisplayRole) or "")


def _check(table, row, col):
    m = table.model()
    val = m.data(m.index(row, col), Qt.CheckStateRole)
    if isinstance(val, int):
        return Qt.CheckState(val)
    return val


def _flags(table, row, col):
    m = table.model()
    return m.flags(m.index(row, col))


def _snap(library_folder_id=7, relative_path="a.mkv", file_name="a.mkv",
          size_bytes=1024, video_codec="h264", probe_ok=True):
    return FileSnapshot(
        library_folder_id=library_folder_id, relative_path=relative_path,
        file_name=file_name, size_bytes=size_bytes,
        video_codec=video_codec, hdr_type=HDRType.SDR, probe_ok=probe_ok,
    )


def _row(snap, decision=None):
    row = FileRow(snap=snap, decision=decision)
    return row


def _make_decision(status_key="processable", strategy_text="均衡压缩",
                   result_text="35-50%", result_sort=50, processable=True):
    return FileDecisionDisplay(
        status_key=status_key, strategy_text=strategy_text,
        result_text=result_text, result_sort=result_sort,
        processable=processable, tooltip=strategy_text,
    )


def test_flat_adapter_rebuild_populates_table(qtbot):
    from leanreel.gui.adapters.flat_adapter import FlatAdapter

    store = FileTableStore()
    table = QTableWidget()
    table.setColumnCount(7)
    adapter = FlatAdapter(store, table)

    snap = _snap(video_codec="h264", size_bytes=1024)
    row = _row(snap, decision=_make_decision())
    store.rebuild([row])

    assert table.model().rowCount() == 1
    assert _text(table, 0, 1) == "a.mkv"
    assert "h264" in _text(table, 0, 3)


def test_flat_adapter_rebuild_empty_clears_table(qtbot):
    from leanreel.gui.adapters.flat_adapter import FlatAdapter

    store = FileTableStore()
    table = QTableWidget()
    table.setColumnCount(7)
    adapter = FlatAdapter(store, table)

    store.rebuild([_row(_snap())])
    assert table.model().rowCount() == 1
    store.rebuild([])
    assert table.model().rowCount() == 0


def test_flat_adapter_row_update(qtbot):
    from leanreel.gui.adapters.flat_adapter import FlatAdapter

    store = FileTableStore()
    table = QTableWidget()
    table.setColumnCount(7)
    adapter = FlatAdapter(store, table)

    snap = _snap(video_codec="", size_bytes=0, probe_ok=False)
    store.rebuild([_row(snap, decision=_make_decision(status_key="probe_failed", result_text="无法估算", result_sort=-3, processable=False))])

    new_snap = _snap(video_codec="h264", size_bytes=2048, probe_ok=True)
    store.update_row((7, "a.mkv"), new_snap)

    assert "h264" in _text(table, 0, 3)


def test_flat_adapter_checkbox_sync(qtbot):
    from leanreel.gui.adapters.flat_adapter import FlatAdapter

    store = FileTableStore()
    table = QTableWidget()
    table.setColumnCount(7)
    adapter = FlatAdapter(store, table)

    snap = _snap(video_codec="h264")
    row = _row(snap, decision=_make_decision())
    store.rebuild([row])

    assert _check(table, 0, 0) == Qt.Unchecked
    store.set_checked((7, "a.mkv"), True)
    assert _check(table, 0, 0) == Qt.Checked


def test_flat_adapter_protected_row_not_checkable(qtbot):
    from leanreel.gui.adapters.flat_adapter import FlatAdapter

    store = FileTableStore()
    table = QTableWidget()
    table.setColumnCount(7)
    adapter = FlatAdapter(store, table)

    snap = _snap(video_codec="hevc")
    row = _row(snap, decision=_make_decision(status_key="protected", processable=False, strategy_text="跳过：HEVC"))
    store.rebuild([row])

    assert not (_flags(table, 0, 0) & Qt.ItemIsEnabled)
