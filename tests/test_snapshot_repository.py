"""SnapshotRepository 单元测试 — 覆盖 load_all、get_cached、save（upsert）、JSON 序列化/反序列化往返

所有测试使用非平凡真实数据，满足 TDD 防逃逸规则。
"""
import json
import pytest
from pathlib import Path

from leanreel.data.database import Database
from leanreel.data.models import (
    AudioTrack,
    FileSnapshot,
    HDRType,
    Library,
    LibraryFolder,
    SubtitleTrack,
)
from leanreel.core.scanner import SnapshotRepository


# ── fixtures ──

@pytest.fixture
def db(tmp_path: Path):
    """为每个测试提供独立的 Database 实例。"""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    yield database
    database.close()


@pytest.fixture
def repo(db: Database) -> SnapshotRepository:
    return SnapshotRepository(db)


@pytest.fixture
def folder_id(db: Database) -> int:
    """创建一个 Library + LibraryFolder，返回 folder_id。"""
    lib_id = db.insert_library(Library(name="Test Library"))
    return db.insert_folder(LibraryFolder(library_id=lib_id, path="C:/media/movies"))


@pytest.fixture
def second_folder_id(db: Database) -> int:
    """第二个 LibraryFolder，用于隔离测试。"""
    lib_id = db.insert_library(Library(name="Second Library"))
    return db.insert_folder(LibraryFolder(library_id=lib_id, path="D:/shows"))


# ── 辅助函数 ──

def make_snap(
    folder_id: int,
    rel_path: str = "Movies/Action/Film (2024).mkv",
    file_name: str = "Film (2024).mkv",
    size_bytes: int = 4_500_000_000,
    video_codec: str = "hevc",
    video_width: int = 3840,
    video_height: int = 2160,
    hdr_type: HDRType = HDRType.HDR10P,
    audio_tracks: list | None = None,
    subtitle_tracks: list | None = None,
    duration_seconds: float = 7620.5,
    bitrate_bps: int = 48_000_000,
    file_mtime: float = 1715000000.0,
    probe_ok: bool = True,
) -> FileSnapshot:
    """工厂函数：创建带非平凡值的 FileSnapshot。"""
    if audio_tracks is None:
        audio_tracks = [
            AudioTrack(codec="truehd", channels=8, language="eng", title="Atmos 7.1", is_commentary=False),
            AudioTrack(codec="ac3", channels=6, language="jpn", title="Japanese 5.1", is_commentary=False),
            AudioTrack(codec="aac", channels=2, language="eng", title="Director Commentary", is_commentary=True),
        ]
    if subtitle_tracks is None:
        subtitle_tracks = [
            SubtitleTrack(codec="hdmv_pgs", language="chi", title="Chinese Simplified", is_forced=False),
            SubtitleTrack(codec="hdmv_pgs", language="chi", title="Chinese Forced", is_forced=True),
            SubtitleTrack(codec="subrip", language="eng", title="English SDH", is_forced=False),
        ]
    return FileSnapshot(
        library_folder_id=folder_id,
        relative_path=rel_path,
        file_name=file_name,
        size_bytes=size_bytes,
        video_codec=video_codec,
        video_width=video_width,
        video_height=video_height,
        hdr_type=hdr_type,
        audio_tracks=audio_tracks,
        subtitle_tracks=subtitle_tracks,
        duration_seconds=duration_seconds,
        bitrate_bps=bitrate_bps,
        file_mtime=file_mtime,
        probe_ok=probe_ok,
    )


# ── load_all ──

def test_load_all_returns_all_snapshots_for_given_folder(repo, folder_id, second_folder_id):
    """保存 3 个快照（2 个属于文件夹 A，1 个属于文件夹 B），load_all 只返回文件夹 A 的 2 个。"""
    repo.save(make_snap(folder_id, rel_path="Movies/Action/Fury Road.mkv"))
    repo.save(make_snap(folder_id, rel_path="Movies/Comedy/Paddington 2.mkv"))
    repo.save(make_snap(second_folder_id, rel_path="Shows/Drama/Breaking Bad.mkv"))

    results = repo.load_all(folder_id)

    assert len(results) == 2
    rel_paths = {snap.relative_path for snap in results}
    assert "Movies/Action/Fury Road.mkv" in rel_paths
    assert "Movies/Comedy/Paddington 2.mkv" in rel_paths
    # 验证返回的是完整的 FileSnapshot 对象（而非仅路径）
    for snap in results:
        assert isinstance(snap, FileSnapshot)
        assert snap.library_folder_id == folder_id


def test_load_all_returns_snapshots_sorted_by_relative_path(repo, folder_id):
    """load_all 应按 relative_path ASC 排序，而不是按插入顺序。"""
    repo.save(make_snap(folder_id, rel_path="C.mkv", file_name="C.mkv"))
    repo.save(make_snap(folder_id, rel_path="A.mkv", file_name="A.mkv"))
    repo.save(make_snap(folder_id, rel_path="B.mkv", file_name="B.mkv"))

    results = repo.load_all(folder_id)

    paths = [snap.relative_path for snap in results]
    assert paths == ["A.mkv", "B.mkv", "C.mkv"]


def test_load_all_returns_empty_list_for_folder_with_no_snapshots(repo, folder_id):
    """对没有任何快照的文件夹，load_all 应返回空列表。"""
    results = repo.load_all(folder_id)
    assert results == []
    assert isinstance(results, list)


# ── get_cached ──

def test_get_cached_returns_snapshot_on_cache_hit(repo, folder_id):
    """先 save 后 get_cached 应返回完整快照。"""
    snap = make_snap(
        folder_id,
        rel_path="Movies/Sci-Fi/Inception.mkv",
        video_codec="av1",
        video_width=3840,
        video_height=1600,
        hdr_type=HDRType.DV_P7,
    )
    repo.save(snap)

    cached = repo.get_cached(folder_id, "Movies/Sci-Fi/Inception.mkv")

    assert cached is not None
    assert isinstance(cached, FileSnapshot)
    assert cached.relative_path == "Movies/Sci-Fi/Inception.mkv"
    assert cached.video_codec == "av1"
    assert cached.video_width == 3840
    assert cached.video_height == 1600
    assert cached.hdr_type is HDRType.DV_P7


def test_get_cached_returns_none_for_unknown_path(repo, folder_id):
    """查询不存在的相对路径应返回 None。"""
    repo.save(make_snap(folder_id, rel_path="Movies/Drama/Parasite.mkv"))

    result = repo.get_cached(folder_id, "Movies/Drama/Nonexistent.mkv")
    assert result is None


def test_get_cached_returns_none_for_unknown_folder(repo, folder_id):
    """查询不存在的文件夹 ID 应返回 None。"""
    repo.save(make_snap(folder_id, rel_path="Movies/Drama/Parasite.mkv"))

    result = repo.get_cached(folder_id + 99999, "Movies/Drama/Parasite.mkv")
    assert result is None


def test_get_cached_with_multiple_snapshots_returns_correct_one(repo, folder_id):
    """多条记录存在时，get_cached 应精准匹配并仅返回目标快照。"""
    repo.save(make_snap(folder_id, rel_path="A.mkv", file_name="A.mkv", video_codec="h264"))
    repo.save(make_snap(folder_id, rel_path="B.mkv", file_name="B.mkv", video_codec="hevc"))
    repo.save(make_snap(folder_id, rel_path="C.mkv", file_name="C.mkv", video_codec="av1"))

    cached = repo.get_cached(folder_id, "B.mkv")

    assert cached is not None
    assert cached.relative_path == "B.mkv"
    assert cached.video_codec == "hevc"


# ── save ──

def test_save_inserts_new_snapshot_with_all_fields_intact(repo, folder_id):
    """save 后 load_all 应返回字段完整无损的快照。"""
    snap = make_snap(
        folder_id,
        rel_path="Movies/Epic/Interstellar (2014).mkv",
        file_name="Interstellar (2014).mkv",
        size_bytes=12_345_678_901,
        video_codec="hevc",
        video_width=3840,
        video_height=2160,
        hdr_type=HDRType.HDR10,
        duration_seconds=10140.0,
        bitrate_bps=55_000_000,
        file_mtime=1716000000.5,
        probe_ok=True,
    )
    repo.save(snap)

    results = repo.load_all(folder_id)

    assert len(results) == 1
    loaded = results[0]
    assert loaded.relative_path == "Movies/Epic/Interstellar (2014).mkv"
    assert loaded.file_name == "Interstellar (2014).mkv"
    assert loaded.size_bytes == 12_345_678_901
    assert loaded.video_codec == "hevc"
    assert loaded.video_width == 3840
    assert loaded.video_height == 2160
    assert loaded.hdr_type is HDRType.HDR10
    assert loaded.duration_seconds == 10140.0
    assert loaded.bitrate_bps == 55_000_000
    assert loaded.file_mtime == 1716000000.5
    assert loaded.probe_ok is True
    assert len(loaded.audio_tracks) == 3
    assert len(loaded.subtitle_tracks) == 3


def test_save_upserts_existing_snapshot_with_new_values(repo, folder_id):
    """对同一 (library_folder_id, relative_path) 再次 save，应更新记录（upsert）。"""
    snap1 = make_snap(
        folder_id,
        rel_path="Movies/Action/John Wick.mkv",
        size_bytes=8_000_000_000,
        video_codec="h264",
        video_width=1920,
        video_height=1080,
    )
    repo.save(snap1)

    # 修改多个字段后再次保存
    snap2 = make_snap(
        folder_id,
        rel_path="Movies/Action/John Wick.mkv",
        size_bytes=8_500_000_000,
        video_codec="av1",
        video_width=3840,
        video_height=2160,
    )
    repo.save(snap2)

    results = repo.load_all(folder_id)
    assert len(results) == 1, "upsert 不应创建新行"
    loaded = results[0]
    assert loaded.size_bytes == 8_500_000_000
    assert loaded.video_codec == "av1"
    assert loaded.video_width == 3840
    assert loaded.video_height == 2160


def test_save_upsert_updates_file_name_on_conflict(repo, folder_id):
    """file_name 现在在 DO UPDATE SET 中 → upsert 时应更新为新值。"""
    snap1 = make_snap(
        folder_id,
        rel_path="Movies/Horror/The Thing.mkv",
        file_name="The Thing (1982).mkv",
    )
    repo.save(snap1)

    # 第二次 save 时修改 file_name（现在 upsert 会更新该字段）
    snap2 = make_snap(
        folder_id,
        rel_path="Movies/Horror/The Thing.mkv",
        file_name="The Thing (Different Name).mkv",
        video_codec="vp9",  # 用其他字段的变化来区分是第二次插入
    )
    repo.save(snap2)

    loaded = repo.get_cached(folder_id, "Movies/Horror/The Thing.mkv")
    assert loaded is not None
    assert loaded.file_name == "The Thing (Different Name).mkv", "file_name 现在在 ON CONFLICT UPDATE SET 中，应更新为第二次的值"
    assert loaded.video_codec == "vp9", "其他字段仍应正常更新"


def test_save_multiple_then_load_all_is_complete(repo, folder_id):
    """往返测试：保存 3 个不同文件的快照，加载回来验证完整性和数量。"""
    files = [
        ("Movies/Drama/The Godfather.mkv", "The Godfather.mkv", 9_000_000_000, "h264", HDRType.SDR, 10530.0),
        ("Movies/Sci-Fi/The Matrix.mkv", "The Matrix.mkv", 12_000_000_000, "hevc", HDRType.HDR10, 8100.0),
        ("Movies/Animation/Spirited Away.mkv", "Spirited Away.mkv", 6_500_000_000, "av1", HDRType.DV_P8, 7560.0),
    ]

    for rel_path, fname, size, codec, hdr, dur in files:
        repo.save(make_snap(
            folder_id,
            rel_path=rel_path,
            file_name=fname,
            size_bytes=size,
            video_codec=codec,
            hdr_type=hdr,
            duration_seconds=dur,
        ))

    results = repo.load_all(folder_id)
    assert len(results) == 3

    result_map = {snap.relative_path: snap for snap in results}

    godfather = result_map["Movies/Drama/The Godfather.mkv"]
    assert godfather.size_bytes == 9_000_000_000
    assert godfather.video_codec == "h264"
    assert godfather.hdr_type is HDRType.SDR
    assert godfather.duration_seconds == 10530.0

    matrix = result_map["Movies/Sci-Fi/The Matrix.mkv"]
    assert matrix.size_bytes == 12_000_000_000
    assert matrix.video_codec == "hevc"
    assert matrix.hdr_type is HDRType.HDR10
    assert matrix.duration_seconds == 8100.0

    spirited = result_map["Movies/Animation/Spirited Away.mkv"]
    assert spirited.size_bytes == 6_500_000_000
    assert spirited.video_codec == "av1"
    assert spirited.hdr_type is HDRType.DV_P8
    assert spirited.duration_seconds == 7560.0


# ── 音轨 JSON 往返 ──

def test_audio_tracks_json_roundtrip_includes_commentary_flag(repo, folder_id):
    """包含评论音轨（is_commentary=True）的音频轨道经过 JSON 序列化/反序列化后不丢失字段。"""
    tracks = [
        AudioTrack(codec="truehd", channels=8, language="eng", title="Dolby Atmos", is_commentary=False),
        AudioTrack(codec="ac3", channels=6, language="eng", title="5.1 Surround", is_commentary=False),
        AudioTrack(codec="aac", channels=2, language="eng", title="Film Commentary", is_commentary=True),
        AudioTrack(codec="aac", channels=2, language="jpn", title="Japanese Commentary", is_commentary=True),
    ]
    snap = make_snap(folder_id, rel_path="Movies/Big Budget.mkv", audio_tracks=tracks, subtitle_tracks=[])
    repo.save(snap)

    loaded = repo.get_cached(folder_id, "Movies/Big Budget.mkv")
    assert loaded is not None
    assert len(loaded.audio_tracks) == 4

    # 验证字段完整性（非评论音轨）
    assert loaded.audio_tracks[0].codec == "truehd"
    assert loaded.audio_tracks[0].channels == 8
    assert loaded.audio_tracks[0].language == "eng"
    assert loaded.audio_tracks[0].title == "Dolby Atmos"
    assert loaded.audio_tracks[0].is_commentary is False

    # 验证评论音轨的标志被正确保留
    assert loaded.audio_tracks[2].is_commentary is True
    assert loaded.audio_tracks[2].codec == "aac"
    assert loaded.audio_tracks[2].channels == 2
    assert loaded.audio_tracks[2].title == "Film Commentary"
    assert loaded.audio_tracks[2].language == "eng"

    assert loaded.audio_tracks[3].is_commentary is True
    assert loaded.audio_tracks[3].language == "jpn"

    # 验证从 JSON 读取后类型正确
    for track in loaded.audio_tracks:
        assert isinstance(track, AudioTrack)
        assert isinstance(track.is_commentary, bool)
        assert isinstance(track.channels, int)


def test_subtitle_tracks_json_roundtrip_includes_forced_flag(repo, folder_id):
    """包含强制字幕（is_forced=True）的字幕轨道经过 JSON 序列化/反序列化后不丢失。"""
    tracks = [
        SubtitleTrack(codec="hdmv_pgs", language="eng", title="English Full", is_forced=False),
        SubtitleTrack(codec="hdmv_pgs", language="eng", title="English Forced (Signs & Alien Speech)", is_forced=True),
        SubtitleTrack(codec="subrip", language="chi", title="Chinese Simplified", is_forced=False),
        SubtitleTrack(codec="ass", language="chi", title="Chinese Forced", is_forced=True),
        SubtitleTrack(codec="hdmv_pgs", language="kor", title="Korean", is_forced=False),
    ]
    snap = make_snap(folder_id, rel_path="Movies/Sci-Fi/Arrival.mkv", audio_tracks=[], subtitle_tracks=tracks)
    repo.save(snap)

    loaded = repo.get_cached(folder_id, "Movies/Sci-Fi/Arrival.mkv")
    assert loaded is not None
    assert len(loaded.subtitle_tracks) == 5

    # 验证普通字幕
    assert loaded.subtitle_tracks[0].codec == "hdmv_pgs"
    assert loaded.subtitle_tracks[0].language == "eng"
    assert loaded.subtitle_tracks[0].is_forced is False

    # 验证强制字幕标志被正确保留
    assert loaded.subtitle_tracks[1].is_forced is True
    assert loaded.subtitle_tracks[1].codec == "hdmv_pgs"
    assert loaded.subtitle_tracks[1].language == "eng"
    assert loaded.subtitle_tracks[1].title == "English Forced (Signs & Alien Speech)"

    assert loaded.subtitle_tracks[3].is_forced is True
    assert loaded.subtitle_tracks[3].codec == "ass"

    # 验证类型正确
    for track in loaded.subtitle_tracks:
        assert isinstance(track, SubtitleTrack)
        assert isinstance(track.is_forced, bool)


def test_multiple_audio_tracks_with_various_codecs_survive_roundtrip(repo, folder_id):
    """多种编解码器（truehd, dts, ac3, aac, flac, opus）的音轨往返后完整性验证。"""
    tracks = [
        AudioTrack(codec="truehd", channels=8, language="eng", title="Atmos 7.1.4"),
        AudioTrack(codec="dts", channels=6, language="fra", title="DTS 5.1"),
        AudioTrack(codec="ac3", channels=2, language="spa", title="Spanish Stereo"),
        AudioTrack(codec="aac", channels=2, language="eng", title="Commentary", is_commentary=True),
        AudioTrack(codec="flac", channels=2, language="jpn", title="FLAC 2.0"),
        AudioTrack(codec="opus", channels=6, language="deu", title="Opus 5.1"),
    ]
    snap = make_snap(folder_id, rel_path="Movies/MultiLang.mkv", audio_tracks=tracks, subtitle_tracks=[])
    repo.save(snap)

    loaded = repo.get_cached(folder_id, "Movies/MultiLang.mkv")
    assert loaded is not None
    assert len(loaded.audio_tracks) == 6

    codecs_found = {t.codec for t in loaded.audio_tracks}
    assert codecs_found == {"truehd", "dts", "ac3", "aac", "flac", "opus"}

    languages_found = {t.language for t in loaded.audio_tracks}
    assert languages_found == {"eng", "fra", "spa", "jpn", "deu"}

    channels_found = {t.channels for t in loaded.audio_tracks}
    assert channels_found == {8, 6, 2}


def test_empty_track_lists_survive_roundtrip(repo, folder_id):
    """空音轨/字幕列表应正确往返，不丢失/不产生虚假条目。"""
    snap = make_snap(
        folder_id,
        rel_path="Movies/No Tracks.mkv",
        audio_tracks=[],
        subtitle_tracks=[],
    )
    repo.save(snap)

    loaded = repo.get_cached(folder_id, "Movies/No Tracks.mkv")
    assert loaded is not None
    assert loaded.audio_tracks == []
    assert loaded.subtitle_tracks == []
    assert isinstance(loaded.audio_tracks, list)
    assert isinstance(loaded.subtitle_tracks, list)


def test_all_hdr_types_survive_roundtrip(repo, folder_id):
    """验证所有 6 个 HDRType 枚举值在存储/加载后正确还原。"""
    hdr_map = {
        "SDR.mkv": HDRType.SDR,
        "HDR10.mkv": HDRType.HDR10,
        "HDR10+.mkv": HDRType.HDR10P,
        "DV_P5.mkv": HDRType.DV_P5,
        "DV_P7.mkv": HDRType.DV_P7,
        "DV_P8.mkv": HDRType.DV_P8,
    }

    for rel_path, hdr_type in hdr_map.items():
        repo.save(make_snap(folder_id, rel_path=rel_path, hdr_type=hdr_type))

    results = repo.load_all(folder_id)
    assert len(results) == 6

    for snap in results:
        expected = hdr_map[snap.relative_path]
        assert snap.hdr_type is expected, (
            f"expected {expected} for {snap.relative_path}, got {snap.hdr_type}"
        )
        assert isinstance(snap.hdr_type, HDRType)


def test_single_track_survives_roundtrip(repo, folder_id):
    """单条音轨+单条字幕的往返：验证不产生多余条目。"""
    tracks = [
        AudioTrack(codec="eac3", channels=8, language="eng", title="E-AC3 7.1", is_commentary=False),
    ]
    subs = [
        SubtitleTrack(codec="subrip", language="eng", title="English", is_forced=False),
    ]
    repo.save(make_snap(
        folder_id,
        rel_path="Movies/Single Track.mkv",
        audio_tracks=tracks,
        subtitle_tracks=subs,
    ))

    loaded = repo.get_cached(folder_id, "Movies/Single Track.mkv")
    assert loaded is not None
    assert len(loaded.audio_tracks) == 1
    assert loaded.audio_tracks[0].codec == "eac3"
    assert len(loaded.subtitle_tracks) == 1
    assert loaded.subtitle_tracks[0].codec == "subrip"
