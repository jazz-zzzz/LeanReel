"""主窗口测试"""
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

_app = None

def get_app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app

def test_main_window_creates():
    from leanreel.gui.main_window import MainWindow
    app = get_app()
    win = MainWindow()
    assert win.windowTitle() == "LeanReel"
    win.close()

def test_main_window_has_menu_bar():
    from leanreel.gui.main_window import MainWindow
    app = get_app()
    win = MainWindow()
    menu = win.menuBar()
    assert menu is not None
    win.close()

def test_main_window_has_status_bar():
    from leanreel.gui.main_window import MainWindow
    app = get_app()
    win = MainWindow()
    status = win.statusBar()
    assert status is not None
    win.close()


def test_file_list_displays_codec_strategy_and_estimated_savings():
    from leanreel.core.strategy import Strategy
    from leanreel.data.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    snap = FileSnapshot(
        relative_path="movie.mkv",
        file_name="movie.mkv",
        size_bytes=10 * 1024**3,
        video_codec="h264",
        hdr_type=HDRType.HDR10P,
    )

    panel.populate([snap], {"movie.mkv": strategy})

    assert panel.table.item(0, 2).text() == "h264"
    assert panel.table.item(0, 3).text() == "HDR10+"
    assert panel.table.item(0, 4).text() == "均衡压缩"
    assert "3.5-5.0 GB" in panel.table.item(0, 5).text()
    assert "35-50%" in panel.table.item(0, 5).text()
    panel.close()


def test_file_list_shows_unknown_when_codec_missing():
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(
        relative_path="clip.mkv",
        file_name="clip.mkv",
        size_bytes=1024,
        video_codec="",
    )

    panel.populate([snap], {"clip.mkv": "未匹配"})

    assert panel.table.item(0, 2).text() == "未识别"
    panel.close()


def test_file_list_columns_are_user_resizable():
    from PySide6.QtWidgets import QHeaderView
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()

    header = panel.table.horizontalHeader()

    assert header.sectionResizeMode(0) == QHeaderView.Interactive
    assert header.sectionResizeMode(4) == QHeaderView.Interactive
    panel.close()


def test_strategy_combo_has_enough_width_to_avoid_text_overlap():
    from leanreel.core.strategy import Strategy
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    snap = FileSnapshot(relative_path="movie.mkv", file_name="movie.mkv", size_bytes=10 * 1024**3)

    panel.populate([snap], {"movie.mkv": strategy}, strategies=[strategy])
    combo = panel.table.cellWidget(0, 4)

    assert combo.minimumWidth() >= 140
    assert panel.table.columnWidth(4) >= 160
    panel.close()


def test_file_list_can_switch_between_flat_and_tree_modes():
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(relative_path="Season 1/a.mkv", file_name="a.mkv", size_bytes=1024),
        FileSnapshot(relative_path="Season 2/b.mkv", file_name="b.mkv", size_bytes=1024),
    ]

    panel.populate(snapshots, {})

    assert panel.current_view_mode == "flat"
    assert panel.stack.currentWidget() is panel.table
    assert not panel.table.isHidden()
    assert panel.tree.isHidden()

    panel.set_view_mode("tree")

    assert panel.current_view_mode == "tree"
    assert panel.stack.currentWidget() is panel.tree
    assert not panel.tree.isHidden()
    assert panel.table.isHidden()
    assert panel.tree.topLevelItemCount() == 2
    assert panel.tree.topLevelItem(0).childCount() == 1
    panel.close()


def test_file_list_sorts_size_and_estimated_savings_numerically():
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(relative_path="large.mkv", file_name="large.mkv", size_bytes=10 * 1024**3),
        FileSnapshot(relative_path="small.mkv", file_name="small.mkv", size_bytes=1 * 1024**3),
        FileSnapshot(relative_path="medium.mkv", file_name="medium.mkv", size_bytes=2 * 1024**3),
    ]
    matches = {
        "large.mkv": {"strategy_name": "A", "estimated_min_bytes": 4 * 1024**3, "estimated_max_bytes": 5 * 1024**3},
        "small.mkv": {"strategy_name": "B", "estimated_min_bytes": 200 * 1024**2, "estimated_max_bytes": 300 * 1024**2},
        "medium.mkv": {"strategy_name": "C", "estimated_min_bytes": 1 * 1024**3, "estimated_max_bytes": 2 * 1024**3},
    }

    panel.populate(snapshots, matches)

    panel.table.sortItems(1, Qt.AscendingOrder)
    assert [panel.table.item(row, 0).text() for row in range(3)] == [
        "small.mkv",
        "medium.mkv",
        "large.mkv",
    ]

    panel.table.sortItems(5, Qt.DescendingOrder)
    assert [panel.table.item(row, 0).text() for row in range(3)] == [
        "large.mkv",
        "medium.mkv",
        "small.mkv",
    ]
    panel.close()


def test_library_panel_delete_and_remove_actions_emit_signals():
    from leanreel.gui.library_panel import LibraryPanel

    app = get_app()
    panel = LibraryPanel()
    deleted_libraries = []
    removed_folders = []
    panel.library_deleted.connect(deleted_libraries.append)
    panel.folder_removed.connect(removed_folders.append)

    panel._delete_library(7)
    panel._remove_folder(11)

    assert deleted_libraries == [7]
    assert removed_folders == [11]
    panel.close()


def test_file_list_allows_per_row_strategy_override_and_updates_savings():
    from leanreel.core.strategy import Strategy
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    balanced = Strategy(name="均衡压缩", estimated_savings="35-50%")
    light = Strategy(name="轻量压缩", estimated_savings="10%")
    snap = FileSnapshot(
        relative_path="movie.mkv",
        file_name="movie.mkv",
        size_bytes=10 * 1024**3,
    )

    panel.populate([snap], {"movie.mkv": balanced}, strategies=[balanced, light])
    changes = []
    panel.strategy_override_changed.connect(lambda rel_path, strategy: changes.append((rel_path, strategy)))

    combo = panel.table.cellWidget(0, 4)
    assert combo is not None
    assert combo.currentText() == "均衡压缩"

    combo.setCurrentText("轻量压缩")

    assert changes == [("movie.mkv", "轻量压缩")]
    assert combo.currentText() == "轻量压缩"
    assert "1.0-1.0 GB" in panel.table.item(0, 5).text()
    assert "10%" in panel.table.item(0, 5).text()
    panel.close()


def test_file_list_custom_strategy_option_emits_request_signal():
    from leanreel.core.strategy import Strategy
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    snap = FileSnapshot(relative_path="movie.mkv", file_name="movie.mkv", size_bytes=10 * 1024**3)

    panel.populate([snap], {"movie.mkv": strategy}, strategies=[strategy])
    requests = []
    panel.custom_strategy_requested.connect(requests.append)

    combo = panel.table.cellWidget(0, 4)
    assert "自定义" in [combo.itemText(i) for i in range(combo.count())]

    combo.setCurrentText("自定义")

    assert requests == ["movie.mkv"]
    assert combo.currentText() == "自定义"
    panel.close()


def test_file_list_can_update_row_with_custom_strategy():
    from leanreel.core.strategy import Strategy
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(relative_path="movie.mkv", file_name="movie.mkv", size_bytes=10 * 1024**3)
    panel.populate([snap], {"movie.mkv": "未匹配"})

    custom = Strategy(name="自定义", estimated_savings="50-70%")
    panel.apply_strategy_to_row("movie.mkv", custom)

    assert panel.table.item(0, 4).text() == "自定义"
    assert "5.0-7.0 GB" in panel.table.item(0, 5).text()
    panel.close()


def test_strategy_panel_custom_controls_emit_recomputed_strategy():
    from leanreel.gui.strategy_panel import StrategyPanel

    app = get_app()
    panel = StrategyPanel()
    changes = []
    panel.custom_strategy_changed.connect(changes.append)

    panel.show_custom_strategy()
    panel.custom_crf_spin.setValue(22)

    assert panel.custom_group.isVisibleTo(panel)
    assert changes
    assert changes[-1].name == "自定义"
    assert changes[-1].video.crf == 22
    assert changes[-1].estimated_savings == "50-70%"
    assert panel.current_strategy.name == "自定义"
    panel.close()
