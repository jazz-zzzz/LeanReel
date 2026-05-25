"""SQLite 数据库操作 — 无 ORM，原生 SQL"""
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from leanreel.domain.models import (
    Library, LibraryFolder, FileSnapshot,
    CompressionRecord, AudioTrack, SubtitleTrack, TaskStatus
)
from leanreel.domain.interfaces import LibraryStore


class ConnectionPool:
    """为每个线程提供独立 SQLite 连接，消除并发写入冲突。"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()

    def get(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def get_explicit(self):
        return getattr(self._local, "explicit_conn", None)

    def set_explicit(self, conn):
        self._local.explicit_conn = conn

    def clear_explicit(self):
        self._local.explicit_conn = None

    def close_all(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None


class Database(LibraryStore):
    def __init__(self, db_path: str = ":memory:"):
        self._pool = ConnectionPool(db_path)
        conn = self._pool.get()  # 只在初始化线程用一次
        self._create_tables(conn)

    def _create_tables(self, conn: sqlite3.Connection):
        conn.executescript("""
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
            probe_error TEXT DEFAULT '',
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
        self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection):
        existing = {row[1] for row in conn.execute("PRAGMA table_info(file_snapshot)")}
        if "file_mtime" not in existing:
            conn.execute("ALTER TABLE file_snapshot ADD COLUMN file_mtime REAL DEFAULT 0")
        if "probe_ok" not in existing:
            conn.execute("ALTER TABLE file_snapshot ADD COLUMN probe_ok INTEGER DEFAULT 0")
        if "probe_error" not in existing:
            conn.execute("ALTER TABLE file_snapshot ADD COLUMN probe_error TEXT DEFAULT ''")

        existing_ch = {row[1] for row in conn.execute("PRAGMA table_info(compression_history)")}
        ch_migrations = [
            ("output_path", "TEXT DEFAULT ''"),
            ("output_size_bytes", "INTEGER DEFAULT 0"),
            ("savings_pct", "REAL DEFAULT 0"),
            ("encoder", "TEXT DEFAULT ''"),
            ("cq_value", "INTEGER DEFAULT 0"),
            ("preset", "TEXT DEFAULT ''"),
            ("pix_fmt", "TEXT DEFAULT ''"),
            ("audio_mode", "TEXT DEFAULT ''"),
            ("sub_mode", "TEXT DEFAULT ''"),
            ("ffmpeg_command", "TEXT DEFAULT ''"),
            ("sidecar_path", "TEXT DEFAULT ''"),
            ("leanreel_version", "TEXT DEFAULT ''"),
            ("source_deleted", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in ch_migrations:
            if col_name not in existing_ch:
                conn.execute(f"ALTER TABLE compression_history ADD COLUMN {col_name} {col_def}")

    def execute(self, sql: str, params=None):
        conn = self._pool.get()
        try:
            cur = conn.execute(sql, params or [])
            rows = [dict(row) for row in cur.fetchall()] if cur.description else []
            if self._pool.get_explicit() is None:
                conn.commit()
            return rows
        except Exception:
            if self._pool.get_explicit() is None:
                conn.rollback()
            raise

    def begin(self):
        """开启显式事务。此后 execute() 不会自动提交，由调用方显式 commit() 结束。

        典型用法:
            db.begin()
            try:
                db.execute("INSERT INTO ...")
                db.execute("INSERT INTO ...")
                db.commit()
            except Exception:
                db.rollback()
                raise
        """
        conn = self._pool.get()
        conn.execute("BEGIN IMMEDIATE")
        self._pool.set_explicit(conn)

    def commit(self):
        """提交当前事务。"""
        conn = self._pool.get_explicit()
        if conn is not None:
            conn.commit()
            self._pool.clear_explicit()

    def rollback(self):
        """回滚当前事务。"""
        conn = self._pool.get_explicit()
        if conn is not None:
            conn.rollback()
            self._pool.clear_explicit()

    @property
    def last_insert_id(self) -> int:
        conn = self._pool.get()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

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
        """插入压缩历史记录，返回记录 ID。"""
        cols = [
            "file_snapshot_id", "strategy_name", "original_size", "compressed_size",
            "status", "duration_seconds", "error_message",
            "output_path", "output_size_bytes", "savings_pct",
            "encoder", "cq_value", "preset", "pix_fmt",
            "audio_mode", "sub_mode", "ffmpeg_command", "sidecar_path", "leanreel_version",
            "source_deleted",
        ]
        values = [
            record.file_snapshot_id, record.strategy_name, record.original_size,
            record.compressed_size, record.status, record.duration_seconds,
            getattr(record, "error_message", ""),
            getattr(record, "output_path", ""),
            getattr(record, "output_size_bytes", 0),
            getattr(record, "savings_pct", 0.0),
            getattr(record, "encoder", ""),
            getattr(record, "cq_value", 0),
            getattr(record, "preset", ""),
            getattr(record, "pix_fmt", ""),
            getattr(record, "audio_mode", ""),
            getattr(record, "sub_mode", ""),
            getattr(record, "ffmpeg_command", ""),
            getattr(record, "sidecar_path", ""),
            getattr(record, "leanreel_version", ""),
            getattr(record, "source_deleted", 0),
        ]
        placeholders = ",".join("?" * len(cols))
        self.execute(
            f"INSERT INTO compression_history ({','.join(cols)}) VALUES ({placeholders})",
            values,
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
            compressed_size=r["compressed_size"], status=TaskStatus(r["status"]),
            duration_seconds=r["duration_seconds"], error_message=r["error_message"],
            created_at=r["created_at"],
            output_path=r.get("output_path", ""),
            output_size_bytes=r.get("output_size_bytes", 0),
            savings_pct=r.get("savings_pct", 0.0),
            encoder=r.get("encoder", ""),
            cq_value=r.get("cq_value", 0),
            preset=r.get("preset", ""),
            pix_fmt=r.get("pix_fmt", ""),
            audio_mode=r.get("audio_mode", ""),
            sub_mode=r.get("sub_mode", ""),
            ffmpeg_command=r.get("ffmpeg_command", ""),
            sidecar_path=r.get("sidecar_path", ""),
            leanreel_version=r.get("leanreel_version", ""),
        ) for r in rows]

    def get_all_history(self) -> list[dict]:
        """返回所有压缩历史记录，JOIN 出库名和文件夹路径，按时间倒序。"""
        rows = self.execute("""
            SELECT
                ch.id, ch.file_snapshot_id, ch.strategy_name,
                ch.original_size, ch.compressed_size, ch.output_size_bytes,
                ch.savings_pct, ch.encoder, ch.cq_value, ch.preset,
                ch.duration_seconds, ch.status, ch.error_message,
                ch.output_path, ch.sidecar_path, ch.created_at,
                ch.source_deleted, ch.leanreel_version,
                fs.file_name, fs.relative_path, fs.video_codec, fs.library_folder_id,
                lf.path AS folder_path,
                lib.name AS library_name
            FROM compression_history ch
            JOIN file_snapshot fs ON ch.file_snapshot_id = fs.id
            JOIN library_folder lf ON fs.library_folder_id = lf.id
            JOIN library lib ON lf.library_id = lib.id
            ORDER BY ch.created_at DESC
        """)
        return rows

    def get_compression_records_for_folders(self, folder_ids: set[int]) -> dict[tuple[int, str], CompressionRecord]:
        """Return the latest completed compression record keyed by source file."""
        if not folder_ids:
            return {}
        ordered_ids = sorted(int(folder_id) for folder_id in folder_ids)
        placeholders = ",".join("?" * len(ordered_ids))
        rows = self.execute(f"""
            SELECT
                fs.library_folder_id,
                fs.relative_path,
                ch.*
            FROM compression_history ch
            JOIN file_snapshot fs ON ch.file_snapshot_id = fs.id
            WHERE fs.library_folder_id IN ({placeholders})
              AND ch.status = ?
              AND ch.sidecar_path <> ''
            ORDER BY ch.created_at DESC, ch.id DESC
        """, [*ordered_ids, TaskStatus.COMPLETED.value])

        records: dict[tuple[int, str], CompressionRecord] = {}
        for r in rows:
            key = (int(r["library_folder_id"]), str(r["relative_path"]))
            if key in records:
                continue
            records[key] = CompressionRecord(
                id=r["id"],
                file_snapshot_id=r["file_snapshot_id"],
                strategy_name=r["strategy_name"],
                original_size=r["original_size"],
                compressed_size=r["compressed_size"],
                status=TaskStatus(r["status"]),
                duration_seconds=r["duration_seconds"],
                error_message=r["error_message"],
                created_at=r["created_at"],
                output_path=r.get("output_path", ""),
                output_size_bytes=r.get("output_size_bytes", 0),
                savings_pct=r.get("savings_pct", 0.0),
                encoder=r.get("encoder", ""),
                cq_value=r.get("cq_value", 0),
                preset=r.get("preset", ""),
                pix_fmt=r.get("pix_fmt", ""),
                audio_mode=r.get("audio_mode", ""),
                sub_mode=r.get("sub_mode", ""),
                ffmpeg_command=r.get("ffmpeg_command", ""),
                sidecar_path=r.get("sidecar_path", ""),
                leanreel_version=r.get("leanreel_version", ""),
            )
        return records

    def close(self):
        self._pool.close_all()
