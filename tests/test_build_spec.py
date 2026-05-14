"""PyInstaller packaging spec tests."""
from pathlib import Path


def test_build_spec_includes_bundled_command_line_tools():
    text = Path("build.spec").read_text(encoding="utf-8")

    assert "leanreel/resources/ffmpeg/ffmpeg.exe" in text
    assert "leanreel/resources/ffmpeg/ffprobe.exe" in text
    assert "leanreel/resources/dovi_tool/dovi_tool.exe" in text
