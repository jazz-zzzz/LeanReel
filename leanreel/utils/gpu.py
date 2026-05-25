"""GPU detection helpers."""
import subprocess

from leanreel.executor.ffmpeg_builder import get_ffmpeg_path


def available_nvenc_encoders() -> set[str]:
    """Return exact NVENC encoder names exposed by the active FFmpeg build."""
    try:
        result = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except Exception:
        return set()

    encoders: set[str] = set()
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].endswith("_nvenc"):
            encoders.add(parts[1])
    return encoders


def has_nvenc() -> bool:
    """Return whether any NVENC encoder is available."""
    return bool(available_nvenc_encoders())
