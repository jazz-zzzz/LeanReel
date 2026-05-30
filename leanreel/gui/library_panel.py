"""库面板 — 左侧树形列表：库 → 文件夹，TMM 风格"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QInputDialog, QMessageBox, QMenu, QFileDialog,
    QLineEdit, QHBoxLayout
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QColor

from leanreel.ui_text import UI_TEXT
from leanreel.gui.theme import C_TEXT_SECONDARY


class LibraryPanel(QWidget):
    library_selected = Signal(int)
    folder_selected = Signal(int)  # 预留：文件夹被选中时通知外部（当前无人连接）
    library_added = Signal(str)
    folder_added = Signal(int, str)
    library_deleted = Signal(int)
    folder_removed = Signal(int)
    folder_refresh_requested = Signal(int)  # 右键刷新单个文件夹，传 folder_id

    def __init__(self):
        super().__init__()
        self._libraries = []
        self._folders_map = {}
        self.empty_item = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── 顶部工具栏 ──
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 4, 6, 4)

        self.add_btn = QPushButton(UI_TEXT.LIBRARY_NEW)
        self.add_btn.setToolTip(UI_TEXT.LIBRARY_NEW_TOOLTIP)
        self.add_btn.clicked.connect(self._add_library)
        toolbar.addWidget(self.add_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── 搜索 ──
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(UI_TEXT.LIBRARY_SEARCH_PLACEHOLDER)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_tree)
        layout.addWidget(self.search_edit)

        # ── 树形目录 ──
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

    def populate(self, libraries: list, folders_map: dict):
        self._libraries = libraries
        self._folders_map = folders_map
        self._rebuild_tree()

    def _rebuild_tree(self, filter_text: str = ""):
        self.tree.clear()
        self.empty_item = None
        for lib in self._libraries:
            folders = self._folders_map.get(lib.id, [])
            if filter_text:
                lib_match = filter_text.lower() in lib.name.lower()
                matching_folders = [f for f in folders if filter_text.lower() in f.path.lower()]
                if not lib_match and not matching_folders:
                    continue

            lib_item = QTreeWidgetItem([f"📁 {lib.name}"])
            lib_item.setData(0, Qt.UserRole, ("library", lib.id))
            font_bold = QFont()
            font_bold.setBold(True)
            lib_item.setFont(0, font_bold)
            self.tree.addTopLevelItem(lib_item)

            for folder in folders:
                if filter_text and filter_text.lower() not in folder.path.lower():
                    continue
                display = folder.path
                if len(display) > 80:
                    display = "..." + display[-77:]
                folder_item = QTreeWidgetItem([f"  {display}"])
                folder_item.setData(0, Qt.UserRole, ("folder", folder.id))
                folder_item.setToolTip(0, folder.path)
                folder_item.setForeground(0, QColor(C_TEXT_SECONDARY))
                lib_item.addChild(folder_item)

            lib_item.setExpanded(True)

        if self.tree.topLevelItemCount() == 0:
            self.empty_item = QTreeWidgetItem([UI_TEXT.LIBRARY_NO_MATCH])
            self.empty_item.setFlags(Qt.NoItemFlags)
            self.empty_item.setForeground(0, QColor(C_TEXT_SECONDARY))
            self.tree.addTopLevelItem(self.empty_item)

    def _filter_tree(self, text: str):
        self._rebuild_tree(text)

    def _on_item_clicked(self, item, col):
        data = item.data(0, Qt.UserRole)
        if data is None:
            return
        kind, obj_id = data
        if kind == "library":
            self.library_selected.emit(obj_id)
        elif kind == "folder":
            self.folder_selected.emit(obj_id)

    def _add_library(self):
        name, ok = QInputDialog.getText(self, UI_TEXT.LIBRARY_DIALOG_NEW_TITLE, UI_TEXT.LIBRARY_DIALOG_NAME_LABEL)
        if ok and name.strip():
            self.library_added.emit(name.strip())

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        if data is None:
            return
        kind, obj_id = data
        menu = QMenu()
        if kind == "library":
            menu.addAction(UI_TEXT.LIBRARY_CONTEXT_ADD_FOLDER, lambda: self._add_folder_dialog(obj_id))
            menu.addAction(UI_TEXT.LIBRARY_CONTEXT_DELETE, lambda: self._delete_library(obj_id))
        elif kind == "folder":
            menu.addAction(UI_TEXT.LIBRARY_CONTEXT_REBUILD_CACHE, lambda: self.folder_refresh_requested.emit(obj_id))
            menu.addSeparator()
            menu.addAction(UI_TEXT.LIBRARY_CONTEXT_REMOVE_FOLDER, lambda: self._remove_folder(obj_id))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _add_folder_dialog(self, lib_id):
        path = QFileDialog.getExistingDirectory(self, UI_TEXT.LIBRARY_CHOOSE_FOLDER_TITLE)
        if path:
            self.folder_added.emit(lib_id, path)

    def _delete_library(self, lib_id):
        result = QMessageBox.question(
            self,
            UI_TEXT.LIBRARY_DELETE_TITLE,
            UI_TEXT.LIBRARY_DELETE_PROMPT,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.library_deleted.emit(lib_id)

    def _remove_folder(self, folder_id):
        result = QMessageBox.question(
            self,
            UI_TEXT.LIBRARY_REMOVE_FOLDER_TITLE,
            UI_TEXT.LIBRARY_REMOVE_FOLDER_PROMPT,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.folder_removed.emit(folder_id)
