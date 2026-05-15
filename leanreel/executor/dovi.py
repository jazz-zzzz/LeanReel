"""dovi_tool 封装 — Dolby Vision RPU 提取与注入"""
import subprocess
from pathlib import Path
from typing import Optional

from leanreel.data.models import FileSnapshot, HDRType
from leanreel.core.strategy import Strategy
from leanreel.executor.resources import bundled_resource_path

_DOVI_TOOL_PATH = None


def get_dovi_tool_path() -> str:
    global _DOVI_TOOL_PATH
    if _DOVI_TOOL_PATH:
        return _DOVI_TOOL_PATH
    builtin = bundled_resource_path("dovi_tool", "dovi_tool.exe")
    if builtin.exists():
        return str(builtin)
    return "dovi_tool"


def set_dovi_tool_path(path: str):
    global _DOVI_TOOL_PATH
    _DOVI_TOOL_PATH = path


def needs_dovi_processing(snap: FileSnapshot, strategy: Strategy) -> bool:
    """判断是否需要 dovi_tool 参与处理"""
    if snap.hdr_type != HDRType.DV_P7:
        return False
    return strategy.hdr.dv_handling == "reinject_rpu"


class DoviTool:

    @staticmethod
    def build_extract_command(input_file: str, rpu_output: str) -> list[str]:
        return [get_dovi_tool_path(), "extract-rpu", input_file, "-o", rpu_output]

    @staticmethod
    def build_inject_command(encoded_hevc: str, rpu_file: str, output: str) -> list[str]:
        return [get_dovi_tool_path(), "inject-rpu", "-i", encoded_hevc,
                "--rpu-in", rpu_file, "-o", output]

    @staticmethod
    def extract_rpu(input_file: str, rpu_output: str) -> bool:
        cmd = DoviTool.build_extract_command(input_file, rpu_output)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
        return result.returncode == 0

    @staticmethod
    def inject_rpu(encoded_hevc: str, rpu_file: str, output: str) -> bool:
        cmd = DoviTool.build_inject_command(encoded_hevc, rpu_file, output)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
        return result.returncode == 0
