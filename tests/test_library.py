"""库管理测试"""
import os as _os
import pytest
from leanreel.infrastructure.database import Database
from leanreel.services.library import LibraryManager

@pytest.fixture
def mgr(tmp_path):
    return LibraryManager(Database(str(tmp_path / "test.db")))

def test_create_library(mgr: LibraryManager):
    lib = mgr.create_library("Film")
    assert lib.id == 1
    assert lib.name == "Film"
    assert len(mgr.get_all_libraries()) == 1

def test_create_duplicate_library_fails(mgr: LibraryManager):
    mgr.create_library("Film")
    with pytest.raises(ValueError):
        mgr.create_library("Film")

def test_add_folder_to_library(mgr: LibraryManager):
    lib = mgr.create_library("Film")
    folder = mgr.add_folder(lib.id, "/mnt/nas/Film")
    assert folder.id == 1
    assert folder.path == _os.path.normpath("/mnt/nas/Film")

    folders = mgr.get_folders(lib.id)
    assert len(folders) == 1

def test_remove_library_cascades(mgr: LibraryManager):
    lib = mgr.create_library("Film")
    mgr.add_folder(lib.id, "/mnt/nas/Film")
    mgr.delete_library(lib.id)
    assert len(mgr.get_all_libraries()) == 0

def test_rename_library(mgr: LibraryManager):
    lib = mgr.create_library("Film")
    updated = mgr.rename_library(lib.id, "Movies")
    assert updated.name == "Movies"
    assert updated.id == lib.id
    # 验证持久化
    libs = mgr.get_all_libraries()
    assert libs[0].name == "Movies"


def test_rename_library_persists(mgr: LibraryManager):
    lib = mgr.create_library("Film")
    mgr.rename_library(lib.id, "Movies")
    libs = mgr.get_all_libraries()
    assert len(libs) == 1
    assert libs[0].name == "Movies"
    assert libs[0].id == lib.id


def test_rename_nonexistent_library_does_not_crash(mgr: LibraryManager):
    """重命名不存在的库不应抛异常（SQL UPDATE 匹配 0 行）"""
    updated = mgr.rename_library(999, "Ghost")
    assert updated.id == 999
    assert updated.name == "Ghost"


def test_rename_to_duplicate_name_raises(mgr: LibraryManager):
    mgr.create_library("Film")
    mgr.create_library("Movies")
    with pytest.raises(Exception):
        mgr.rename_library(2, "Film")  # UNIQUE 约束冲突
