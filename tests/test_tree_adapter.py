"""TreeAdapter 测试"""
import pytest
from PySide6.QtWidgets import QTreeWidget
from PySide6.QtCore import Qt

from leanreel.state.file_store import FileTableStore
from leanreel.domain.models import FileRow
from leanreel.domain.models import FileSnapshot, HDRType
from leanreel.gui.file_list import MatchResult, FileDecisionDisplay


def _snap(library_folder_id=7, relative_path="Season 1/E01.mkv", file_name="E01.mkv",
          size_bytes=1024, video_codec="h264", probe_ok=True):
    return FileSnapshot(
        library_folder_id=library_folder_id, relative_path=relative_path,
        file_name=file_name, size_bytes=size_bytes,
        video_codec=video_codec, hdr_type=HDRType.SDR, probe_ok=probe_ok,
    )


def _row(snap, decision=None):
    return FileRow(snap=snap, decision=decision)


def _make_decision(status_key="processable", strategy_text="均衡",
                   result_text="50%", result_sort=50, processable=True):
    return FileDecisionDisplay(
        status_key=status_key, strategy_text=strategy_text,
        result_text=result_text, result_sort=result_sort,
        processable=processable, tooltip=strategy_text,
    )


def test_tree_adapter_rebuild_creates_folders(qtbot):
    from leanreel.gui.adapters.tree_adapter import TreeAdapter

    store = FileTableStore()
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(6)

    adapter = TreeAdapter(store, tree)
    s1 = _snap(relative_path="S1/a.mkv", file_name="a.mkv")
    s2 = _snap(relative_path="S1/b.mkv", file_name="b.mkv")
    s3 = _snap(relative_path="S2/c.mkv", file_name="c.mkv")
    store.rebuild([_row(s, _make_decision()) for s in [s1, s2, s3]])

    assert tree.topLevelItemCount() == 2
    folder1 = tree.topLevelItem(0)
    assert folder1.childCount() == 2


def test_tree_adapter_folder_total_size(qtbot):
    from leanreel.gui.adapters.tree_adapter import TreeAdapter

    store = FileTableStore()
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(6)
    adapter = TreeAdapter(store, tree)

    s1 = _snap(relative_path="S1/a.mkv", size_bytes=1000)
    s2 = _snap(relative_path="S1/b.mkv", size_bytes=2000)
    store.rebuild([_row(s, _make_decision()) for s in [s1, s2]])

    folder = tree.topLevelItem(0)
    assert "KB" in folder.text(1)


def test_tree_adapter_row_update(qtbot):
    from leanreel.gui.adapters.tree_adapter import TreeAdapter

    store = FileTableStore()
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(6)
    adapter = TreeAdapter(store, tree)

    snap = _snap(video_codec="", size_bytes=0, probe_ok=False)
    store.rebuild([_row(snap, _make_decision(status_key="probe_failed", processable=False))])

    new_snap = _snap(video_codec="h264", size_bytes=2048, probe_ok=True)
    store.update_row((7, "Season 1/E01.mkv"), new_snap)

    child = tree.topLevelItem(0).child(0)
    assert "h264" in child.text(2)


def test_tree_adapter_child_checkbox(qtbot):
    from leanreel.gui.adapters.tree_adapter import TreeAdapter

    store = FileTableStore()
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(6)
    adapter = TreeAdapter(store, tree)

    store.rebuild([_row(_snap(), _make_decision())])

    child = tree.topLevelItem(0).child(0)
    assert child.checkState(0) == Qt.Unchecked
    store.set_checked((7, "Season 1/E01.mkv"), True)
    assert child.checkState(0) == Qt.Checked