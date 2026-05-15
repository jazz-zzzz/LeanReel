"""文件扫描器 — 递归扫描视频文件，FFprobe 提取元数据并缓存，支持异步后台探测"""
import json
import os
import time
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Callable

from leanreel.data.database import Database
from leanreel.data.models import AudioTrack, FileSnapshot, HDRType, SubtitleTrack

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".mov", ".wmv", ".m2ts", ".mts"}


@dataclass
class ScanBatch:
    snapshots: list[FileSnapshot]
    pending_jobs: list[tuple[int, str, str, int]]


def find_video_files(folder_path: str) -> list[tuple[str, str]]:
    """递归查找所有视频文件，使用 scandir 加速。

    返回 [(relative_path, absolute_path), ...]
    """
    results: list[tuple[str, str]] = []
    folder_path = os.path.normpath(folder_path)

    def _walk(current: str):
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        _walk(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in VIDEO_EXTENSIONS:
                            rel_path = os.path.relpath(entry.path, folder_path)
                            results.append((rel_path, entry.path))
        except OSError:
            pass

    _walk(folder_path)
    return results


class SnapshotRepository:
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
                        file_mtime, probe_ok)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(library_folder_id, relative_path) DO UPDATE SET
                       file_name=excluded.file_name,
                       size_bytes=excluded.size_bytes, video_codec=excluded.video_codec,
                       video_width=excluded.video_width, video_height=excluded.video_height,
                       hdr_type=excluded.hdr_type, audio_tracks=excluded.audio_tracks,
                       subtitle_tracks=excluded.subtitle_tracks,
                       duration_seconds=excluded.duration_seconds, bitrate_bps=excluded.bitrate_bps,
                       file_mtime=excluded.file_mtime, probe_ok=excluded.probe_ok,
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


class Scanner:
    """文件夹扫描器门面：编排文件发现、FFprobe 探测与缓存，对外 API 不变。

    内部将数据持久化委托给 SnapshotRepository，将文件发现委托给模块级函数。
    """

    def __init__(self, db: Database, probe_runner=None, max_workers: int = 4):
        self._repo = SnapshotRepository(db)
        self._probe = probe_runner
        self.max_workers = max(1, max_workers)
        self._probe_lock = threading.Lock()
        self._pending_jobs: list[tuple[int, str, str, int]] = []

    def _get_probe(self):
        if self._probe is None:
            from leanreel.executor.probe import FFprobeRunner

            self._probe = FFprobeRunner()
        return self._probe

    def load_cached(self, library_folder_id: int, folder_path: str) -> list[FileSnapshot]:
        """从数据库加载已缓存的快照列表，不走文件系统。毫秒级。"""
        return self._repo.load_all(library_folder_id)

    def scan_folder(self, library_folder_id: int, folder_path: str) -> list[FileSnapshot]:
        """同步扫描（向后兼容）：并行探测所有未缓存文件，返回最终结果。"""
        from concurrent.futures import ThreadPoolExecutor

        folder_path = os.path.normpath(folder_path)
        found_files = find_video_files(folder_path)
        results = []
        probe_jobs = []

        # 批量加载缓存到内存 dict，避免逐文件 DB 查询
        cached_dict = {s.relative_path: s for s in self._repo.load_all(library_folder_id)}

        for rel_path, abs_path in found_files:
            try:
                st = os.stat(abs_path)
                file_size, file_mtime = st.st_size, st.st_mtime
            except OSError:
                file_size, file_mtime = 0, 0.0

            existing = cached_dict.get(rel_path)
            if existing and existing.size_bytes == file_size and existing.file_mtime == file_mtime:
                results.append(existing)
                continue
            if existing and not existing.probe_ok and existing.file_mtime == file_mtime:
                results.append(existing)
                continue

            probe_jobs.append((library_folder_id, rel_path, abs_path, file_size, file_mtime))

        if probe_jobs:
            probe = self._get_probe()

            def _run(job):
                fid, rel, abs_p, fsize, fmtime = job
                try:
                    snap = probe.probe(abs_p, fid)
                    snap.relative_path = rel
                    snap.file_mtime = fmtime
                    snap.probe_ok = True
                except Exception:
                    snap = FileSnapshot(
                        library_folder_id=fid,
                        relative_path=rel,
                        file_name=os.path.basename(abs_p),
                        size_bytes=fsize,
                        file_mtime=fmtime,
                        probe_ok=False,
                    )
                return snap

            if len(probe_jobs) == 1 or self.max_workers == 1:
                probed = [_run(job) for job in probe_jobs]
            else:
                with ThreadPoolExecutor(max_workers=min(self.max_workers, len(probe_jobs))) as pool:
                    probed = list(pool.map(_run, probe_jobs))

            for snap in probed:
                self._repo.save(snap)
            results.extend(probed)

        return results

    def scan_folder_fast_batch(self, library_folder_id: int, folder_path: str) -> ScanBatch:
        """快速扫描批次：返回 ScanBatch（快照 + 待探测任务），不触碰 Scanner 内部 _pending_jobs。"""
        folder_path = os.path.normpath(folder_path)
        found_files = find_video_files(folder_path)
        results: list[FileSnapshot] = []
        pending: list[tuple[int, str, str, int]] = []

        cached_dict = {s.relative_path: s for s in self._repo.load_all(library_folder_id)}

        for rel_path, abs_path in found_files:
            try:
                st = os.stat(abs_path)
                file_size, file_mtime = st.st_size, st.st_mtime
            except OSError:
                file_size, file_mtime = 0, 0.0

            existing = cached_dict.get(rel_path)
            if existing and existing.size_bytes == file_size and existing.file_mtime == file_mtime:
                results.append(existing)
                continue

            if existing and not existing.probe_ok and existing.file_mtime == file_mtime:
                results.append(existing)
                continue

            placeholder = FileSnapshot(
                library_folder_id=library_folder_id,
                relative_path=rel_path,
                file_name=os.path.basename(abs_path),
                size_bytes=file_size,
                file_mtime=file_mtime,
            )
            results.append(placeholder)
            pending.append((library_folder_id, rel_path, abs_path, file_size))

        return ScanBatch(snapshots=results, pending_jobs=pending)

    def scan_folder_fast(self, library_folder_id: int, folder_path: str) -> list[FileSnapshot]:
        """快速扫描：立即返回文件列表（优先缓存，无缓存则返回仅含文件名+体积的占位快照）。

        需要 ffprobe 的文件排队到后台，调用 probe_next() 逐个补全。
        """
        batch = self.scan_folder_fast_batch(library_folder_id, folder_path)
        with self._probe_lock:
            self._pending_jobs = list(batch.pending_jobs)
        return batch.snapshots

    @property
    def pending_count(self) -> int:
        with self._probe_lock:
            return len(self._pending_jobs)

    def probe_next(self, on_done: Optional[Callable[[FileSnapshot], None]] = None) -> bool:
        """探测队列中的下一个文件（同步，通常在后台线程调用）。返回 True 表示还有更多待探测。"""
        job = None
        with self._probe_lock:
            if self._pending_jobs:
                job = self._pending_jobs.pop(0)

        if job is None:
            return False

        folder_id, rel_path, abs_path, file_size = job
        try:
            fmtime = os.path.getmtime(abs_path)
        except OSError:
            fmtime = 0.0

        probe = self._get_probe()
        try:
            snap = probe.probe(abs_path, folder_id)
            snap.relative_path = rel_path
            snap.file_mtime = fmtime
            snap.probe_ok = True
        except Exception:
            snap = FileSnapshot(
                library_folder_id=folder_id,
                relative_path=rel_path,
                file_name=os.path.basename(abs_path),
                size_bytes=file_size,
                file_mtime=fmtime,
                probe_ok=False,
            )

        self._repo.save(snap)
        if on_done:
            on_done(snap)
        return self.pending_count > 0

    def start_background_probe_jobs(
        self,
        jobs: list[tuple[int, str, str, int]],
        on_done: Callable[[FileSnapshot], None],
        on_finished: Callable[[], None] | None = None,
        on_progress: Callable[[], None] | None = None,
    ):
        """在后台线程池并行探测指定的文件列表，每个完成后回调 on_done（在探测线程调用）"""
        import concurrent.futures

        jobs = list(jobs)

        def _probe_one(job):
            folder_id, rel_path, abs_path, file_size = job
            try:
                fmtime = os.path.getmtime(abs_path)
            except OSError:
                fmtime = 0.0
            probe = self._get_probe()
            try:
                snap = probe.probe(abs_path, folder_id)
                snap.relative_path = rel_path
                snap.file_mtime = fmtime
                snap.probe_ok = True
            except Exception:
                snap = FileSnapshot(
                    library_folder_id=folder_id,
                    relative_path=rel_path,
                    file_name=os.path.basename(abs_path),
                    size_bytes=file_size,
                    file_mtime=fmtime,
                    probe_ok=False,
                )
            self._repo.save(snap)
            if on_done:
                on_done(snap)
            if on_progress:
                on_progress()

        def _run():
            if jobs:
                workers = min(self.max_workers, len(jobs))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    list(pool.map(_probe_one, jobs))
            if on_finished:
                on_finished()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    def start_background_probe(
        self,
        on_done: Callable[[FileSnapshot], None],
        on_finished: Callable[[], None] | None = None,
        on_progress: Callable[[], None] | None = None,
    ):
        """在后台线程池并行探测所有待处理文件，每个完成后回调 on_done（在探测线程调用）"""
        with self._probe_lock:
            jobs = list(self._pending_jobs)
            self._pending_jobs = []
        return self.start_background_probe_jobs(jobs, on_done, on_finished, on_progress)
