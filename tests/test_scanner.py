"""扫描器测试"""
import json
import time
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


class CountingFFprobe(MockFFprobe):
    def __init__(self):
        self.calls = 0

    def probe(self, file_path, library_folder_id=0):
        self.calls += 1
        return super().probe(file_path, library_folder_id)


class SlowFFprobe(MockFFprobe):
    def __init__(self, delay: float = 0.05):
        self.delay = delay

    def probe(self, file_path, library_folder_id=0):
        time.sleep(self.delay)
        return super().probe(file_path, library_folder_id)


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


def test_scanner_reprobes_cached_snapshot_without_codec(tmp_path: Path):
    (tmp_path / "movie.mkv").write_text("fake")

    from leanreel.core.scanner import Scanner
    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))
    db.execute(
        """INSERT INTO file_snapshot
           (library_folder_id, relative_path, file_name, size_bytes, video_codec)
           VALUES (?,?,?,?,?)""",
        [folder_id, "movie.mkv", "movie.mkv", (tmp_path / "movie.mkv").stat().st_size, ""],
    )
    probe = CountingFFprobe()
    scanner = Scanner(db, probe_runner=probe)

    result = scanner.scan_folder(folder_id, str(tmp_path))

    assert probe.calls == 1
    assert result[0].video_codec == "hevc"


def test_scanner_probes_changed_files_concurrently(tmp_path: Path):
    for i in range(4):
        (tmp_path / f"movie-{i}.mkv").write_text("fake")

    from leanreel.core.scanner import Scanner
    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))
    scanner = Scanner(db, probe_runner=SlowFFprobe(), max_workers=4)

    started = time.perf_counter()
    result = scanner.scan_folder(folder_id, str(tmp_path))
    elapsed = time.perf_counter() - started

    assert len(result) == 4
    assert elapsed < 0.16


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


# ── Issue 3 测试：HDRType 无效值回退 ──

def test_hdr_type_fallback_on_invalid_value(tmp_path: Path):
    """数据库中 hdr_type 字段为无效值时，_row_to_snapshot 应回退到 SDR 而非崩溃。"""
    from leanreel.core.scanner import SnapshotRepository

    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    # 手动插入一条 hdr_type 为无效值的记录
    file_path = tmp_path / "movie.mkv"
    file_path.write_text("fake")
    file_size = file_path.stat().st_size
    db.execute(
        """INSERT INTO file_snapshot
           (library_folder_id, relative_path, file_name, size_bytes, hdr_type)
           VALUES (?,?,?,?,?)""",
        [folder_id, "movie.mkv", "movie.mkv", file_size, "INVALID_HDR_TYPE"],
    )

    repo = SnapshotRepository(db)
    snapshots = repo.load_all(folder_id)

    assert len(snapshots) == 1
    assert snapshots[0].hdr_type is HDRType.SDR


def test_hdr_type_fallback_on_empty_string(tmp_path: Path):
    """数据库中 hdr_type 为空字符串时也应回退到 SDR。"""
    from leanreel.core.scanner import SnapshotRepository

    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    file_path = tmp_path / "movie.mkv"
    file_path.write_text("fake")
    file_size = file_path.stat().st_size
    db.execute(
        """INSERT INTO file_snapshot
           (library_folder_id, relative_path, file_name, size_bytes, hdr_type)
           VALUES (?,?,?,?,?)""",
        [folder_id, "movie.mkv", "movie.mkv", file_size, ""],
    )

    repo = SnapshotRepository(db)
    snapshots = repo.load_all(folder_id)

    assert len(snapshots) == 1
    assert snapshots[0].hdr_type is HDRType.SDR


# ── Issue 2 测试：SQLITE_BUSY 重试 ──

class BusyThenOkDatabase:
    """模拟 Database：前 N 次 execute 抛出 database is locked，然后成功。"""

    def __init__(self, db: Database, busy_count: int):
        self._real = db
        self._busy_count = busy_count
        self.call_count = 0

    def execute(self, sql: str, params=None):
        self.call_count += 1
        if self.call_count <= self._busy_count:
            raise Exception("database is locked")
        return self._real.execute(sql, params)


def test_save_retries_on_busy(tmp_path: Path):
    """save() 遇到 SQLITE_BUSY 时应重试，最多 3 次后或成功后返回。"""
    from leanreel.core.scanner import SnapshotRepository

    real_db = Database(str(tmp_path / "test.db"))
    lib_id = real_db.insert_library(Library(name="Test"))
    folder_id = real_db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    # 前 1 次 execute 抛出 locked，第 2 次成功
    busy_db = BusyThenOkDatabase(real_db, busy_count=1)
    repo = SnapshotRepository(busy_db)

    snap = FileSnapshot(
        library_folder_id=folder_id,
        relative_path="test.mkv",
        file_name="test.mkv",
        size_bytes=100,
    )

    # 不应抛出异常
    repo.save(snap)

    # 验证重试确实发生了：call_count 应为 2（1 次失败 + 1 次成功）
    assert busy_db.call_count >= 2

    # 验证数据实际被写入了真实数据库
    rows = real_db.execute(
        "SELECT * FROM file_snapshot WHERE library_folder_id=? AND relative_path=?",
        [folder_id, "test.mkv"],
    )
    assert len(rows) == 1
    assert rows[0]["file_name"] == "test.mkv"


def test_save_exhausts_retries_and_raises(tmp_path: Path):
    """save() 重试耗尽后应抛出异常。"""
    from leanreel.core.scanner import SnapshotRepository

    real_db = Database(str(tmp_path / "test.db"))
    lib_id = real_db.insert_library(Library(name="Test"))
    folder_id = real_db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    # 每次都抛出 locked，永不成功
    busy_db = BusyThenOkDatabase(real_db, busy_count=999)
    repo = SnapshotRepository(busy_db)

    snap = FileSnapshot(
        library_folder_id=folder_id,
        relative_path="test.mkv",
        file_name="test.mkv",
        size_bytes=100,
    )

    with pytest.raises(Exception, match="database is locked"):
        repo.save(snap)

    # 验证重试了 3 次
    assert busy_db.call_count == 3


def test_fast_scan_batches_keep_independent_pending_jobs(tmp_path: Path):
    from leanreel.core.scanner import Scanner

    db = Database(str(tmp_path / "scan_batch.db"))
    try:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "a.mkv").write_bytes(b"first")
        (second / "b.mkv").write_bytes(b"second")

        scanner = Scanner(db, probe_runner=MockFFprobe(), max_workers=1)
        first_batch = scanner.scan_folder_fast_batch(1, str(first))
        second_batch = scanner.scan_folder_fast_batch(2, str(second))

        assert [job[1] for job in first_batch.pending_jobs] == ["a.mkv"]
        assert [job[1] for job in second_batch.pending_jobs] == ["b.mkv"]
    finally:
        db.close()


def test_save_does_not_retry_non_busy_errors(tmp_path: Path):
    """save() 不应重试非 SQLITE_BUSY 错误。"""
    from leanreel.core.scanner import SnapshotRepository

    class NonBusyErrorDatabase:
        def execute(self, sql, params=None):
            raise ValueError("something else broke")

    repo = SnapshotRepository(NonBusyErrorDatabase())

    snap = FileSnapshot(
        library_folder_id=1,
        relative_path="test.mkv",
        file_name="test.mkv",
        size_bytes=100,
    )

    with pytest.raises(ValueError, match="something else broke"):
        repo.save(snap)
