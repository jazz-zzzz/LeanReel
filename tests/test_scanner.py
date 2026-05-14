"""扫描器测试"""
import pytest
from pathlib import Path
from leanreel.data.database import Database
from leanreel.data.models import Library, LibraryFolder, FileSnapshot, HDRType


class MockFFprobe:
    """模拟 FFprobe，避免依赖实际 ffprobe 二进制文件"""
    def probe(self, file_path, library_folder_id=0):
        return FileSnapshot(
            library_folder_id=library_folder_id,
            relative_path=file_path,
            file_name=Path(file_path).name,
            size_bytes=1024,
            video_codec="hevc",
            video_width=1920,
            video_height=1080,
            hdr_type=HDRType.SDR,
        )


def test_scanner_finds_video_files(tmp_path: Path):
    (tmp_path / "movie.mkv").write_text("fake")
    (tmp_path / "poster.jpg").write_text("not video")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "another.mp4").write_text("fake")

    from leanreel.core.scanner import Scanner
    db = Database(str(tmp_path / "test.db"))
    scanner = Scanner(db, probe_runner=MockFFprobe())
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))
    result = scanner.scan_folder(folder_id, str(tmp_path))
    assert len(result) == 2
    exts = {r.file_name for r in result}
    assert "movie.mkv" in exts
    assert "another.mp4" in exts


def test_scanner_caches_results(tmp_path: Path):
    (tmp_path / "movie.mkv").write_text("fake")

    from leanreel.core.scanner import Scanner
    db = Database(str(tmp_path / "test.db"))
    scanner = Scanner(db, probe_runner=MockFFprobe())
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    first = scanner.scan_folder(folder_id, str(tmp_path))
    second = scanner.scan_folder(folder_id, str(tmp_path))
    assert len(first) == len(second)
