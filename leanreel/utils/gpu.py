"""GPU 检测 — 纯基础设施，不依赖项目内其他层"""
import subprocess
from leanreel.executor.ffmpeg_builder import get_ffmpeg_path


def has_nvenc() -> bool:
    """检测系统是否支持 NVENC GPU 编码。"""
    try:
        result = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-encoders"],
            capture_output=True, text=True, encoding="utf-8", timeout=10
        )
        return "hevc_nvenc" in (result.stdout or "")
    except Exception:
        return False
