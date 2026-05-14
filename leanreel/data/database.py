"""SQLite 数据库操作 — 无 ORM，原生 SQL"""
import sqlite3
from pathlib import Path
from typing import Optional

from leanreel.data.models import (
    Library, LibraryFolder, FileSnapshot,
    CompressionRecord, AudioTrack, SubtitleTrack
)


class Database:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS library_folder (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_id INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            UNIQUE(library_id, path)
        );
        CREATE TABLE IF NOT EXISTS file_snapshot (
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
            file_mtime REAL DEFAULT 0,
            probe_ok INTEGER DEFAULT 0,
            scanned_at TEXT DEFAULT (datetime('now')),
            UNIQUE(library_folder_id, relative_path)
        );
        CREATE TABLE IF NOT EXISTS compression_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_snapshot_id INTEGER NOT NULL REFERENCES file_snapshot(id) ON DELETE CASCADE,
            strategy_name TEXT NOT NULL,
            original_size INTEGER DEFAULT 0,
            compressed_size INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            duration_seconds INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        self._migrate()

    def _migrate(self):
        """增量迁移：为旧数据库添加缺失列"""
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(file_snapshot)")}
        if "file_mtime" not in existing:
            self.conn.execute("ALTER TABLE file_snapshot ADD COLUMN file_mtime REAL DEFAULT 0")
        if "probe_ok" not in existing:
            self.conn.execute("ALTER TABLE file_snapshot ADD COLUMN probe_ok INTEGER DEFAULT 0")

    def execute(self, sql: str, params=None):
        try:
            cur = self.conn.execute(sql, params or [])
            rows = [dict(row) for row in cur.fetchall()] if cur.description else []
            if self.conn.in_transaction:
                self.conn.commit()
            return rows
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    @property
    def last_insert_id(self) -> int:
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def insert_library(self, lib: Library) -> int:
        self.execute("INSERT INTO library (name) VALUES (?)", [lib.name])
        return self.last_insert_id

    def get_all_libraries(self) -> list[Library]:
        rows = self.execute("SELECT * FROM library ORDER BY id")
        return [Library(id=r["id"], name=r["name"]) for r in rows]

    def delete_library(self, lib_id: int):
        self.execute("DELETE FROM library WHERE id=?", [lib_id])

    def insert_folder(self, folder: LibraryFolder) -> int:
        self.execute(
            "INSERT INTO library_folder (library_id, path) VALUES (?,?)",
            [folder.library_id, folder.path]
        )
        return self.last_insert_id

    def get_folders_for_library(self, lib_id: int) -> list[LibraryFolder]:
        rows = self.execute(
            "SELECT * FROM library_folder WHERE library_id=? ORDER BY id",
            [lib_id]
        )
        return [LibraryFolder(id=r["id"], library_id=r["library_id"], path=r["path"]) for r in rows]

    def delete_folder(self, folder_id: int):
        self.execute("DELETE FROM library_folder WHERE id=?", [folder_id])

    def insert_compression(self, record: CompressionRecord) -> int:
        self.execute(
            """INSERT INTO compression_history
               (file_snapshot_id, strategy_name, original_size, compressed_size, status, duration_seconds, error_message)
               VALUES (?,?,?,?,?,?,?)""",
            [record.file_snapshot_id, record.strategy_name, record.original_size,
             record.compressed_size, record.status, record.duration_seconds, record.error_message]
        )
        return self.last_insert_id

    def get_history_for_library(self, lib_id: int) -> list[CompressionRecord]:
        rows = self.execute("""
            SELECT ch.* FROM compression_history ch
            JOIN file_snapshot fs ON ch.file_snapshot_id = fs.id
            JOIN library_folder lf ON fs.library_folder_id = lf.id
            WHERE lf.library_id = ?
            ORDER BY ch.created_at DESC
        """, [lib_id])
        return [CompressionRecord(
            id=r["id"], file_snapshot_id=r["file_snapshot_id"],
            strategy_name=r["strategy_name"], original_size=r["original_size"],
            compressed_size=r["compressed_size"], status=r["status"],
            duration_seconds=r["duration_seconds"], error_message=r["error_message"],
            created_at=r["created_at"]
        ) for r in rows]

    def close(self):
        self.conn.close()
