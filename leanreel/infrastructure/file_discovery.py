"""文件发现 — 递归扫描视频文件，便携式 I/O 操作"""
import os

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".mov", ".wmv", ".m2ts", ".mts"}


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
