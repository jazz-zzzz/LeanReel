"""策略工具 — 策略优先级排序（纯业务逻辑，不碰 I/O）"""
from leanreel.utils.gpu import has_nvenc


def _prioritize_strategies(strategies: list) -> list:
    """仅保留 GPU 策略；如果 NVENC 不可用则保留全部（回退到 CPU）。"""
    if not has_nvenc():
        return strategies
    gpu = [s for s in strategies if getattr(getattr(s, "video", None), "is_gpu", False)]
    # 始终保留 copy 模式（仅去冗余，不需要编码器）
    copy = [s for s in strategies if getattr(getattr(s, "video", None), "encoder", "") == "copy"]
    return gpu + copy
