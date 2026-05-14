"""扫描器测试"""
import json
import pytest
from pathlib import Path
from leanreel.data.database import Database
from leanreel.data.models import (
    AudioTrack,
    Library,
    LibraryFolder,
    FileSnapshot,
    HDRType,
    SubtitleTrack,
)


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


class TrackFFprobe:
    def probe(self, file_path, library_folder_id=0):
        return FileSnapshot(
            library_folder_id=library_folder_id,
            relative_path=file_path,
            file_name=Path(file_path).name,
            size_bytes=Path(file_path).stat().st_size,
            video_codec="hevc",
            video_width=3840,
            video_height=2160,
            hdr_type=HDRType.HDR10P,
            audio_tracks=[
                AudioTrack(
                    codec="truehd",
                    channels=8,
                    language="eng",
                    title="Main Atmos",
                    is_commentary=False,
                ),
                AudioTrack(
                    codec="aac",
                    channels=2,
                    language="eng",
                    title="Commentary",
                    is_commentary=True,
                ),
            ],
            subtitle_tracks=[
                SubtitleTrack(
                    codec="hdmv_pgs",
                    language="chi",
                    title="Chinese forced",
                    is_forced=True,
                )
            ],
        )


class FailingFFprobe:
    def probe(self, file_path, library_folder_id=0):
        raise AssertionError("cached scan should not call ffprobe")


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


def test_scanner_persists_tracks_as_json_and_restores_typed_snapshot(tmp_path: Path):
    (tmp_path / "movie.mkv").write_bytes(b"x" * 1024)

    from leanreel.core.scanner import Scanner

    db = Database(str(tmp_path / "test.db"))
    scanner = Scanner(db, probe_runner=TrackFFprobe())
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    scanner.scan_folder(folder_id, str(tmp_path))
    rows = db.execute(
        "SELECT audio_tracks, subtitle_tracks FROM file_snapshot WHERE library_folder_id=?",
        [folder_id],
    )
    assert json.loads(rows[0]["audio_tracks"])[0]["codec"] == "truehd"
    assert json.loads(rows[0]["subtitle_tracks"])[0]["is_forced"] is True

    cached = Scanner(db, probe_runner=FailingFFprobe()).scan_folder(folder_id, str(tmp_path))

    assert len(cached) == 1
    snapshot = cached[0]
    assert isinstance(snapshot.hdr_type, HDRType)
    assert snapshot.hdr_type is HDRType.HDR10P
    assert snapshot.audio_tracks[0] == AudioTrack(
        codec="truehd",
        channels=8,
        language="eng",
        title="Main Atmos",
        is_commentary=False,
    )
    assert snapshot.audio_tracks[1].is_commentary is True
    assert snapshot.subtitle_tracks[0] == SubtitleTrack(
        codec="hdmv_pgs",
        language="chi",
        title="Chinese forced",
        is_forced=True,
    )
