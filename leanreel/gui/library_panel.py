"""库面板 — 左侧树形列表：库 → 文件夹"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QInputDialog, QMessageBox, QMenu, QFileDialog
)
from PySide6.QtCore import Signal, Qt


class LibraryPanel(QWidget):
    library_selected = Signal(int)         # library_id
    folder_selected = Signal(int)          # folder_id
    library_added = Signal(str)            # name
    folder_added = Signal(int, str)        # library_id, path
    library_deleted = Signal(int)          # library_id
    folder_removed = Signal(int)           # folder_id

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemClicked.connect(self._on_item_clicked)

        self.add_btn = QPushButton("+ 添加库")
        self.add_btn.clicked.connect(self._add_library)

        layout.addWidget(self.tree)
        layout.addWidget(self.add_btn)

    def populate(self, libraries: list, folders_map: dict):
        """libraries: list[Library], folders_map: {library_id: [LibraryFolder]}"""
        self.tree.clear()
        for lib in libraries:
            lib_item = QTreeWidgetItem([lib.name])
            lib_item.setData(0, Qt.UserRole, ("library", lib.id))
            self.tree.addTopLevelItem(lib_item)
            for folder in folders_map.get(lib.id, []):
                folder_item = QTreeWidgetItem([folder.path])
                folder_item.setData(0, Qt.UserRole, ("folder", folder.id))
                lib_item.addChild(folder_item)

    def _on_item_clicked(self, item, col):
        kind, obj_id = item.data(0, Qt.UserRole)
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
        kind, obj_id = item.data(0, Qt.UserRole)
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
