"""扫描器测试"""
import json
import threading
import time
import pytest
from pathlib import Path
from leanreel.infrastructure.database import Database
from leanreel.infrastructure.repository import SnapshotRepository
from leanreel.domain.models import (
    AudioTrack,
    Library,
    LibraryFolder,
    FileSnapshot,
    HDRType,
    SubtitleTrack,
)


def _probe_sync(scanner, folder_id, folder_path):
    """同步包装 probe_stream，便利测试。"""
    from leanreel.infrastructure.file_discovery import find_video_files
    results = []
    event = threading.Event()

    def on_result(snap):
        results.append(snap)

    def on_finished():
        event.set()

    files = find_video_files(folder_path)
    scanner.probe_stream(folder_id, folder_path, on_result, on_finished, files=files)
    event.wait(timeout=10)
    return results


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

    from leanreel.services.scanner import Scanner
    db = Database(str(tmp_path / "test.db"))
    scanner = Scanner(repo=SnapshotRepository(db), probe=MockFFprobe())
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))
    result = _probe_sync(scanner, folder_id, str(tmp_path))
    assert len(result) == 2
    exts = {r.file_name for r in result}
    assert "movie.mkv" in exts
    assert "another.mp4" in exts


def test_scanner_caches_results(tmp_path: Path):
    (tmp_path / "movie.mkv").write_text("fake")

    from leanreel.services.scanner import Scanner
    db = Database(str(tmp_path / "test.db"))
    scanner = Scanner(repo=SnapshotRepository(db), probe=MockFFprobe())
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    first = _probe_sync(scanner, folder_id, str(tmp_path))
    second = _probe_sync(scanner, folder_id, str(tmp_path))
    assert len(first) == len(second)


def test_scanner_reprobes_cached_snapshot_without_codec(tmp_path: Path):
    (tmp_path / "movie.mkv").write_text("fake")

    from leanreel.services.scanner import Scanner
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
    scanner = Scanner(repo=SnapshotRepository(db), probe=probe)

    result = _probe_sync(scanner, folder_id, str(tmp_path))

    assert probe.calls == 1
    assert result[0].video_codec == "hevc"


def test_scanner_probes_changed_files_concurrently(tmp_path: Path):
    for i in range(4):
        (tmp_path / f"movie-{i}.mkv").write_text("fake")

    from leanreel.services.scanner import Scanner
    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))
    scanner = Scanner(repo=SnapshotRepository(db), probe=SlowFFprobe(), max_workers=4)

    started = time.perf_counter()
    result = _probe_sync(scanner, folder_id, str(tmp_path))
    elapsed = time.perf_counter() - started

    assert len(result) == 4
    assert elapsed < 0.16


def test_scanner_persists_tracks_as_json_and_restores_typed_snapshot(tmp_path: Path):
    (tmp_path / "movie.mkv").write_bytes(b"x" * 1024)

    from leanreel.services.scanner import Scanner

    db = Database(str(tmp_path / "test.db"))
    scanner = Scanner(repo=SnapshotRepository(db), probe=TrackFFprobe())
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    _probe_sync(scanner, folder_id, str(tmp_path))
    rows = db.execute(
        "SELECT audio_tracks, subtitle_tracks FROM file_snapshot WHERE library_folder_id=?",
        [folder_id],
    )
    assert json.loads(rows[0]["audio_tracks"])[0]["codec"] == "truehd"
    assert json.loads(rows[0]["subtitle_tracks"])[0]["is_forced"] is True

    cached = _probe_sync(Scanner(repo=SnapshotRepository(db), probe=FailingFFprobe()), folder_id, str(tmp_path))

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
    from leanreel.infrastructure.repository import SnapshotRepository

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
    from leanreel.infrastructure.repository import SnapshotRepository

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
    from leanreel.infrastructure.repository import SnapshotRepository

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
    from leanreel.infrastructure.repository import SnapshotRepository

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


def test_probe_stream_isolates_folders(tmp_path: Path):
    """probe_stream 区分不同文件夹，各自产生正确结果。"""
    from leanreel.services.scanner import Scanner

    db = Database(str(tmp_path / "isolated.db"))
    try:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "a.mkv").write_bytes(b"first")
        (second / "b.mkv").write_bytes(b"second")

        scanner = Scanner(repo=SnapshotRepository(db), probe=MockFFprobe(), max_workers=1)
        results1 = _probe_sync(scanner, 1, str(first))
        results2 = _probe_sync(scanner, 2, str(second))

        assert len(results1) == 1
        assert results1[0].file_name == "a.mkv"
        assert results1[0].library_folder_id == 1
        assert len(results2) == 1
        assert results2[0].file_name == "b.mkv"
        assert results2[0].library_folder_id == 2
    finally:
        db.close()


# ── load_cached 完整性过滤 ──


def test_load_cached_filters_out_incomplete_probe(tmp_path: Path):
    """load_cached 应过滤 probe_ok=True 但 codec/width/height 为空的旧版缓存。"""
    from leanreel.services.scanner import Scanner

    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    # 插入不完整缓存：probe_ok=1 但 codec 为空（老版本产生的脏数据）
    db.execute(
        """INSERT INTO file_snapshot
           (library_folder_id, relative_path, file_name, size_bytes,
            video_codec, video_width, video_height, probe_ok)
           VALUES (?,?,?,?,?,?,?,?)""",
        [folder_id, "incomplete.mkv", "incomplete.mkv", 1024, "", 0, 0, 1],
    )
    # 插入完整缓存
    from leanreel.infrastructure.repository import SnapshotRepository
    repo = SnapshotRepository(db)
    from leanreel.domain.models import FileSnapshot
    snap = FileSnapshot(
        library_folder_id=folder_id,
        relative_path="complete.mkv",
        file_name="complete.mkv",
        size_bytes=2048,
        video_codec="hevc",
        video_width=1920,
        video_height=1080,
        probe_ok=True,
    )
    repo.save(snap)

    scanner = Scanner(repo=SnapshotRepository(db), probe=MockFFprobe())
    results = scanner.load_cached(folder_id, str(tmp_path))

    assert len(results) == 1
    assert results[0].relative_path == "complete.mkv"


def test_load_cached_filters_out_probe_failed(tmp_path: Path):
    """load_cached 应过滤 probe_ok=False 的条目（探测失败不应出现在快速加载中）。"""
    from leanreel.services.scanner import Scanner

    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    db.execute(
        """INSERT INTO file_snapshot
           (library_folder_id, relative_path, file_name, size_bytes,
            video_codec, video_width, video_height, probe_ok, probe_error)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        [folder_id, "failed.mkv", "failed.mkv", 1024, "", 0, 0, 0, "timeout"],
    )

    scanner = Scanner(repo=SnapshotRepository(db), probe=MockFFprobe())
    results = scanner.load_cached(folder_id, str(tmp_path))

    assert len(results) == 0


def test_load_cached_returns_all_complete(tmp_path: Path):
    """load_cached 应返回所有完整缓存的条目。"""
    from leanreel.services.scanner import Scanner
    from leanreel.infrastructure.repository import SnapshotRepository

    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    repo = SnapshotRepository(db)
    for i in range(5):
        snap = FileSnapshot(
            library_folder_id=folder_id,
            relative_path=f"movie_{i}.mkv",
            file_name=f"movie_{i}.mkv",
            size_bytes=1024 * (i + 1),
            video_codec="hevc",
            video_width=3840,
            video_height=2160,
            probe_ok=True,
        )
        repo.save(snap)

    scanner = Scanner(repo=SnapshotRepository(db), probe=MockFFprobe())
    results = scanner.load_cached(folder_id, str(tmp_path))

    assert len(results) == 5


# ── 孤儿清理 ──


def test_probe_stream_cleans_orphan_cache(tmp_path: Path):
    """probe_stream 完成扫描后应删除已不在磁盘上的孤儿缓存。"""
    from leanreel.services.scanner import Scanner
    from leanreel.infrastructure.repository import SnapshotRepository

    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    # 预先插入一条孤儿缓存（文件不在磁盘上）
    repo = SnapshotRepository(db)
    snap = FileSnapshot(
        library_folder_id=folder_id,
        relative_path="gone.mkv",
        file_name="gone.mkv",
        size_bytes=9999,
        video_codec="hevc",
        video_width=1920,
        video_height=1080,
        probe_ok=True,
    )
    repo.save(snap)

    # 磁盘上只有一个实际文件
    (tmp_path / "real.mkv").write_text("fake")

    scanner = Scanner(repo=SnapshotRepository(db), probe=MockFFprobe())
    _probe_sync(scanner, folder_id, str(tmp_path))

    # 孤儿应被清理
    remaining = repo.load_all(folder_id)
    rel_paths = {s.relative_path for s in remaining}
    assert "gone.mkv" not in rel_paths
    assert "real.mkv" in rel_paths


def test_probe_stream_keeps_cache_when_no_orphans(tmp_path: Path):
    """磁盘文件与缓存一致时，不应误删任何记录。"""
    from leanreel.services.scanner import Scanner
    from leanreel.infrastructure.repository import SnapshotRepository

    db = Database(str(tmp_path / "test.db"))
    lib_id = db.insert_library(Library(name="Test"))
    folder_id = db.insert_folder(LibraryFolder(library_id=lib_id, path=str(tmp_path)))

    (tmp_path / "a.mkv").write_text("first")
    (tmp_path / "b.mkv").write_text("second")

    # 先扫一次建立缓存
    scanner = Scanner(repo=SnapshotRepository(db), probe=MockFFprobe())
    _probe_sync(scanner, folder_id, str(tmp_path))

    # 再扫一次，缓存不应被删除
    scanner2 = Scanner(repo=SnapshotRepository(db), probe=FailingFFprobe())
    _probe_sync(scanner2, folder_id, str(tmp_path))

    repo = SnapshotRepository(db)
    remaining = repo.load_all(folder_id)
    assert len(remaining) == 2


def test_save_does_not_retry_non_busy_errors(tmp_path: Path):
    """save() 不应重试非 SQLITE_BUSY 错误。"""
    from leanreel.infrastructure.repository import SnapshotRepository

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
