"""数据库层测试"""
import pytest
from pathlib import Path
from leanreel.infrastructure.database import Database
from leanreel.domain.models import Library, LibraryFolder, HDRType, TaskStatus


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    yield database
    database.close()


def test_create_tables(db: Database):
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {t["name"] for t in tables}
    assert "library" in names
    assert "library_folder" in names
    assert "file_snapshot" in names
    assert "compression_history" in names


def test_insert_and_get_library(db: Database):
    lib = Library(name="Film")
    lib_id = db.insert_library(lib)
    assert isinstance(lib_id, int)
    assert lib_id > 0

    libs = db.get_all_libraries()
    assert len(libs) == 1
    assert libs[0].name == "Film"
    assert libs[0].id == lib_id


def test_write_persists_across_connections(tmp_path: Path):
    db_path = tmp_path / "persistent.db"
    first = Database(str(db_path))
    first.execute("INSERT INTO library (name) VALUES (?)", ["Film"])
    first.close()

    second = Database(str(db_path))
    try:
        libs = second.get_all_libraries()
    finally:
        second.close()

    assert [lib.name for lib in libs] == ["Film"]


def test_explicit_transaction_rolls_back_all_writes(tmp_path: Path):
    db_path = tmp_path / "rollback.db"
    db = Database(str(db_path))
    try:
        db.begin()
        db.execute("INSERT INTO library (name) VALUES (?)", ["Rollback Film"])
        db.execute("INSERT INTO library (name) VALUES (?)", ["Rollback TV"])
        db.rollback()

        rows = db.execute("SELECT name FROM library ORDER BY id")
    finally:
        db.close()

    assert rows == []


def test_insert_duplicate_library_name(db: Database):
    db.insert_library(Library(name="Film"))
    with pytest.raises(Exception):
        db.insert_library(Library(name="Film"))


def test_folder_crud(db: Database):
    lib_id = db.insert_library(Library(name="Film"))
    folder = LibraryFolder(library_id=lib_id, path="/mnt/nas/Film")
    fid = db.insert_folder(folder)
    assert isinstance(fid, int)
    assert fid > 0

    folders = db.get_folders_for_library(lib_id)
    assert len(folders) == 1
    assert folders[0].path == "/mnt/nas/Film"
    assert folders[0].id == fid


def test_compression_history(db: Database):
    from leanreel.domain.models import CompressionRecord
    lib_id = db.insert_library(Library(name="Film"))
    fid = db.insert_folder(LibraryFolder(library_id=lib_id, path="/mnt/f"))
    # Insert a file snapshot
    db.execute(
        "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec, video_width, video_height, hdr_type) VALUES (?,?,?,?,?,?,?,?)",
        [fid, "test.mkv", "test.mkv", 1000, "hevc", 1920, 1080, "SDR"]
    )
    snap_id = db.last_insert_id
    db.insert_compression(CompressionRecord(
        file_snapshot_id=snap_id,
        strategy_name="均衡压缩",
        original_size=50000,
        compressed_size=20000,
        status=TaskStatus.COMPLETED,
        duration_seconds=300,
    ))
    records = db.get_history_for_library(lib_id)
    assert len(records) == 1
    assert records[0].strategy_name == "均衡压缩"


def test_get_compression_records_for_folders_returns_latest_completed_sidecar(db: Database):
    from leanreel.domain.models import CompressionRecord

    lib_id = db.insert_library(Library(name="Film"))
    fid = db.insert_folder(LibraryFolder(library_id=lib_id, path="/mnt/f"))
    db.execute(
        "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec, video_width, video_height, hdr_type) VALUES (?,?,?,?,?,?,?,?)",
        [fid, "movie.mkv", "movie.mkv", 1000, "h264", 1920, 1080, "SDR"],
    )
    snap_id = db.last_insert_id
    db.insert_compression(CompressionRecord(
        file_snapshot_id=snap_id,
        strategy_name="旧记录",
        status=TaskStatus.FAILED,
        sidecar_path="/mnt/f/old.json",
    ))
    db.insert_compression(CompressionRecord(
        file_snapshot_id=snap_id,
        strategy_name="SQL 压缩记录",
        status=TaskStatus.COMPLETED,
        sidecar_path="/mnt/f/movie_zcompressed.mkv.leanreel.json",
    ))

    records = db.get_compression_records_for_folders({fid})

    assert set(records) == {(fid, "movie.mkv")}
    assert records[(fid, "movie.mkv")].strategy_name == "SQL 压缩记录"
    assert records[(fid, "movie.mkv")].sidecar_path.endswith(".leanreel.json")
