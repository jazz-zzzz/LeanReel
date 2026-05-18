"""文件扫描器 — 薄门面，依赖接口，不碰 infrastructure"""
import os
from typing import Callable

from leanreel.domain.models import FileSnapshot
from leanreel.domain.interfaces import SnapshotStore, ProbeRunner
from leanreel.services._probe_batch import is_probe_complete, ProbeBatch


class Scanner:
    """文件夹扫描器门面：依赖注入 repo + probe，编排探测批次。

    Scanner 自身不 import 任何 infrastructure 模块，
    只组合 file_discovery、ProbeBatch 与注入的接口实现。
    """

    def __init__(self, repo: SnapshotStore, probe: ProbeRunner, max_workers: int = 4):
        self._repo = repo
        self._probe = probe
        self.max_workers = max(1, max_workers)

    def load_cached(self, library_folder_id: int, folder_path: str) -> list[FileSnapshot]:
        """从数据库加载已缓存的快照列表，过滤掉探测不完整的条目。毫秒级。"""
        return [s for s in self._repo.load_all(library_folder_id) if is_probe_complete(s)]

    def probe_multi(
        self,
        folders: list[tuple[int, str, list[tuple[str, str]]]],
        on_result: Callable[[FileSnapshot], None],
        on_finished: Callable[[], None] | None = None,
    ) -> int:
        """多文件夹合并探测 — 共享一个线程池，避免每个文件夹各自开池。"""
        all_jobs: list[tuple[int, str, str]] = []
        cache_by_folder: dict[int, dict[str, FileSnapshot]] = {}

        for folder_id, folder_path, files in folders:
            folder_path = os.path.normpath(folder_path)
            cache_by_folder[folder_id] = {
                s.relative_path: s for s in self._repo.load_all(folder_id)
            }
            for rel_path, abs_path in files:
                all_jobs.append((folder_id, rel_path, abs_path))

        def orphan_cleanup():
            for folder_id, _folder_path, _files in folders:
                discovered = {rel_path for fid, rel_path, _abs in all_jobs if fid == folder_id}
                self._repo.delete_orphans(folder_id, discovered)

        batch = ProbeBatch(self._repo, self._probe, self.max_workers, on_result, on_finished)
        return batch.start(all_jobs, cache_by_folder, orphan_cleanup)

    def probe_stream(
        self,
        library_folder_id: int,
        folder_path: str,
        on_result: Callable[[FileSnapshot], None],
        on_finished: Callable[[], None] | None = None,
        files: list[tuple[str, str]] | None = None,
    ) -> int:
        """单文件夹流式探测 — 调用方负责文件发现，本方法不碰 I/O。

        files 必须由调用方传入（通过 find_video_files 等基础设施函数获取）。
        """
        if files is None:
            raise ValueError("files 必须由调用方传入（使用 infrastructure.file_discovery.find_video_files）")
        cache_by_folder = {
            library_folder_id: {
                s.relative_path: s for s in self._repo.load_all(library_folder_id)
            }
        }
        jobs = [(library_folder_id, rel_path, abs_path) for rel_path, abs_path in files]

        discovered = {rel_path for rel_path, _abs in files}

        def orphan_cleanup():
            self._repo.delete_orphans(library_folder_id, discovered)

        batch = ProbeBatch(self._repo, self._probe, self.max_workers, on_result, on_finished)
        return batch.start(jobs, cache_by_folder, orphan_cleanup)
