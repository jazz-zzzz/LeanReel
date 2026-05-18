"""快照仓库 — SnapshotRepository 持久层，负责 FileSnapshot 的 JSON 序列化/反序列化与 SQLite 读写"""
import json
import time
from dataclasses import asdict
from typing import Optional

from leanreel.infrastructure.database import Database
from leanreel.domain.models import FileSnapshot, AudioTrack, SubtitleTrack, HDRType
from leanreel.domain.interfaces import SnapshotStore


class SnapshotRepository(SnapshotStore):
    """快照持久层：负责 FileSnapshot 的 JSON 序列化/反序列化与 SQLite 读写。

    将数据转换和存储逻辑从 Scanner 中分离出来，保持单一职责。
    """

    def __init__(self, db: Database):
        self._db = db

    # ── 查询 ──

    def load_all(self, library_folder_id: int) -> list[FileSnapshot]:
        """从数据库加载某个目录下的全部已缓存快照。"""
        rows = self._db.execute(
            "SELECT * FROM file_snapshot WHERE library_folder_id=? ORDER BY relative_path",
            [library_folder_id],
        )
        return [self._row_to_snapshot(r) for r in rows]

    def get_cached(self, folder_id: int, rel_path: str) -> Optional[FileSnapshot]:
        """按目录+相对路径查询单条缓存快照，未命中返回 None。"""
        rows = self._db.execute(
            "SELECT * FROM file_snapshot WHERE library_folder_id=? AND relative_path=?",
            [folder_id, rel_path],
        )
        if not rows:
            return None
        return self._row_to_snapshot(rows[0])

    # ── 删除 ──

    def delete_orphans(self, folder_id: int, keep_paths: set[str]):
        """删除不再存在于磁盘上的孤儿缓存记录。

        keep_paths 为磁盘上实际发现的 relative_path 集合，
        数据库中不属于该集合的记录将被批量删除。
        """
        rows = self._db.execute(
            "SELECT relative_path FROM file_snapshot WHERE library_folder_id=?",
            [folder_id],
        )
        cached_paths = {r["relative_path"] for r in rows}
        orphans = cached_paths - keep_paths
        if not orphans:
            return

        orphans_list = list(orphans)
        batch_size = 500
        for i in range(0, len(orphans_list), batch_size):
            batch = orphans_list[i : i + batch_size]
            placeholders = ",".join(["?"] * len(batch))
            self._db.execute(
                f"DELETE FROM file_snapshot WHERE library_folder_id=? AND relative_path IN ({placeholders})",
                [folder_id] + batch,
            )

    # ── 写入 ──

    def save(self, snap: FileSnapshot):
        """插入或更新快照记录（ON CONFLICT upsert），含 SQLITE_BUSY 重试。"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._db.execute(
                    """INSERT INTO file_snapshot
                       (library_folder_id, relative_path, file_name, size_bytes,
                        video_codec, video_width, video_height, hdr_type,
                        audio_tracks, subtitle_tracks, duration_seconds, bitrate_bps,
                        file_mtime, probe_ok, probe_error)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(library_folder_id, relative_path) DO UPDATE SET
                       file_name=excluded.file_name,
                       size_bytes=excluded.size_bytes, video_codec=excluded.video_codec,
                       video_width=excluded.video_width, video_height=excluded.video_height,
                       hdr_type=excluded.hdr_type, audio_tracks=excluded.audio_tracks,
                       subtitle_tracks=excluded.subtitle_tracks,
                       duration_seconds=excluded.duration_seconds, bitrate_bps=excluded.bitrate_bps,
                       file_mtime=excluded.file_mtime, probe_ok=excluded.probe_ok,
                       probe_error=excluded.probe_error,
                       scanned_at=datetime('now')""",
                    [
                        snap.library_folder_id,
                        snap.relative_path,
                        snap.file_name,
                        snap.size_bytes,
                        snap.video_codec,
                        snap.video_width,
                        snap.video_height,
                        snap.hdr_type.value,
                        self._serialize_audio_tracks(snap.audio_tracks),
                        self._serialize_subtitle_tracks(snap.subtitle_tracks),
                        snap.duration_seconds,
                        snap.bitrate_bps,
                        snap.file_mtime,
                        1 if snap.probe_ok else 0,
                        snap.probe_error,
                    ],
                )
                return
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise

    # ── 行 → 模型 ──

    def _row_to_snapshot(self, row: dict) -> FileSnapshot:
        try:
            hdr = HDRType(row["hdr_type"])
        except ValueError:
            hdr = HDRType.SDR
        return FileSnapshot(
            id=row["id"],
            library_folder_id=row["library_folder_id"],
            relative_path=row["relative_path"],
            file_name=row["file_name"],
            size_bytes=row["size_bytes"],
            video_codec=row["video_codec"],
            video_width=row["video_width"],
            video_height=row["video_height"],
            hdr_type=hdr,
            audio_tracks=self._deserialize_audio_tracks(row["audio_tracks"]),
            subtitle_tracks=self._deserialize_subtitle_tracks(row["subtitle_tracks"]),
            duration_seconds=row["duration_seconds"],
            bitrate_bps=row["bitrate_bps"],
            file_mtime=row.get("file_mtime", 0.0),
            probe_ok=bool(row.get("probe_ok", 0)),
            probe_error=row.get("probe_error", ""),
        )

    # ── JSON 序列化 ──

    def _serialize_audio_tracks(self, tracks: list[AudioTrack]) -> str:
        return json.dumps([asdict(track) for track in tracks], ensure_ascii=False)

    def _serialize_subtitle_tracks(self, tracks: list[SubtitleTrack]) -> str:
        return json.dumps([asdict(track) for track in tracks], ensure_ascii=False)

    # ── JSON 反序列化 ──

    def _deserialize_audio_tracks(self, raw: str) -> list[AudioTrack]:
        return [
            AudioTrack(
                codec=item.get("codec", ""),
                channels=item.get("channels", 0),
                language=item.get("language", ""),
                title=item.get("title", ""),
                is_commentary=item.get("is_commentary", False),
            )
            for item in self._load_track_json(raw)
        ]

    def _deserialize_subtitle_tracks(self, raw: str) -> list[SubtitleTrack]:
        return [
            SubtitleTrack(
                codec=item.get("codec", ""),
                language=item.get("language", ""),
                title=item.get("title", ""),
                is_forced=item.get("is_forced", False),
            )
            for item in self._load_track_json(raw)
        ]

    def _load_track_json(self, raw: str) -> list[dict]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]
