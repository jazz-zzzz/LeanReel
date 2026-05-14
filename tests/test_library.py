"""库管理测试"""
import pytest
from leanreel.data.database import Database
from leanreel.core.library import LibraryManager

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
    assert folder.path == "/mnt/nas/Film"

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
