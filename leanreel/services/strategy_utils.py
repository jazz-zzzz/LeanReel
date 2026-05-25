"""Strategy utility functions."""
from leanreel.utils.gpu import available_nvenc_encoders


def _prioritize_strategies(strategies: list) -> list:
    """Put compatible GPU strategies first while always keeping CPU strategies."""
    available_gpu_encoders = available_nvenc_encoders()
    non_gpu = [
        s for s in strategies
        if not getattr(getattr(s, "video", None), "is_gpu", False)
    ]

    gpu = [
        s for s in strategies
        if getattr(getattr(s, "video", None), "is_gpu", False)
        and getattr(getattr(s, "video", None), "encoder", "") in available_gpu_encoders
    ]
    return gpu + non_gpu
