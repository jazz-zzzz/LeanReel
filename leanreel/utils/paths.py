"""应用路径工具 — LeanReel 数据目录和策略目录路径"""
import sys
import os
from pathlib import Path

_OBSOLETE_BUILTIN_STRATEGIES = {
    "balanced.json",
    "extreme.json",
    "light.json",
    "av1_balanced.json",
    "av1_quality.json",
    "nvenc_balanced.json",
    "nvenc_quality.json",
    "strip_only.json",
    "x265_fast.json",
    "x265_quality.json",
    "x265_turbo.json",
}


def get_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "LeanReel"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_strategies_dir() -> Path:
    user_dir = get_data_dir() / "strategies"
    user_dir.mkdir(parents=True, exist_ok=True)
    builtin = Path(__file__).parent.parent / "resources" / "strategies"
    if builtin.exists():
        import shutil
        builtin_names = {f.name for f in builtin.glob("*.json")}
        for name in _OBSOLETE_BUILTIN_STRATEGIES - builtin_names:
            stale = user_dir / name
            if stale.exists():
                stale.unlink()
        for f in builtin.glob("*.json"):
            dest = user_dir / f.name
            shutil.copy2(f, dest)
    return user_dir
