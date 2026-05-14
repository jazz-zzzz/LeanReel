"""库面板 — 左侧树形列表：库 → 文件夹，TMM 风格"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QInputDialog, QMessageBox, QMenu, QFileDialog,
    QLineEdit, QHBoxLayout
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont


class LibraryPanel(QWidget):
    library_selected = Signal(int)
    folder_selected = Signal(int)
    library_added = Signal(str)
    folder_added = Signal(int, str)
    library_deleted = Signal(int)
    folder_removed = Signal(int)

    def __init__(self):
        super().__init__()
        self._libraries = []
        self._folders_map = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── 顶部工具栏 ──
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 4, 6, 4)

        self.add_btn = QPushButton("+ 新建")
        self.add_btn.setToolTip("新建库")
        self.add_btn.clicked.connect(self._add_library)
        toolbar.addWidget(self.add_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── 搜索 ──
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索库或文件夹...")
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
                folder_item.setForeground(0, Qt.gray)
                lib_item.addChild(folder_item)

            lib_item.setExpanded(True)

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
        name, ok = QInputDialog.getText(self, "新建库", "库名称：")
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
            menu.addAction("添加文件夹...", lambda: self._add_folder_dialog(obj_id))
            menu.addAction("删除库", lambda: self._delete_library(obj_id))
        elif kind == "folder":
            menu.addAction("移除文件夹", lambda: self._remove_folder(obj_id))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _add_folder_dialog(self, lib_id):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            self.folder_added.emit(lib_id, path)

    def _delete_library(self, lib_id):
        self.library_deleted.emit(lib_id)

    def _remove_folder(self, folder_id):
        self.folder_removed.emit(folder_id)
