"""GUI 工具函数 — 供各面板共享使用"""


def _format_bytes(size_bytes):
    """将字节数格式化为人类可读的字符串（如 1.5 GB）。"""
    value = float(size_bytes or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while abs(value) >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.1f} {units[idx]}"
