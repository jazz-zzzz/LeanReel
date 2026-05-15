"""数据模型单元测试"""
import pytest
from leanreel.data.models import (
    Library, LibraryFolder, FileSnapshot,
    CompressionRecord, AudioTrack, SubtitleTrack, HDRType, TaskStatus
)


def test_library_creation():
    lib = Library(name="Film")
    assert lib.name == "Film"


def test_library_folder_creation():
    folder = LibraryFolder(library_id=1, path="/mnt/nas/Film")
    assert folder.path == "/mnt/nas/Film"
    assert folder.library_id == 1


def test_file_snapshot_minimal():
    snap = FileSnapshot(
        library_folder_id=1,
        relative_path="Dunkirk.mkv",
        file_name="Dunkirk.mkv",
        size_bytes=1024,
        video_codec="hevc",
        video_width=3840,
        video_height=2160,
        hdr_type=HDRType.HDR10,
        audio_tracks=[AudioTrack(codec="truehd", channels=8, language="eng")],
        subtitle_tracks=[SubtitleTrack(codec="hdmv_pgs", language="chi")],
        duration_seconds=6420.0,
        bitrate_bps=50000000,
    )
    assert snap.hdr_type == HDRType.HDR10
    assert len(snap.audio_tracks) == 1
    assert snap.audio_tracks[0].channels == 8


def test_compression_record():
    record = CompressionRecord(
        file_snapshot_id=1,
        strategy_name="均衡压缩",
        original_size=50000000000,
        compressed_size=20000000000,
        status=TaskStatus.COMPLETED,
        duration_seconds=15000,
    )
    assert record.original_size > record.compressed_size
    assert record.status == TaskStatus.COMPLETED


def test_hdr_type_enum():
    assert HDRType.SDR == "SDR"
    assert HDRType.HDR10 == "HDR10"
    assert HDRType.DV_P7 == "DV_P7"


def test_library_creation_different_names():
    lib1 = Library(name="TV Series")
    lib2 = Library(name="Anime")
    assert lib1.name != lib2.name
    assert lib1.id is None  # 未持久化时 id 为 None


def test_file_snapshot_defaults():
    snap = FileSnapshot()
    assert snap.hdr_type == HDRType.SDR
    assert snap.audio_tracks == []
    assert snap.subtitle_tracks == []
    assert snap.probe_ok is False
    assert snap.size_bytes == 0


def test_audio_track_commentary_default():
    track = AudioTrack(codec="aac", channels=2, language="eng")
    assert track.is_commentary is False
    assert track.title == ""


def test_subtitle_track_forced_default():
    track = SubtitleTrack(codec="hdmv_pgs", language="chi")
    assert track.is_forced is False
    assert track.title == ""


def test_compression_record_default_status():
    record = CompressionRecord(file_snapshot_id=1, strategy_name="test")
    assert record.status == TaskStatus.PENDING
    assert record.original_size == 0
    assert record.compressed_size == 0


def test_file_snapshot_multiple_audio_tracks():
    tracks = [
        AudioTrack(codec="truehd", channels=8, language="eng", title="Atmos"),
        AudioTrack(codec="aac", channels=2, language="jpn", title="Commentary", is_commentary=True),
        AudioTrack(codec="flac", channels=2, language="chi"),
    ]
    snap = FileSnapshot(audio_tracks=tracks)
    assert len(snap.audio_tracks) == 3
    assert snap.audio_tracks[1].is_commentary is True
    assert snap.audio_tracks[2].language == "chi"
