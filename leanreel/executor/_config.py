"""Executor 全局配置 — 消除模块级可变全局状态"""


class ExecutorConfig:
    """封装 ffprobe/ffmpeg/dovi_tool 二进制路径的单例配置"""

    def __init__(self):
        self._ffprobe_path = None
        self._ffmpeg_path = None
        self._dovi_tool_path = None

    @property
    def ffprobe_path(self):
        return self._ffprobe_path

    @ffprobe_path.setter
    def ffprobe_path(self, value):
        self._ffprobe_path = value

    @property
    def ffmpeg_path(self):
        return self._ffmpeg_path

    @ffmpeg_path.setter
    def ffmpeg_path(self, value):
        self._ffmpeg_path = value

    @property
    def dovi_tool_path(self):
        return self._dovi_tool_path

    @dovi_tool_path.setter
    def dovi_tool_path(self, value):
        self._dovi_tool_path = value


_config = ExecutorConfig()
