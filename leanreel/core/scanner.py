"""文件扫描器 — 编排文件发现、FFprobe 探测与缓存，支持异步后台探测"""
import os
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

from leanreel.data.database import Database
from leanreel.data.models import FileSnapshot, HDRType
from leanreel.core.file_discovery import find_video_files
from leanreel.core.repository import SnapshotRepository


@dataclass
class ScanBatch:
    snapshots: list[FileSnapshot]
    pending_jobs: list[tuple[int, str, str, int]]


class Scanner:
    """文件夹扫描器门面：编排文件发现、FFprobe 探测与缓存，对外 API 不变。

    内部将数据持久化委托给 SnapshotRepository，将文件发现委托给模块级函数。
    """

    def __init__(self, db: Database, probe_runner=None, max_workers: int = 4):
        self._repo = SnapshotRepository(db)
        self._probe = probe_runner
        self.max_workers = max(1, max_workers)
        self._probe_lock = threading.Lock()
        self._save_lock = threading.Lock()
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
                except Exception as e:
                    snap = FileSnapshot(
                        library_folder_id=fid,
                        relative_path=rel,
                        file_name=os.path.basename(abs_p),
                        size_bytes=fsize,
                        file_mtime=fmtime,
                        probe_ok=False,
                        probe_error=str(e)[:200],
                    )
                return snap

            if len(probe_jobs) == 1 or self.max_workers == 1:
                probed = [_run(job) for job in probe_jobs]
            else:
                with ThreadPoolExecutor(max_workers=min(self.max_workers, len(probe_jobs))) as pool:
                    probed = list(pool.map(_run, probe_jobs))

            for snap in probed:
                try:
                    with self._save_lock:
                        self._repo.save(snap)
                except Exception:
                    pass
            results.extend(probed)

        return results

    def scan_folder_fast_batch(self, library_folder_id: int, folder_path: str) -> ScanBatch:
        """快速扫描批次：返回 ScanBatch（快照 + 待探测任务），不触碰 Scanner 内部 _pending_jobs。"""
        import sys as _sys3
        folder_path = os.path.normpath(folder_path)
        t0 = time.time()
        found_files = find_video_files(folder_path)
        print(f"[LeanReel] 遍历完成: {len(found_files)}个文件, {time.time()-t0:.1f}s", file=_sys3.stderr, flush=True)
        results: list[FileSnapshot] = []
        pending: list[tuple[int, str, str, int]] = []

        cached_dict = {s.relative_path: s for s in self._repo.load_all(library_folder_id)}

        for i, (rel_path, abs_path) in enumerate(found_files):
            if (i + 1) % 200 == 0:
                print(f"[LeanReel] stat进度: {i+1}/{len(found_files)}", file=_sys3.stderr, flush=True)
            try:
                st = os.stat(abs_path)
                file_size, file_mtime = st.st_size, st.st_mtime
            except OSError:
                file_size, file_mtime = 0, 0.0

            existing = cached_dict.get(rel_path)
            if existing and existing.size_bytes == file_size and existing.file_mtime == file_mtime:
                if existing.probe_ok:
                    results.append(existing)
                    continue
                # probe_ok=False 但文件未变：仍需重新探测（之前可能因临时问题失败）

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
        except Exception as e:
            snap = FileSnapshot(
                library_folder_id=folder_id,
                relative_path=rel_path,
                file_name=os.path.basename(abs_path),
                size_bytes=file_size,
                file_mtime=fmtime,
                probe_ok=False,
                probe_error=str(e)[:200],
            )

        try:
            with self._save_lock:
                self._repo.save(snap)
        except Exception as save_err:
            import sys
            print(
                f"[LeanReel] 保存快照失败: {abs_path}\n  {save_err}",
                file=sys.stderr,
                flush=True,
            )
        if on_done:
            try:
                on_done(snap)
            except Exception:
                pass
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
            last_error = None
            snap = None
            for attempt in range(2):  # 首次 + 一次重试
                try:
                    snap = probe.probe(abs_path, folder_id)
                    snap.relative_path = rel_path
                    snap.file_mtime = fmtime
                    snap.probe_ok = True
                    break
                except Exception as e:
                    last_error = e
                    if attempt == 0:
                        import sys
                        print(
                            f"[LeanReel] FFprobe 探测失败(第1次,将重试): {abs_path}\n  {e}",
                            file=sys.stderr,
                            flush=True,
                        )
            if snap is None:
                import sys
                print(
                    f"[LeanReel] FFprobe 探测失败: {abs_path}\n  {last_error}",
                    file=sys.stderr,
                    flush=True,
                )
                snap = FileSnapshot(
                    library_folder_id=folder_id,
                    relative_path=rel_path,
                    file_name=os.path.basename(abs_path),
                    size_bytes=file_size,
                    file_mtime=fmtime,
                    probe_ok=False,
                    probe_error=str(last_error)[:200],
                )
            try:
                with self._save_lock:
                    self._repo.save(snap)
            except Exception as save_err:
                import sys
                print(
                    f"[LeanReel] 保存快照失败: {abs_path}\n  {save_err}",
                    file=sys.stderr,
                    flush=True,
                )
            if on_done:
                try:
                    on_done(snap)
                except Exception:
                    pass
            if on_progress:
                try:
                    on_progress()
                except Exception:
                    pass

        def _run():
            if jobs:
                workers = min(self.max_workers, len(jobs))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_probe_one, job) for job in jobs]
                    for f in concurrent.futures.as_completed(futures):
                        try:
                            f.result()
                        except Exception:
                            pass  # _probe_one 内部已经打印过错误
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
