"""库管理器 — 库和文件夹的 CRUD 操作"""
from leanreel.data.database import Database
from leanreel.data.models import Library, LibraryFolder


class LibraryManager:
    def __init__(self, db: Database):
        self.db = db

    def create_library(self, name: str) -> Library:
        existing = self.db.execute(
            "SELECT id FROM library WHERE name=?", [name]
        )
        if existing:
            raise ValueError(f"库 '{name}' 已存在")
        lid = self.db.insert_library(Library(name=name))
        return Library(id=lid, name=name)

    def get_all_libraries(self) -> list[Library]:
        return self.db.get_all_libraries()

    def rename_library(self, lib_id: int, new_name: str) -> Library:
        self.db.execute("UPDATE library SET name=? WHERE id=?", [new_name, lib_id])
        return Library(id=lib_id, name=new_name)

    def delete_library(self, lib_id: int):
        self.db.delete_library(lib_id)

    def add_folder(self, lib_id: int, path: str) -> LibraryFolder:
        fid = self.db.insert_folder(LibraryFolder(library_id=lib_id, path=path))
        return LibraryFolder(id=fid, library_id=lib_id, path=path)

    def get_folders(self, lib_id: int) -> list[LibraryFolder]:
        return self.db.get_folders_for_library(lib_id)

    def remove_folder(self, folder_id: int):
        self.db.delete_folder(folder_id)
