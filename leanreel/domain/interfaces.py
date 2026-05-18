"""领域接口 — 纯 ABC，零外部依赖"""
from abc import ABC, abstractmethod
from typing import Optional
from leanreel.domain.models import FileSnapshot, Library, LibraryFolder


class SnapshotStore(ABC):
    """快照持久化的抽象接口。Infrastructure 层提供 SQLite 实现。"""

    @abstractmethod
    def load_all(self, library_folder_id: int) -> list[FileSnapshot]:
        """加载某个目录下的全部已缓存快照。"""
        ...

    @abstractmethod
    def get_cached(self, folder_id: int, rel_path: str) -> Optional[FileSnapshot]:
        """按目录+相对路径查询单条缓存快照。"""
        ...

    @abstractmethod
    def save(self, snap: FileSnapshot) -> None:
        """插入或更新快照记录。"""
        ...

    @abstractmethod
    def delete_orphans(self, folder_id: int, keep_paths: set[str]) -> None:
        """删除不再存在于磁盘上的孤儿缓存记录。"""
        ...


class LibraryStore(ABC):
    """库和文件夹持久化的抽象接口。Infrastructure 层提供 SQLite 实现。"""

    @abstractmethod
    def insert_library(self, lib: Library) -> int:
        """插入新库，返回 ID。"""
        ...

    @abstractmethod
    def get_all_libraries(self) -> list[Library]:
        """获取所有库。"""
        ...

    @abstractmethod
    def delete_library(self, lib_id: int) -> None:
        """删除库及其关联数据。"""
        ...

    @abstractmethod
    def insert_folder(self, folder: LibraryFolder) -> int:
        """插入新文件夹，返回 ID。"""
        ...

    @abstractmethod
    def get_folders_for_library(self, lib_id: int) -> list[LibraryFolder]:
        """获取指定库的所有文件夹。"""
        ...

    @abstractmethod
    def delete_folder(self, folder_id: int) -> None:
        """删除文件夹及其关联数据。"""
        ...


class ProbeRunner(ABC):
    """视频探测的抽象接口。Infrastructure 层提供 FFprobe 实现。"""

    @abstractmethod
    def probe(self, file_path: str, library_folder_id: int = 0) -> FileSnapshot:
        """对单个文件执行探测，返回完整快照。"""
        ...
