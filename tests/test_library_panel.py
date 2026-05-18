from PySide6.QtWidgets import QMessageBox

from leanreel.domain.models import Library, LibraryFolder
from leanreel.gui.library_panel import LibraryPanel


def test_library_delete_requires_confirmation(qtbot, monkeypatch):
    panel = LibraryPanel()
    qtbot.addWidget(panel)
    emitted = []
    panel.library_deleted.connect(emitted.append)
    panel.populate([Library(id=7, name="电影库")], {7: []})

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    panel._delete_library(7)
    assert emitted == []

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    panel._delete_library(7)
    assert emitted == [7]


def test_folder_remove_requires_confirmation(qtbot, monkeypatch):
    panel = LibraryPanel()
    qtbot.addWidget(panel)
    emitted = []
    panel.folder_removed.connect(emitted.append)
    panel.populate(
        [Library(id=3, name="剧集")],
        {3: [LibraryFolder(id=11, library_id=3, path="Z:/Series")]},
    )

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    panel._remove_folder(11)
    assert emitted == []

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    panel._remove_folder(11)
    assert emitted == [11]


def test_library_search_empty_state_is_visible(qtbot):
    panel = LibraryPanel()
    qtbot.addWidget(panel)
    panel.populate([Library(id=1, name="电影库")], {1: []})

    panel.search_edit.setText("no-match")

    assert panel.empty_item is not None
    assert panel.tree.topLevelItem(0).text(0) == "没有匹配的库或文件夹"
