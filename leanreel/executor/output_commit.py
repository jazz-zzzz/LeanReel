"""Output commit protocol for encoded files."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

_COPY_CHUNK = 128 * 1024 * 1024  # 128 MB，NAS 写回大缓冲区


class OutputCommitter:
    """Commit a completed temp output to its final path via a staging file."""

    def commit(self, temp_output: Path | str, final_output: Path | str) -> Path:
        temp_output = Path(temp_output)
        final_output = Path(final_output)
        staging = final_output.with_name(final_output.name + ".staging")

        if not temp_output.exists():
            raise FileNotFoundError(str(temp_output))
        if temp_output.stat().st_size <= 0:
            raise ValueError(f"Refusing to commit empty output: {temp_output}")

        final_output.parent.mkdir(parents=True, exist_ok=True)
        try:
            if staging.exists():
                staging.unlink()
            self._copyfile(temp_output, staging)
            os.replace(str(staging), str(final_output))
            temp_output.unlink(missing_ok=True)  # 替换成功后清理临时文件
            return final_output
        except Exception:
            try:
                if staging.exists():
                    staging.unlink()
            finally:
                raise

    @staticmethod
    def _copyfile(src: Path, dst: Path) -> None:
        """跨设备大缓冲区拷贝，避免 shutil.move 降级为 1 MB 缓冲区。"""
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while chunk := fsrc.read(_COPY_CHUNK):
                fdst.write(chunk)
