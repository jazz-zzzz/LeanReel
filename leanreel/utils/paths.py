"""应用路径工具 — LeanReel 数据目录和策略目录路径"""
import sys
import os
from pathlib import Path


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
        for f in builtin.glob("*.json"):
            dest = user_dir / f.name
            shutil.copy2(f, dest)
    return user_dir
