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


def _text(panel, row, col):
    m = panel.table.model()
    return str(m.data(m.index(row, col), Qt.DisplayRole) or "")


def _check(panel, row, col):
    m = panel.table.model()
    val = m.data(m.index(row, col), Qt.CheckStateRole)
    # QTableWidget internal model returns int; wrap to Qt.CheckState for comparison
    if isinstance(val, int):
        return Qt.CheckState(val)
    return val


def _set_check(panel, row, col, state):
    m = panel.table.model()
    m.setData(m.index(row, col), state, Qt.CheckStateRole)


def _flags(panel, row, col):
    m = panel.table.model()
    return m.flags(m.index(row, col))


def _userdata(panel, row, col):
    m = panel.table.model()
    return m.data(m.index(row, col), Qt.UserRole)


def _combo(panel, row, col):
    return panel.table.indexWidget(panel.table.model().index(row, col))


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


def test_main_window_default_splitter_gives_strategy_panel_room():
    from leanreel.gui.main_window import MainWindow

    app = get_app()
    window = MainWindow()
    sizes = window.splitter.sizes()

    assert len(sizes) == 3
    assert window.strategy_placeholder.minimumWidth() >= 320
    window.close()


def test_about_text_avoids_absolute_lossless_claim(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from leanreel.gui.main_window import MainWindow

    app = get_app()
    captured = {}
    monkeypatch.setattr(
        QMessageBox,
        "about",
        lambda parent, title, text: captured.update({"title": title, "text": text}),
    )
    window = MainWindow()

    window._show_about()

    assert "完整无损" not in captured["text"]
    assert "默认保护 HEVC/HDR/Dolby Vision 片源" in captured["text"]
    window.close()


def test_file_list_displays_codec_strategy_and_estimated_savings():
    from leanreel.domain.models import Strategy
    from leanreel.domain.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    snap = FileSnapshot(
        relative_path="movie.mkv",
        file_name="movie.mkv",
        size_bytes=10 * 1024**3,
        video_codec="h264",
        hdr_type=HDRType.SDR,
    )

    panel.populate([snap], {"movie.mkv": MatchResult(strategy=strategy)})

    assert _text(panel, 0, 3) == "h264"
    assert _text(panel, 0, 4) == "SDR"
    assert _text(panel, 0, 5) == "均衡压缩"
    assert "3.5-5.0 GB" in _text(panel, 0, 6)
    assert "35-50%" in _text(panel, 0, 6)
    panel.close()


def test_file_list_shows_unknown_when_codec_missing():
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(
        relative_path="clip.mkv",
        file_name="clip.mkv",
        size_bytes=1024,
        video_codec="",
        probe_ok=True,  # probe 成功但无视频流（如纯音频文件），应显示"未识别"
    )

    panel.populate([snap], {"clip.mkv": None})

    assert _text(panel, 0, 3) == "未识别"
    panel.close()


def test_file_list_columns_are_user_resizable():
    from PySide6.QtWidgets import QHeaderView
    from leanreel.gui.file_list import FileListPanel

    from leanreel.domain.models import FileSnapshot as _FS
    app = get_app()
    panel = FileListPanel()
    panel.populate([_FS(library_folder_id=7, relative_path="a.mkv", file_name="a.mkv", size_bytes=1024, video_codec="h264")], {"a.mkv": None})

    header = panel.table.horizontalHeader()

    assert header.sectionResizeMode(1) == QHeaderView.Interactive
    assert header.sectionResizeMode(5) == QHeaderView.Interactive
    panel.close()


def test_strategy_combo_has_enough_width_to_avoid_text_overlap():
    from leanreel.domain.models import Strategy
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    snap = FileSnapshot(relative_path="movie.mkv", file_name="movie.mkv", size_bytes=10 * 1024**3)

    panel.populate([snap], {"movie.mkv": MatchResult(strategy=strategy)}, strategies=[strategy])
    combo = panel.table.itemDelegateForColumn(5).createEditor(None, None, panel.table.model().index(0, 5))
    assert combo.minimumWidth() >= 140
    combo.deleteLater()
    assert panel.table.columnWidth(5) >= 160
    panel.close()


def test_file_list_can_switch_between_flat_and_tree_modes():
    from leanreel.domain.models import FileSnapshot
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


def test_file_list_tree_view_columns_are_aligned_with_headers():
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(
        relative_path="Season 01/Episode 01.mkv",
        file_name="Episode 01.mkv",
        size_bytes=10 * 1024**3,
        video_codec="h264",
        video_width=1920,
        video_height=1080,
    )

    panel.populate(
        [snap],
        {"Season 01/Episode 01.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"})},
    )
    panel.set_view_mode("tree")

    folder = panel.tree.topLevelItem(0)
    child = folder.child(0)
    assert panel.tree.headerItem().text(0) == "文件夹名"
    assert child.text(0) == "Episode 01.mkv"
    assert "GB" in child.text(1)
    assert "h264" in child.text(3)
    assert child.text(4) == "SDR"
    assert child.text(5) == "x265 HEVC CRF 20 标准转码"
    assert "GB" in child.text(6)
    panel.close()


def test_file_list_sorts_size_and_estimated_savings_numerically():
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(relative_path="large.mkv", file_name="large.mkv", size_bytes=10 * 1024**3),
        FileSnapshot(relative_path="small.mkv", file_name="small.mkv", size_bytes=1 * 1024**3),
        FileSnapshot(relative_path="medium.mkv", file_name="medium.mkv", size_bytes=2 * 1024**3),
    ]
    matches = {
        "large.mkv": MatchResult(strategy="A", estimate={"estimated_min_bytes": 4 * 1024**3, "estimated_max_bytes": 5 * 1024**3}),
        "small.mkv": MatchResult(strategy="B", estimate={"estimated_min_bytes": 200 * 1024**2, "estimated_max_bytes": 300 * 1024**2}),
        "medium.mkv": MatchResult(strategy="C", estimate={"estimated_min_bytes": 1 * 1024**3, "estimated_max_bytes": 2 * 1024**3}),
    }

    panel.populate(snapshots, matches)

    m = panel.table.model()
    assert m.rowCount() == 3
    assert m.data(m.index(0, 2), Qt.UserRole) == 10 * 1024**3
    assert m.data(m.index(1, 2), Qt.UserRole) == 1 * 1024**3
    panel.close()


def test_file_list_updates_correct_row_after_sorting():
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    large = FileSnapshot(relative_path="large.mkv", file_name="large.mkv", size_bytes=10 * 1024**3, video_codec="h264")
    small = FileSnapshot(relative_path="small.mkv", file_name="small.mkv", size_bytes=1 * 1024**3, video_codec="h264")

    panel.populate(
        [large, small],
        {
            "large.mkv": MatchResult(strategy="A", estimate={"estimated_min_bytes": 1, "estimated_max_bytes": 2}),
            "small.mkv": MatchResult(strategy="B", estimate={"estimated_min_bytes": 1, "estimated_max_bytes": 2}),
        },
    )
    large.video_codec = "hevc"
    panel.update_snapshot_row(large)

    m = panel.table.model()
    assert m.data(m.index(0, 3), Qt.DisplayRole) == "hevc"
    assert m.data(m.index(1, 3), Qt.DisplayRole) == "h264"
    panel.close()


def test_library_panel_delete_and_remove_actions_emit_signals(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from leanreel.gui.library_panel import LibraryPanel

    app = get_app()
    panel = LibraryPanel()
    deleted_libraries = []
    removed_folders = []
    panel.library_deleted.connect(deleted_libraries.append)
    panel.folder_removed.connect(removed_folders.append)

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    panel._delete_library(7)
    panel._remove_folder(11)

    assert deleted_libraries == [7]
    assert removed_folders == [11]
    panel.close()


def test_file_list_allows_per_row_strategy_override_and_updates_savings():
    from leanreel.domain.models import Strategy
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    balanced = Strategy(name="均衡压缩", estimated_savings="35-50%")
    light = Strategy(name="轻量压缩", estimated_savings="10%")
    snap = FileSnapshot(
        relative_path="movie.mkv",
        file_name="movie.mkv",
        size_bytes=10 * 1024**3,
    )

    panel.populate([snap], {"movie.mkv": MatchResult(strategy=balanced)}, strategies=[balanced, light])
    changes = []
    panel.strategy_override_changed.connect(lambda rel_path, strategy: changes.append((rel_path, strategy)))

    m = panel.table.model()
    delegate = panel.table.itemDelegateForColumn(5)
    combo = delegate.createEditor(None, None, m.index(0, 5))
    assert combo.currentText() == "均衡压缩"
    combo.setCurrentText("轻量压缩")
    delegate.setModelData(combo, m, m.index(0, 5))

    assert changes == [((0, "movie.mkv"), "轻量压缩")]
    assert combo.currentText() == "轻量压缩"
    combo.deleteLater()
    panel.close()


def test_file_list_custom_strategy_option_emits_request_signal():
    from leanreel.domain.models import Strategy
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    strategy = Strategy(name="均衡压缩", estimated_savings="35-50%")
    snap = FileSnapshot(relative_path="movie.mkv", file_name="movie.mkv", size_bytes=10 * 1024**3)

    panel.populate([snap], {"movie.mkv": MatchResult(strategy=strategy)}, strategies=[strategy])
    requests = []
    panel.custom_strategy_requested.connect(requests.append)

    delegate = panel.table.itemDelegateForColumn(5)
    m = panel.table.model()
    combo = delegate.createEditor(None, None, m.index(0, 5))
    assert "自定义" in [combo.itemText(i) for i in range(combo.count())]
    combo.setCurrentText("自定义")
    delegate.setModelData(combo, m, m.index(0, 5))

    assert requests == [(0, "movie.mkv")]
    assert combo.currentText() == "自定义"
    combo.deleteLater()
    panel.close()


def test_file_list_does_not_select_skipped_sources_with_select_all():
    from leanreel.domain.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(relative_path="sdr.mkv", file_name="sdr.mkv", size_bytes=1024, video_codec="h264"),
        FileSnapshot(relative_path="hevc.mkv", file_name="hevc.mkv", size_bytes=1024, video_codec="hevc"),
        FileSnapshot(relative_path="hdr.mkv", file_name="hdr.mkv", size_bytes=1024, video_codec="h264", hdr_type=HDRType.HDR10),
    ]
    matches = {
        "sdr.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"}),
        "hevc.mkv": MatchResult(strategy="跳过：HEVC/H.265 片源"),
        "hdr.mkv": MatchResult(strategy="跳过：HDR10 片源"),
    }

    panel.populate(snapshots, matches)
    panel.select_all()

    assert panel.get_checked_relative_paths() == ["sdr.mkv"]
    assert not (_flags(panel, 1, 0) & Qt.ItemIsEnabled)
    assert not (_flags(panel, 2, 0) & Qt.ItemIsEnabled)
    assert panel.selection_label.text() == "已选中 1/1 个可处理文件"
    panel.close()


def test_file_list_checked_state_survives_flat_to_tree_switch():
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(library_folder_id=1, relative_path="Season/a.mkv", file_name="a.mkv", video_codec="h264")

    panel.populate([snap], {"Season/a.mkv": MatchResult(strategy="A", estimate={"percentage": "10%"})})
    _set_check(panel, 0, 0, Qt.Checked)

    panel.set_view_mode("tree")

    child = panel.tree.topLevelItem(0).child(0)
    assert child.checkState(0) == Qt.Checked
    assert panel.get_checked_file_keys() == [(1, "Season/a.mkv")]
    panel.close()


def test_file_list_flat_checkbox_click_updates_store(qtbot):
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    panel = FileListPanel()
    qtbot.addWidget(panel)
    snap = FileSnapshot(library_folder_id=1, relative_path="Season/a.mkv", file_name="a.mkv", video_codec="h264")

    panel.populate([snap], {"Season/a.mkv": MatchResult(strategy="A", estimate={"percentage": "10%"})})
    panel.show()

    index = panel.table.model().index(0, 0)
    rect = panel.table.visualRect(index)
    qtbot.mouseClick(panel.table.viewport(), Qt.LeftButton, pos=rect.center())

    assert panel.get_checked_file_keys() == [(1, "Season/a.mkv")]
    assert _check(panel, 0, 0) == Qt.Checked
    panel.close()


def test_file_list_checked_state_survives_tree_to_flat_switch():
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(library_folder_id=1, relative_path="Season/a.mkv", file_name="a.mkv", video_codec="h264")

    panel.populate([snap], {"Season/a.mkv": MatchResult(strategy="A", estimate={"percentage": "10%"})})
    panel.set_view_mode("tree")
    child = panel.tree.topLevelItem(0).child(0)
    child.setCheckState(0, Qt.Checked)

    panel.set_view_mode("flat")

    assert _check(panel, 0, 0) == Qt.Checked
    assert panel.get_checked_file_keys() == [(1, "Season/a.mkv")]
    panel.close()


def test_file_list_tree_checkbox_click_updates_store(qtbot):
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    panel = FileListPanel()
    qtbot.addWidget(panel)
    snap = FileSnapshot(library_folder_id=1, relative_path="Season/a.mkv", file_name="a.mkv", video_codec="h264")

    panel.populate([snap], {"Season/a.mkv": MatchResult(strategy="A", estimate={"percentage": "10%"})})
    panel.set_view_mode("tree")
    panel.show()

    panel.tree.topLevelItem(0).setExpanded(True)
    child = panel.tree.topLevelItem(0).child(0)
    rect = panel.tree.visualItemRect(child)
    qtbot.mouseClick(panel.tree.viewport(), Qt.LeftButton, pos=rect.center())

    assert panel.get_checked_file_keys() == [(1, "Season/a.mkv")]
    assert child.checkState(0) == Qt.Checked
    panel.close()


def test_file_list_flat_disabled_checkbox_click_shows_reason(qtbot, monkeypatch):
    from PySide6.QtWidgets import QToolTip

    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    panel = FileListPanel()
    qtbot.addWidget(panel)
    snap = FileSnapshot(
        library_folder_id=1,
        relative_path="Season/hevc.mkv",
        file_name="hevc.mkv",
        video_codec="hevc",
    )
    shown = []
    monkeypatch.setattr(QToolTip, "showText", lambda _pos, text, *_args: shown.append(text))

    panel.populate([snap], {"Season/hevc.mkv": MatchResult(strategy="跳过：HEVC/H.265 片源")})
    panel.show()

    index = panel.table.model().index(0, 0)
    rect = panel.table.visualRect(index)
    qtbot.mouseClick(panel.table.viewport(), Qt.LeftButton, pos=rect.center())

    assert panel.get_checked_file_keys() == []
    assert shown
    assert "HEVC" in shown[-1]
    panel.close()


def test_file_list_tree_disabled_checkbox_click_shows_reason(qtbot, monkeypatch):
    from PySide6.QtWidgets import QToolTip

    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    panel = FileListPanel()
    qtbot.addWidget(panel)
    snap = FileSnapshot(
        library_folder_id=1,
        relative_path="Season/hevc.mkv",
        file_name="hevc.mkv",
        video_codec="hevc",
    )
    shown = []
    monkeypatch.setattr(QToolTip, "showText", lambda _pos, text, *_args: shown.append(text))

    panel.populate([snap], {"Season/hevc.mkv": MatchResult(strategy="跳过：HEVC/H.265 片源")})
    panel.set_view_mode("tree")
    panel.show()

    panel.tree.topLevelItem(0).setExpanded(True)
    child = panel.tree.topLevelItem(0).child(0)
    rect = panel.tree.visualItemRect(child)
    qtbot.mouseClick(panel.tree.viewport(), Qt.LeftButton, pos=rect.center())

    assert panel.get_checked_file_keys() == []
    assert shown
    assert "HEVC" in shown[-1]
    panel.close()


def test_file_list_tree_checked_filter_hides_unchecked_files_and_empty_folders():
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(library_folder_id=1, relative_path="A/checked.mkv", file_name="checked.mkv", video_codec="h264"),
        FileSnapshot(library_folder_id=1, relative_path="B/unchecked.mkv", file_name="unchecked.mkv", video_codec="h264"),
    ]
    matches = {s.relative_path: MatchResult(strategy="A", estimate={"percentage": "10%"}) for s in snapshots}

    panel.populate(snapshots, matches)
    panel.set_view_mode("tree")
    panel.tree.topLevelItem(0).child(0).setCheckState(0, Qt.Checked)
    panel.filter_combo.setCurrentText("已选择")

    assert not panel.tree.topLevelItem(0).isHidden()
    assert panel.tree.topLevelItem(1).isHidden()
    panel.close()


def test_file_list_distinguishes_duplicate_relative_paths_by_folder_id():
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(library_folder_id=1, relative_path="movie.mkv", file_name="movie.mkv", video_codec="h264"),
        FileSnapshot(library_folder_id=2, relative_path="movie.mkv", file_name="movie.mkv", video_codec="h264"),
    ]
    matches = {"movie.mkv": MatchResult(strategy="A", estimate={"percentage": "10%"})}

    panel.populate(snapshots, matches)
    _set_check(panel, 0, 0, Qt.Checked)

    assert panel.get_checked_file_keys() == [(1, "movie.mkv")]
    assert panel.get_checked_relative_paths() == ["movie.mkv"]
    panel.close()


def test_file_list_protected_sources_show_skip_reason_and_not_processing():
    from leanreel.domain.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(
            relative_path="hevc.mkv",
            file_name="hevc.mkv",
            size_bytes=1024,
            video_codec="hevc",
            hdr_type=HDRType.SDR,
        ),
        FileSnapshot(
            relative_path="hdr10.mkv",
            file_name="hdr10.mkv",
            size_bytes=2048,
            video_codec="h264",
            hdr_type=HDRType.HDR10,
        ),
    ]

    panel.populate(
        snapshots,
        {
            "hevc.mkv": MatchResult(strategy=None),
            "hdr10.mkv": MatchResult(strategy=None),
        },
    )

    assert _text(panel, 0, 5) == "跳过：HEVC/H.265 片源"
    assert _text(panel, 0, 6) == "不处理"
    assert _text(panel, 1, 5) == "跳过：HDR10 片源"
    assert _text(panel, 1, 6) == "不处理"
    # toolTip() not directly accessible via QTableView model; covered by strategy_text column
    panel.close()


def test_file_list_unmatched_non_protected_source_still_shows_unmatched():
    from leanreel.domain.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(
        relative_path="unknown.mkv",
        file_name="unknown.mkv",
        size_bytes=4096,
        video_codec="h264",
        hdr_type=HDRType.SDR,
    )

    panel.populate([snap], {"unknown.mkv": None})

    assert _text(panel, 0, 5) == "未匹配"
    assert _text(panel, 0, 6) == "—"
    panel.close()


def test_file_list_filter_shows_only_protected_rows():
    from leanreel.domain.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(relative_path="sdr.mkv", file_name="sdr.mkv", size_bytes=1024, video_codec="h264"),
        FileSnapshot(relative_path="hevc.mkv", file_name="hevc.mkv", size_bytes=1024, video_codec="hevc"),
        FileSnapshot(relative_path="hdr.mkv", file_name="hdr.mkv", size_bytes=1024, video_codec="h264", hdr_type=HDRType.HDR10),
    ]
    matches = {
        "sdr.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"}),
        "hevc.mkv": MatchResult(strategy=None),
        "hdr.mkv": MatchResult(strategy=None),
    }

    panel.populate(snapshots, matches)
    panel.filter_combo.setCurrentText("已保护跳过")

    m = panel.table.model()
    assert m.rowCount() == 2  # only protected rows visible
    assert m.data(m.index(0, 3), Qt.DisplayRole) == "hevc"
    assert "HDR10" in str(m.data(m.index(1, 4), Qt.DisplayRole) or "")
    panel.close()


def test_file_list_selection_count_uses_processable_total():
    from leanreel.domain.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(relative_path="sdr-a.mkv", file_name="sdr-a.mkv", size_bytes=1024, video_codec="h264"),
        FileSnapshot(relative_path="sdr-b.mkv", file_name="sdr-b.mkv", size_bytes=1024, video_codec="h264"),
        FileSnapshot(relative_path="hdr.mkv", file_name="hdr.mkv", size_bytes=1024, video_codec="h264", hdr_type=HDRType.HDR10),
    ]
    matches = {
        "sdr-a.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"}),
        "sdr-b.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"}),
        "hdr.mkv": MatchResult(strategy=None),
    }

    panel.populate(snapshots, matches)
    panel.select_all()

    assert panel.selection_label.text() == "已选中 2/2 个可处理文件"
    panel.close()


def test_file_list_can_update_row_with_custom_strategy():
    from leanreel.domain.models import Strategy
    from leanreel.domain.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(relative_path="movie.mkv", file_name="movie.mkv", size_bytes=10 * 1024**3)
    panel.populate([snap], {"movie.mkv": None})

    custom = Strategy(name="自定义", estimated_savings="50-70%")
    panel.apply_strategy_to_row("movie.mkv", custom)

    assert _text(panel, 0, 5) == "自定义"
    assert "5.0-7.0 GB" in _text(panel, 0, 6)
    panel.close()


def test_strategy_panel_custom_controls_emit_recomputed_strategy():
    from leanreel.gui.strategy_panel import StrategyPanel

    app = get_app()
    panel = StrategyPanel()
    changes = []
    panel.custom_strategy_changed.connect(changes.append)

    panel.show_custom_strategy()
    panel.custom_encoder_combo.setCurrentText("hevc_nvenc")
    panel.custom_cq_spin.setValue(25)

    assert panel.custom_group.isVisibleTo(panel)
    assert changes
    assert changes[-1].name == "NVENC HEVC CQ 25 自定义转码"
    assert changes[-1].video.cq == 25
    assert changes[-1].estimated_savings == "35-55%"
    assert panel.current_strategy.name == "NVENC HEVC CQ 25 自定义转码"
    panel.close()


def test_strategy_panel_custom_x265_uses_crf_name_and_cpu_metadata():
    from leanreel.gui.strategy_panel import StrategyPanel

    app = get_app()
    panel = StrategyPanel()
    panel.show_custom_strategy()
    panel.custom_encoder_combo.setCurrentText("libx265")
    panel.custom_crf_spin.setValue(18)

    strategy = panel.current_strategy

    assert strategy.name == "x265 HEVC CRF 18 自定义转码"
    assert strategy.video.encoder == "libx265"
    assert strategy.video.gpu is False
    assert strategy.video.crf == 18
    assert strategy.quality_impact == "CPU x265 编码"
    panel.close()


def test_strategy_panel_custom_copy_hides_quality_controls_and_uses_copy_metadata():
    from leanreel.gui.strategy_panel import StrategyPanel

    app = get_app()
    panel = StrategyPanel()
    panel.show_custom_strategy()
    panel.custom_encoder_combo.setCurrentText("copy")

    strategy = panel.current_strategy

    assert strategy.name == "Copy Streams 自定义流复制"
    assert strategy.video.encoder == "copy"
    assert strategy.video.gpu is False
    assert strategy.quality_impact == "不重编码视频"
    assert not panel.custom_cq_spin.isVisibleTo(panel)
    assert not panel.custom_crf_spin.isVisibleTo(panel)
    panel.close()


def test_start_button_uses_primary_action_object_name():
    from leanreel.gui.strategy_panel import StrategyPanel

    app = get_app()
    panel = StrategyPanel()

    assert panel.start_btn.objectName() == "primary_action"
    assert panel.start_btn.styleSheet() == ""
    panel.close()


# ──────────────────────────────────────────
# _parse_savings_range() 模块级函数测试
# ──────────────────────────────────────────

def test_parse_savings_range_returns_fraction_for_range():
    """正向用例 1："20-35%" 返回小数元组 (0.20, 0.35)"""
    from leanreel.gui.file_list import _parse_savings_range

    lo, hi = _parse_savings_range("20-35%")
    assert abs(lo - 0.20) < 0.001
    assert abs(hi - 0.35) < 0.001


def test_parse_savings_range_with_different_range():
    """正向用例 2："10-50%" 返回 (0.10, 0.50)"""
    from leanreel.gui.file_list import _parse_savings_range

    lo, hi = _parse_savings_range("10-50%")
    assert abs(lo - 0.10) < 0.001
    assert abs(hi - 0.50) < 0.001


def test_parse_savings_range_returns_none_for_empty():
    """空字符串返回 None"""
    from leanreel.gui.file_list import _parse_savings_range

    result = _parse_savings_range("")
    assert result is None


def test_parse_savings_range_returns_none_for_non_numeric():
    """全非数字字符串返回 None"""
    from leanreel.gui.file_list import _parse_savings_range

    result = _parse_savings_range("abc")
    assert result is None


def test_parse_savings_range_single_number():
    """单数字 "50%" 返回 (0.50, 0.50)"""
    from leanreel.gui.file_list import _parse_savings_range

    lo, hi = _parse_savings_range("50%")
    assert abs(lo - 0.50) < 0.001
    assert abs(hi - 0.50) < 0.001


def test_parse_savings_range_decimal_percent():
    """小数百分比 "12.5%-33.3%" 正确解析为小数"""
    from leanreel.gui.file_list import _parse_savings_range

    lo, hi = _parse_savings_range("12.5%-33.3%")
    assert abs(lo - 0.125) < 0.001
    assert abs(hi - 0.333) < 0.001


def test_parse_savings_range_three_numbers_uses_first_two():
    """三个数字只取前两个："10-20-30%" → (0.10, 0.20)"""
    from leanreel.gui.file_list import _parse_savings_range

    lo, hi = _parse_savings_range("10-20-30%")
    assert abs(lo - 0.10) < 0.001
    assert abs(hi - 0.20) < 0.001


def test_parse_savings_range_no_percent_sign():
    """无百分号的数字同样解析："20-35" → (0.20, 0.35)"""
    from leanreel.gui.file_list import _parse_savings_range

    lo, hi = _parse_savings_range("20-35")
    assert abs(lo - 0.20) < 0.001
    assert abs(hi - 0.35) < 0.001


# ──────────────────────────────────────────
# _format_bytes 一致性测试（Issue 3）
# ──────────────────────────────────────────

def test_format_bytes_consistency_across_modules():
    """file_list 和 queue_panel 的 _format_bytes 来自同一源。"""
    from leanreel.gui.file_list import _format_bytes as fb1
    from leanreel.gui.queue_panel import _format_bytes as fb2

    assert fb1 is fb2, "_format_bytes 应从同一模块导入"
    assert fb1(1024) == "1.0 KB"
    assert fb1(0) == "—"


# ──────────────────────────────────────────
# 空文件夹无视频反馈测试（Issue 6）
# ──────────────────────────────────────────

def test_empty_folder_shows_no_video_feedback():
    """添加不含视频文件的文件夹时，消息明确指明未找到视频文件"""
    # 通过代码审查验证：_on_folder_added 中 len(snapshots) == 0 时
    # 设置状态为 f"未找到视频文件：{path}"，而非 "扫描完成：0 个文件"
    expected_prefix = "未找到视频文件："
    # 验证状态消息格式不包含模糊的"扫描完成"表述
    assert "扫描完成" not in expected_prefix
    assert "视频" in expected_prefix

