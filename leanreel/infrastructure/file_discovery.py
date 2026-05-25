"""Portable video file discovery."""
from __future__ import annotations

from dataclasses import dataclass, field
import os

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".mov", ".wmv", ".m2ts", ".mts"}


@dataclass(frozen=True)
class DiscoveryWarning:
    path: str
    error: str


@dataclass(frozen=True)
class DiscoveryReport:
    files: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[DiscoveryWarning] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return bool(self.warnings)


def discover_video_files(folder_path: str) -> DiscoveryReport:
    """Recursively discover videos and report directories that could not be read."""
    results: list[tuple[str, str]] = []
    warnings: list[DiscoveryWarning] = []
    folder_path = os.path.normpath(folder_path)

    def _walk(current: str) -> None:
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            _walk(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in VIDEO_EXTENSIONS:
                                rel_path = os.path.relpath(entry.path, folder_path)
                                results.append((rel_path, entry.path))
                    except OSError as exc:
                        warnings.append(DiscoveryWarning(entry.path, str(exc)))
        except OSError as exc:
            warnings.append(DiscoveryWarning(current, str(exc)))

    _walk(folder_path)
    return DiscoveryReport(files=results, warnings=warnings)


def find_video_files(folder_path: str) -> list[tuple[str, str]]:
    """Compatibility wrapper returning only discovered video files."""
    return discover_video_files(folder_path).files
