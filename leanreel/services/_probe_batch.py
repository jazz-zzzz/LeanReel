"""探测批次 — 后台线程池并行探测，流式回调结果"""
import os
import sys
import threading
from typing import Callable

from leanreel.domain.models import FileSnapshot
from leanreel.domain.interfaces import SnapshotStore, ProbeRunner


def is_probe_complete(snap: FileSnapshot) -> bool:
    """缓存快照是否包含完整的探测信息"""
    return bool(snap.probe_ok and snap.video_codec and snap.video_width and snap.video_height)


def probe_one(
    abs_path: str,
    rel_path: str,
    folder_id: int,
    fsize: int,
    fmtime: float,
    cache_by_folder: dict[int, dict[str, FileSnapshot]],
    repo: SnapshotStore,
    probe: ProbeRunner,
) -> FileSnapshot:
    """处理单个文件：stat → 缓存检查 → 探测 → 保存。

    纯函数，可在任意线程调用。cache_by_folder 只读。
    """
    existing = cache_by_folder.get(folder_id, {}).get(rel_path)
    if existing and existing.size_bytes == fsize and existing.file_mtime == fmtime:
        if is_probe_complete(existing):
            return existing

    last_error = None
    for attempt in range(2):
        try:
            snap = probe.probe(abs_path, folder_id)
            snap.relative_path = rel_path
            snap.file_mtime = fmtime
            snap.probe_ok = True
            if fsize > 0:
                snap.size_bytes = fsize
            try:
                repo.save(snap)
            except Exception as save_err:
                print(f"[LeanReel] 保存快照失败: {abs_path}\n  {save_err}", file=sys.stderr, flush=True)
            return snap
        except Exception as e:
            last_error = e
            if attempt == 0:
                print(f"[LeanReel] 探测失败(重试中): {abs_path}", file=sys.stderr, flush=True)

    snap = FileSnapshot(
        library_folder_id=folder_id,
        relative_path=rel_path,
        file_name=os.path.basename(abs_path),
        size_bytes=fsize,
        file_mtime=fmtime,
        probe_ok=False,
        probe_error=str(last_error)[:200] if last_error else "探测失败",
    )
    try:
        repo.save(snap)
    except Exception:
        pass
    return snap


class ProbeBatch:
    """一次探测批次：后台线程池并行执行，每个文件完成后流式回调。"""

    def __init__(
        self,
        repo: SnapshotStore,
        probe: ProbeRunner,
        max_workers: int,
        on_result: Callable[[FileSnapshot], None],
        on_finished: Callable[[], None] | None = None,
    ):
        self._repo = repo
        self._probe = probe
        self._max_workers = max_workers
        self._on_result = on_result
        self._on_finished = on_finished

    def start(
        self,
        jobs: list[tuple[int, str, str]],
        cache_by_folder: dict[int, dict[str, FileSnapshot]],
        orphan_cleanup: Callable[[], None],
    ) -> int:
        """启动探测。返回总文件数，结果通过 on_result/on_finished 回调。

        jobs: [(folder_id, rel_path, abs_path), ...]
        cache_by_folder: {folder_id: {rel_path: FileSnapshot}}
        orphan_cleanup: 全部完成后调用的清理函数
        """
        import concurrent.futures

        total = len(jobs)
        workers = min(self._max_workers, max(1, total))
        repo = self._repo
        probe = self._probe
        on_result = self._on_result
        on_finished = self._on_finished

        def _run():
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {}
                for fid, rel_path, abs_path in jobs:
                    try:
                        st = os.stat(abs_path)
                        fsize, fmtime = st.st_size, st.st_mtime
                    except OSError:
                        fsize, fmtime = 0, 0.0
                    existing = cache_by_folder.get(fid, {}).get(rel_path)
                    if (
                        existing
                        and existing.size_bytes == fsize
                        and existing.file_mtime == fmtime
                        and is_probe_complete(existing)
                    ):
                        try:
                            on_result(existing)
                        except Exception:
                            pass
                        continue
                    f = pool.submit(
                        probe_one, abs_path, rel_path, fid,
                        fsize, fmtime, cache_by_folder, repo, probe,
                    )
                    futures[f] = None
                for f in concurrent.futures.as_completed(futures):
                    try:
                        on_result(f.result())
                    except Exception:
                        pass

            orphan_cleanup()
            if on_finished:
                on_finished()

        threading.Thread(target=_run, daemon=True).start()
        return total
