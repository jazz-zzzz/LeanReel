"""文件扫描器 — 编排文件发现、FFprobe 探测与缓存，支持异步后台探测"""
import os
import threading
from typing import Callable

from leanreel.data.database import Database
from leanreel.data.models import FileSnapshot
from leanreel.core.file_discovery import find_video_files
from leanreel.core.repository import SnapshotRepository


def is_probe_complete(snap: FileSnapshot) -> bool:
    """缓存快照是否包含完整的探测信息"""
    return bool(snap.probe_ok and snap.video_codec and snap.video_width and snap.video_height)


class Scanner:
    """文件夹扫描器门面：编排文件发现、FFprobe 探测与缓存，对外 API 不变。

    内部将数据持久化委托给 SnapshotRepository，将文件发现委托给模块级函数。
    """

    def __init__(self, db: Database, probe_runner=None, max_workers: int = 4):
        self._repo = SnapshotRepository(db)
        self._probe = probe_runner
        self.max_workers = max(1, max_workers)

    def _get_probe(self):
        if self._probe is None:
            from leanreel.executor.probe import FFprobeRunner

            self._probe = FFprobeRunner()
        return self._probe

    def load_cached(self, library_folder_id: int, folder_path: str) -> list[FileSnapshot]:
        """从数据库加载已缓存的快照列表，不走文件系统。毫秒级。"""
        return self._repo.load_all(library_folder_id)

    def probe_stream(
        self,
        library_folder_id: int,
        folder_path: str,
        on_result: Callable[[FileSnapshot], None],
        on_finished: Callable[[], None] | None = None,
        files: list[tuple[str, str]] | None = None,
    ) -> int:
        """合并 stat+ffprobe 为一次 I/O — 边扫描边输出结果。

        返回文件总数，立即开始后台探测。每个文件处理完回调 on_result
        （在工作线程调用），全部完成后回调 on_finished。

        相比两阶段 scan→probe：stat 减少一次 NAS 往返，无占位快照，
        列表即时流式渲染。
        """
        import concurrent.futures

        folder_path = os.path.normpath(folder_path)
        if files is None:
            files = find_video_files(folder_path)
        cached_dict = {s.relative_path: s for s in self._repo.load_all(library_folder_id)}
        total = len(files)

        def _process(rel_path: str, abs_path: str) -> FileSnapshot:
            # stat once
            try:
                st = os.stat(abs_path)
                fsize, fmtime = st.st_size, st.st_mtime
            except OSError:
                fsize, fmtime = 0, 0.0

            # 缓存命中：直接返回
            existing = cached_dict.get(rel_path)
            if existing and existing.size_bytes == fsize and existing.file_mtime == fmtime:
                if is_probe_complete(existing):
                    return existing

            # 缓存未命中或过期：ffprobe + 重试
            probe = self._get_probe()
            last_error = None
            for attempt in range(2):
                try:
                    snap = probe.probe(abs_path, library_folder_id)
                    snap.relative_path = rel_path
                    snap.file_mtime = fmtime
                    snap.probe_ok = True
                    try:
                        self._repo.save(snap)
                    except Exception as save_err:
                        import sys
                        print(f"[LeanReel] 保存快照失败: {abs_path}\n  {save_err}", file=sys.stderr, flush=True)
                    return snap
                except Exception as e:
                    last_error = e
                    if attempt == 0:
                        import sys
                        print(f"[LeanReel] 探测失败(重试中): {abs_path}", file=sys.stderr, flush=True)

            snap = FileSnapshot(
                library_folder_id=library_folder_id,
                relative_path=rel_path,
                file_name=os.path.basename(abs_path),
                size_bytes=fsize,
                file_mtime=fmtime,
                probe_ok=False,
                probe_error=str(last_error)[:200] if last_error else "探测失败",
            )
            try:
                self._repo.save(snap)
            except Exception:
                pass
            return snap

        def _run():
            workers = min(self.max_workers, max(1, total))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_process, r, a) for r, a in files]
                for f in concurrent.futures.as_completed(futures):
                    try:
                        on_result(f.result())
                    except Exception:
                        pass
            if on_finished:
                on_finished()

        threading.Thread(target=_run, daemon=True).start()
        return total
