"""文件扫描器 — 递归扫描视频文件，FFprobe 提取元数据并缓存"""
import os
from pathlib import Path
from typing import Optional

from leanreel.data.database import Database
from leanreel.data.models import FileSnapshot

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".mov", ".wmv", ".m2ts", ".mts"}


class Scanner:
    """文件夹扫描器：递归发现视频文件，调用 FFprobe 提取元数据，结果缓存至 SQLite"""

    def __init__(self, db: Database, probe_runner=None):
        self.db = db
        self._probe = probe_runner

    def _get_probe(self):
        if self._probe is None:
            from leanreel.executor.probe import FFprobeRunner
            self._probe = FFprobeRunner()
        return self._probe

    def scan_folder(self, library_folder_id: int, folder_path: str) -> list[FileSnapshot]:
        """扫描文件夹，返回新增/变更的文件快照列表"""
        folder_path = os.path.normpath(folder_path)
        found_files = self._find_video_files(folder_path)
        results = []
        for rel_path, abs_path in found_files:
            # 检查是否已有缓存
            existing = self._get_cached_snapshot(library_folder_id, rel_path)
            file_size = os.path.getsize(abs_path)
            if existing and existing.size_bytes == file_size:
                results.append(existing)
                continue

            # 运行 FFprobe
            try:
                snap = self._get_probe().probe(abs_path, library_folder_id)
                snap.relative_path = rel_path
                self._upsert_snapshot(snap)
                results.append(snap)
            except Exception:
                # 如果 FFprobe 失败，使用最小信息创建快照
                snap = FileSnapshot(
                    library_folder_id=library_folder_id,
                    relative_path=rel_path,
                    file_name=os.path.basename(abs_path),
                    size_bytes=file_size,
                )
                self._upsert_snapshot(snap)
                results.append(snap)
        return results

    def _find_video_files(self, folder_path: str) -> list[tuple[str, str]]:
        """递归查找所有视频文件，返回 (相对路径, 绝对路径) 列表"""
        results = []
        for root, _dirs, files in os.walk(folder_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    abs_path = os.path.join(root, f)
                    rel_path = os.path.relpath(abs_path, folder_path)
                    results.append((rel_path, abs_path))
        return results

    def _get_cached_snapshot(self, folder_id: int, rel_path: str) -> Optional[FileSnapshot]:
        rows = self.db.execute(
            "SELECT * FROM file_snapshot WHERE library_folder_id=? AND relative_path=?",
            [folder_id, rel_path]
        )
        if not rows:
            return None
        return self._row_to_snapshot(rows[0])

    def _upsert_snapshot(self, snap: FileSnapshot):
        self.db.execute(
            """INSERT INTO file_snapshot
               (library_folder_id, relative_path, file_name, size_bytes,
                video_codec, video_width, video_height, hdr_type,
                audio_tracks, subtitle_tracks, duration_seconds, bitrate_bps)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(library_folder_id, relative_path) DO UPDATE SET
               size_bytes=excluded.size_bytes, video_codec=excluded.video_codec,
               video_width=excluded.video_width, video_height=excluded.video_height,
               hdr_type=excluded.hdr_type, audio_tracks=excluded.audio_tracks,
               subtitle_tracks=excluded.subtitle_tracks,
               duration_seconds=excluded.duration_seconds, bitrate_bps=excluded.bitrate_bps,
               scanned_at=datetime('now')""",
            [snap.library_folder_id, snap.relative_path, snap.file_name,
             snap.size_bytes, snap.video_codec, snap.video_width, snap.video_height,
             snap.hdr_type.value, repr(snap.audio_tracks), repr(snap.subtitle_tracks),
             snap.duration_seconds, snap.bitrate_bps]
        )

    def _row_to_snapshot(self, row: dict) -> FileSnapshot:
        from leanreel.data.models import HDRType
        return FileSnapshot(
            id=row["id"], library_folder_id=row["library_folder_id"],
            relative_path=row["relative_path"], file_name=row["file_name"],
            size_bytes=row["size_bytes"], video_codec=row["video_codec"],
            video_width=row["video_width"], video_height=row["video_height"],
            hdr_type=HDRType(row["hdr_type"]),
            duration_seconds=row["duration_seconds"], bitrate_bps=row["bitrate_bps"],
        )
