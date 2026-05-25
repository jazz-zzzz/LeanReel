"""测试压缩审计侧挂功能"""
import json
import os
import tempfile
from pathlib import Path

from leanreel.services.audit import build_audit, write_sidecar, read_sidecar, find_sidecars_for_source


def test_build_audit_captures_all_fields():
    from leanreel.domain.models import FileSnapshot, Strategy, VideoRule, AudioRule, SubtitleRule, TaskStatus
    from leanreel.executor.worker import EncodeTask

    snap = FileSnapshot(
        library_folder_id=1,
        relative_path="test/movie.mkv",
        file_name="movie.mkv",
        size_bytes=10_000_000_000,
        video_codec="h264",
        video_width=1920,
        video_height=1080,
        bitrate_bps=15_000_000,
        duration_seconds=3600.0,
    )
    snap.file_mtime = 1700000000.0

    strategy = Strategy(
        name="x265 HEVC CRF 20 标准转码",
        video=VideoRule(encoder="libx265", crf=20, preset="slow", pix_fmt="yuv420p10le"),
        audio=AudioRule(mode="keep_original"),
        subtitle=SubtitleRule(mode="keep_chinese"),
    )

    cmd = ["ffmpeg", "-y", "-i", "/src/movie.mkv", "-c:V", "libx265", "-crf", "20", "/out/movie_zcompressed.mkv"]

    task = EncodeTask(
        file_name="movie.mkv",
        input_path="/src/movie.mkv",
        output_path="/out/movie_zcompressed.mkv",
        strategy_name=strategy.name,
        strategy=strategy,
        snapshot=snap,
        original_size=snap.size_bytes,
    )
    task.compressed_size = 3_500_000_000
    task.started_at = 1700000100.0
    task.completed_at = 1700003700.0
    task.status = TaskStatus.COMPLETED

    audit = build_audit(
        task=task,
        ffmpeg_command=cmd,
        adaptive_cq_original=23,
        adaptive_cq_adjusted=23,
        adaptive_cq_reason="bpp >= 8.0, no adjustment needed",
    )

    assert audit.library_folder_id == 1
    assert audit.relative_path == "test/movie.mkv"
    assert audit.source_path == "/src/movie.mkv"
    assert audit.source_size_bytes == 10_000_000_000
    assert audit.source_codec == "h264"
    assert audit.source_width == 1920
    assert audit.source_height == 1080
    assert audit.source_bitrate_bps == 15_000_000
    assert audit.source_duration_seconds == 3600.0
    assert audit.source_hdr == "SDR"

    assert audit.output_path == "/out/movie_zcompressed.mkv"
    assert audit.output_size_bytes == 3_500_000_000
    assert audit.savings_bytes == 6_500_000_000
    assert audit.savings_pct == 65.0

    assert audit.strategy_name == "x265 HEVC CRF 20 标准转码"
    assert audit.encoder == "libx265"
    assert audit.crf == 20
    assert audit.preset == "slow"
    assert audit.pix_fmt == "yuv420p10le"
    assert audit.audio_mode == "keep_original"
    assert audit.sub_mode == "keep_chinese"

    assert audit.ffmpeg_command == cmd
    assert audit.adaptive_cq_original == 23
    assert audit.adaptive_cq_adjusted == 23
    assert audit.status == "completed"
    assert audit.duration_seconds == 3600.0
    assert audit.platform != ""


def test_write_and_read_sidecar_roundtrip():
    from leanreel.domain.models import CompressionAudit

    audit = CompressionAudit(
        library_folder_id=1,
        relative_path="test/movie.mkv",
        source_path="/src/movie.mkv",
        source_size_bytes=10_000_000_000,
        source_codec="h264",
        source_hdr="SDR",
        output_path="/tmp/movie_zcompressed.mkv",
        output_size_bytes=3_500_000_000,
        savings_bytes=6_500_000_000,
        savings_pct=65.0,
        strategy_name="x265 HEVC CRF 20 标准转码",
        encoder="libx265",
        crf=20,
        preset="slow",
        ffmpeg_command=["ffmpeg", "-y", "-i", "src", "out"],
        started_at="2026-05-25T12:00:00",
        completed_at="2026-05-25T14:30:00",
        duration_seconds=9000.0,
        status="completed",
        ffmpeg_version="ffmpeg version 7.1",
        platform="Windows",
    )

    with tempfile.TemporaryDirectory() as tmp:
        audit.output_path = str(Path(tmp) / "movie_zcompressed.mkv")
        path = write_sidecar(audit)
        assert path != ""
        assert os.path.exists(path)

        loaded = read_sidecar(path)
        assert loaded is not None
        assert loaded.source_codec == audit.source_codec
        assert loaded.output_size_bytes == audit.output_size_bytes
        assert loaded.strategy_name == audit.strategy_name
        assert loaded.encoder == audit.encoder
        assert loaded.ffmpeg_command == audit.ffmpeg_command


def test_write_sidecar_failure_returns_empty():
    from unittest.mock import patch
    from leanreel.domain.models import CompressionAudit

    audit = CompressionAudit(output_path="/tmp/movie_zcompressed.mkv")
    with patch("pathlib.Path.mkdir", side_effect=OSError("permission denied")):
        result = write_sidecar(audit)
        assert result == ""


def test_read_sidecar_invalid_json_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.leanreel.json"
        bad.write_text("not json")
        assert read_sidecar(str(bad)) is None


def test_find_sidecars_for_source():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "movie.mkv"
        src.touch()
        sidecar = Path(tmp) / "movie_zcompressed.mkv.leanreel.json"
        sidecar.write_text("{}")
        found = find_sidecars_for_source(str(src))
        assert len(found) == 1
        assert "movie_zcompressed" in found[0]


def test_find_sidecars_no_match_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "movie.mkv"
        src.touch()
        found = find_sidecars_for_source(str(src))
        assert found == []


def test_audit_roundtrip_sidecar_to_display(qtbot):
    """端到端：写 sidecar → 扫描检测 → 文件列表显示已压缩"""
    import tempfile
    from pathlib import Path
    from leanreel.domain.models import CompressionAudit, FileSnapshot
    from leanreel.gui.file_list import FileListPanel
    from leanreel.services.audit import write_sidecar, find_sidecars_for_source

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "movie_zcompressed.mkv"
        out.touch()
        sidecar = Path(tmp) / "movie_zcompressed.mkv.leanreel.json"

        audit = CompressionAudit(
            library_folder_id=1,
            relative_path="movie.mkv",
            source_path=str(Path(tmp) / "movie.mkv"),
            source_size_bytes=10_000_000_000,
            source_codec="h264",
            source_hdr="SDR",
            output_path=str(out),
            output_size_bytes=3_500_000_000,
            savings_bytes=6_500_000_000,
            savings_pct=65.0,
            strategy_name="x265 HEVC CRF 20 标准转码",
            encoder="libx265",
            crf=20,
            preset="slow",
            ffmpeg_command=["ffmpeg", "-y"],
            status="completed",
        )
        path = write_sidecar(audit)
        assert path != ""
        assert sidecar.exists()

        # Simulate scan detection
        source_path = str(Path(tmp) / "movie.mkv")
        found = find_sidecars_for_source(source_path)
        assert len(found) == 1
        assert "movie_zcompressed" in found[0]

        # Verify FileDecisionDisplay marks as compressed (DB-driven)
        panel = FileListPanel()
        qtbot.addWidget(panel)
        snap = FileSnapshot(
            library_folder_id=1,
            relative_path="movie.mkv",
            file_name="movie.mkv",
            size_bytes=10_000_000_000,
            video_codec="h264",
            probe_ok=True,
        )
        compressed_record = {
            "encoder": "libx265",
            "strategy_name": "x265 HEVC CRF 20 标准转码",
            "savings_pct": 65.0,
        }
        decision = panel._decision_display(snap, match=None, compressed_record=compressed_record)
        assert decision.status_key == "compressed"
        assert decision.processable is False
        assert "HEVC" in decision.strategy_text
