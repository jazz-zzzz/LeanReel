"""数据库层测试"""
import sqlite3
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


def test_get_compression_records_for_folders_returns_latest_completed_record(db: Database):
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
        sidecar_path="",
        output_path="/mnt/f/movie_zcompressed.mkv",
    ))

    records = db.get_compression_records_for_folders({fid})

    assert set(records) == {(fid, "movie.mkv")}
    assert records[(fid, "movie.mkv")].strategy_name == "SQL 压缩记录"
    assert records[(fid, "movie.mkv")].output_path.endswith("_zcompressed.mkv")


def test_compression_history_runtime_columns_exist(db):
    cols = {row["name"] for row in db.execute("PRAGMA table_info(compression_history)")}

    assert "progress" in cols
    assert "stage" in cols
    assert "started_at" in cols
    assert "completed_at" in cols
    assert "updated_at" in cols
    assert "batch_id" in cols


def test_create_pending_compression_records_for_batch(db):
    from leanreel.domain.models import Library, LibraryFolder, FileSnapshot

    lib_id = db.insert_library(Library(name="Movies"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path="/movies"))
    db.execute(
        "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec) VALUES (?,?,?,?,?)",
        [folder_id, "a.mkv", "a.mkv", 1000, "h264"],
    )
    snap_id = db.last_insert_id

    record_id = db.create_compression_record(
        file_snapshot_id=snap_id,
        batch_id="batch-1",
        strategy_name="AV1 NVENC CQ34",
        original_size=1000,
        output_path="/movies/a_zcompressed.mkv",
        encoder="av1_nvenc",
        cq_value=34,
    )

    rows = db.get_all_history()
    assert len(rows) == 1
    assert record_id == rows[0]["id"]
    assert rows[0]["status"] == "pending"
    assert rows[0]["progress"] == 0
    assert rows[0]["stage"] == ""
    assert rows[0]["batch_id"] == "batch-1"


def test_update_compression_runtime_and_terminal_state(db):
    from leanreel.domain.models import Library, LibraryFolder, FileSnapshot

    lib_id = db.insert_library(Library(name="Movies"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path="/movies"))
    db.execute(
        "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec) VALUES (?,?,?,?,?)",
        [folder_id, "a.mkv", "a.mkv", 1000, "h264"],
    )
    snap_id = db.last_insert_id
    record_id = db.create_compression_record(
        file_snapshot_id=snap_id,
        batch_id="batch-1",
        strategy_name="AV1 NVENC CQ34",
        original_size=1000,
        output_path="/movies/a_zcompressed.mkv",
        encoder="av1_nvenc",
        cq_value=34,
    )

    db.update_compression_runtime(
        record_id,
        status="running",
        progress=42.5,
        stage="转码",
        duration_seconds=12,
    )
    running = db.get_compression_record(record_id)
    assert running["status"] == "running"
    assert running["progress"] == 42.5
    assert running["stage"] == "转码"
    assert running["duration_seconds"] == 12

    db.finish_compression(
        record_id,
        status="completed",
        progress=100.0,
        duration_seconds=30,
        compressed_size=600,
        output_size_bytes=600,
        savings_pct=40.0,
        error_message="",
        sidecar_path="/movies/a_zcompressed.mkv.leanreel.json",
    )
    completed = db.get_compression_record(record_id)
    assert completed["status"] == "completed"
    assert completed["progress"] == 100.0
    assert completed["completed_at"] != ""
    assert completed["compressed_size"] == 600
    assert completed["savings_pct"] == 40.0


def test_get_batch_progress_aggregates_statuses(db):
    from leanreel.domain.models import Library, LibraryFolder, FileSnapshot

    lib_id = db.insert_library(Library(name="Movies"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path="/movies"))
    ids = []
    for name in ("a.mkv", "b.mkv", "c.mkv"):
        db.execute(
            "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec) VALUES (?,?,?,?,?)",
            [folder_id, name, name, 1000, "h264"],
        )
        snap_id = db.last_insert_id
        ids.append(db.create_compression_record(
            file_snapshot_id=snap_id,
            batch_id="batch-1",
            strategy_name="AV1",
            original_size=1000,
            output_path=f"/movies/{name}.out.mkv",
            encoder="av1_nvenc",
            cq_value=34,
        ))

    db.finish_compression(ids[0], status="completed", progress=100, duration_seconds=10)
    db.finish_compression(ids[1], status="failed", progress=25, duration_seconds=3, error_message="boom")

    progress = db.get_batch_progress("batch-1")
    # get_batch_progress does not track "skipped" as a separate status.
    # percentage = sum of all progress values / total = (100+25+0)/3 = 41.67
    assert progress == {
        "total": 3,
        "completed": 1,
        "skipped": 0,
        "failed": 1,
        "cancelled": 0,
        "discarded": 0,
        "pending": 1,
        "running": 0,
        "percentage": pytest.approx(41.666666666666664),
    }


def test_insert_compression_sets_updated_at_and_sorts_after_migration(tmp_path: Path):
    from leanreel.domain.models import CompressionRecord, FileSnapshot

    db_path = tmp_path / "migrated.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE library_folder (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_id INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            UNIQUE(library_id, path)
        );
        CREATE TABLE file_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_folder_id INTEGER NOT NULL REFERENCES library_folder(id) ON DELETE CASCADE,
            relative_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            video_codec TEXT DEFAULT '',
            video_width INTEGER DEFAULT 0,
            video_height INTEGER DEFAULT 0,
            hdr_type TEXT DEFAULT 'SDR',
            audio_tracks TEXT DEFAULT '[]',
            subtitle_tracks TEXT DEFAULT '[]',
            duration_seconds REAL DEFAULT 0,
            bitrate_bps INTEGER DEFAULT 0,
            scanned_at TEXT DEFAULT (datetime('now')),
            UNIQUE(library_folder_id, relative_path)
        );
        CREATE TABLE compression_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_snapshot_id INTEGER NOT NULL REFERENCES file_snapshot(id) ON DELETE CASCADE,
            strategy_name TEXT NOT NULL,
            original_size INTEGER DEFAULT 0,
            compressed_size INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            duration_seconds INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT ''
        );
        INSERT INTO library (name) VALUES ('Movies');
        INSERT INTO library_folder (library_id, path) VALUES (1, '/movies');
        INSERT INTO file_snapshot (
            library_folder_id, relative_path, file_name, size_bytes, video_codec,
            video_width, video_height, hdr_type
        ) VALUES (1, 'old.mkv', 'old.mkv', 1000, 'h264', 1920, 1080, 'SDR');
        INSERT INTO compression_history (
            file_snapshot_id, strategy_name, status, created_at
        ) VALUES (1, 'old', 'completed', '2000-01-01 00:00:00');
    """)
    conn.commit()
    conn.close()

    migrated = Database(str(db_path))
    try:
        migrated.execute(
            "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec) VALUES (?,?,?,?,?)",
            [1, "new.mkv", "new.mkv", 1000, "h264"],
        )
        snap_id = migrated.last_insert_id
        new_id = migrated.insert_compression(CompressionRecord(
            file_snapshot_id=snap_id,
            strategy_name="new",
            status=TaskStatus.COMPLETED,
        ))

        new_row = migrated.get_compression_record(new_id)
        rows = migrated.get_all_history()
    finally:
        migrated.close()

    assert new_row["updated_at"] != ""
    assert [row["strategy_name"] for row in rows[:2]] == ["new", "old"]


def test_insert_compression_sets_updated_at_on_fresh_schema(db):
    from leanreel.domain.models import CompressionRecord, FileSnapshot

    lib_id = db.insert_library(Library(name="Movies"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path="/movies"))
    db.execute(
        "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec) VALUES (?,?,?,?,?)",
        [folder_id, "a.mkv", "a.mkv", 1000, "h264"],
    )
    snap_id = db.last_insert_id

    record_id = db.insert_compression(CompressionRecord(
        file_snapshot_id=snap_id,
        strategy_name="legacy",
        status=TaskStatus.COMPLETED,
    ))

    assert db.get_compression_record(record_id)["updated_at"] != ""


def test_get_batch_progress_bounds_each_row_and_includes_skipped(db):
    from leanreel.domain.models import FileSnapshot

    lib_id = db.insert_library(Library(name="Movies"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path="/movies"))
    ids = []
    for name in ("a.mkv", "b.mkv", "c.mkv", "d.mkv", "e.mkv"):
        db.execute(
            "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec) VALUES (?,?,?,?,?)",
            [folder_id, name, name, 1000, "h264"],
        )
        snap_id = db.last_insert_id
        ids.append(db.create_compression_record(
            file_snapshot_id=snap_id,
            batch_id="batch-1",
            strategy_name="AV1",
            original_size=1000,
            output_path=f"/movies/{name}.out.mkv",
        ))

    db.finish_compression(ids[0], status="completed", progress=100, duration_seconds=10)
    db.finish_compression(ids[1], status="failed", progress=25, duration_seconds=3)
    db.finish_compression(ids[2], status="skipped", progress=10, duration_seconds=0)
    db.update_compression_runtime(ids[3], status="running", progress=150, stage="转码", duration_seconds=1)
    db.update_compression_runtime(ids[4], status="pending", progress=-10, stage="", duration_seconds=0)

    progress = db.get_batch_progress("batch-1")

    assert progress["completed"] == 1
    assert progress["skipped"] == 1
    assert progress["failed"] == 1
    assert progress["pending"] == 1
    assert progress["running"] == 1
    assert progress["total"] == 5
    # percentage clamps each row first: (100+25+10+100+0) / 5 = 47.0
    assert progress["percentage"] == 47.0


def test_history_survives_deleted_folder_using_denormalized_source_fields(db: Database):
    lib_id = db.insert_library(Library(name="Movies"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path="/movies"))
    db.execute(
        "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec) VALUES (?,?,?,?,?)",
        [folder_id, "gone.mkv", "gone.mkv", 1000, "h264"],
    )
    snap_id = db.last_insert_id
    db.create_compression_record(
        file_snapshot_id=snap_id,
        batch_id="batch-1",
        strategy_name="AV1",
        original_size=1000,
        output_path="/movies/gone_zcompressed.mkv",
    )

    db.delete_folder(folder_id)

    rows = db.get_all_history()
    assert len(rows) == 1
    assert rows[0]["library_name"] == "Movies"
    assert rows[0]["folder_path"] == "/movies"
    assert rows[0]["relative_path"] == "gone.mkv"
    assert rows[0]["file_name"] == "gone.mkv"
    assert rows[0]["library_folder_id"] == folder_id


def test_compression_record_runtime_fields_round_trip_through_typed_history(db):
    from leanreel.domain.models import CompressionRecord, FileSnapshot

    lib_id = db.insert_library(Library(name="Movies"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path="/movies"))
    db.execute(
        "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec) VALUES (?,?,?,?,?)",
        [folder_id, "a.mkv", "a.mkv", 1000, "h264"],
    )
    snap_id = db.last_insert_id

    # Use create_compression_record for runtime fields + direct UPDATE for typed fields
    record_id = db.create_compression_record(
        file_snapshot_id=snap_id,
        batch_id="batch-1",
        strategy_name="runtime",
        original_size=0,
        output_path="",
    )
    # Then update with runtime values via SQL
    db.execute("""
        UPDATE compression_history
        SET status = 'running',
            source_deleted = 1,
            progress = 37.5,
            stage = '转码',
            started_at = '2026-05-26 01:00:00',
            completed_at = '2026-05-26 01:30:00',
            updated_at = '2026-05-26 01:15:00'
        WHERE id = ?
    """, [record_id])

    # get_all_history() returns raw dicts with all columns including runtime fields
    all_history = db.get_all_history()
    record = all_history[0]

    assert record["source_deleted"] == 1
    assert record["progress"] == 37.5
    assert record["stage"] == "转码"
    assert record["started_at"] == "2026-05-26 01:00:00"
    assert record["completed_at"] == "2026-05-26 01:30:00"
    assert record["updated_at"] == "2026-05-26 01:15:00"
    assert record["batch_id"] == "batch-1"
