# Compression Audit Sidecar — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 编码完成后生成完整审计记录，同源双写 — JSON sidecar 文件 + compression_history 表

**Architecture:** CompressionAudit 领域对象作为唯一数据源，由 FFmpegExecutor.encode() 在 move_out 完成后构建。`leanreel/services/audit.py` 负责构建、写 sidecar、读 sidecar。DB migration 扩展压缩历史表。扫描时检测 `*_zcompressed.mkv.leanreel.json` 将源文件标记为"已压缩"。

**Tech Stack:** Python dataclass, json, sqlite3 migration, subprocess (version check)

---

### Task 1: 环境版本检测工具

**Files:**
- Modify: `leanreel/executor/ffmpeg_builder.py`（末尾追加两个函数）
- Modify: `leanreel/executor/dovi.py`（末尾追加一个函数）

- [ ] **Step 1: 在 ffmpeg_builder.py 末尾添加 `get_ffmpeg_version()`**

```python
def get_ffmpeg_version() -> str:
    """返回 FFmpeg 版本字符串，例如 'ffmpeg version 7.1...'"""
    import subprocess
    try:
        proc = subprocess.run(
            [get_ffmpeg_path(), "-version"],
            capture_output=True, text=True, timeout=5,
        )
        return proc.stdout.split("\n")[0].strip() if proc.returncode == 0 else "unknown"
    except Exception:
        return "unknown"
```

- [ ] **Step 2: 在 dovi.py 末尾添加 `get_dovi_tool_version()`**

```python
def get_dovi_tool_version() -> str:
    """返回 dovi_tool 版本字符串，例如 'dovi_tool 2.1.0'"""
    import subprocess
    try:
        proc = subprocess.run(
            [get_dovi_tool_path(), "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return proc.stdout.strip().split("\n")[0] if proc.returncode == 0 else "unknown"
    except Exception:
        return "unknown"
```

- [ ] **Step 3: 运行现有测试确认无回归**

Run: `py -m pytest tests/test_ffmpeg.py tests/test_dovi.py -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add leanreel/executor/ffmpeg_builder.py leanreel/executor/dovi.py
git commit -m "feat: add version detection for ffmpeg and dovi_tool"
```

---

### Task 2: CompressionAudit 领域模型

**Files:**
- Modify: `leanreel/domain/models.py`（在 `CompressionRecord` 之后追加）

- [ ] **Step 1: 添加 `CompressionAudit` dataclass**

在 `CompressionRecord` 类之后追加：

```python
@dataclass
class CompressionAudit:
    """编码完成后的完整审计快照 — DB 和 Sidecar 的唯一数据源"""
    library_folder_id: int = 0
    relative_path: str = ""
    source_path: str = ""
    source_size_bytes: int = 0
    source_mtime: float = 0.0
    source_codec: str = ""
    source_width: int = 0
    source_height: int = 0
    source_pix_fmt: str = ""
    source_bitrate_bps: int = 0
    source_duration_seconds: float = 0.0
    source_frame_rate: str = ""
    source_hdr: str = "SDR"
    source_color_primaries: str = ""
    source_color_transfer: str = ""
    source_color_space: str = ""
    source_audio: list[dict] = field(default_factory=list)
    source_subtitle: list[dict] = field(default_factory=list)

    output_path: str = ""
    output_size_bytes: int = 0
    savings_bytes: int = 0
    savings_pct: float = 0.0

    strategy_name: str = ""
    encoder: str = ""
    crf: int = 0
    cq: int = 0
    preset: str = ""
    pix_fmt: str = ""
    audio_mode: str = ""
    sub_mode: str = ""

    ffmpeg_command: list[str] = field(default_factory=list)
    adaptive_cq_original: int = 0
    adaptive_cq_adjusted: int = 0
    adaptive_cq_reason: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    status: str = "pending"

    ffmpeg_version: str = ""
    dovi_tool_version: str = ""
    leanreel_version: str = ""
    platform: str = ""

    db_record_id: int = 0
```

- [ ] **Step 2: 运行现有测试确认无回归**

Run: `py -m pytest tests/test_models.py -v`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add leanreel/domain/models.py
git commit -m "feat: add CompressionAudit domain model"
```

---

### Task 3: 审计服务 — build_audit, write_sidecar, read_sidecar

**Files:**
- Create: `leanreel/services/audit.py`
- Create: `tests/test_audit.py`

- [ ] **Step 1: 编写测试 — `test_build_audit_captures_all_fields`**

```python
"""测试压缩审计侧挂功能"""
import json
import os
import tempfile
from pathlib import Path

from leanreel.services.audit import build_audit, write_sidecar, read_sidecar, find_sidecars_for_source


def test_build_audit_captures_all_fields():
    from leanreel.domain.models import FileSnapshot, Strategy, VideoRule, AudioRule, SubtitleRule
    from leanreel.executor.worker import EncodeTask

    snap = FileSnapshot(
        library_folder_id=1,
        relative_path="test/movie.mkv",
        file_name="movie.mkv",
        size_bytes=10_000_000_000,
        video_codec="h264",
        video_width=1920,
        video_height=1080,
        bitrate_bps=15_000_000,
        duration_seconds=3600.0,
    )
    snap.file_mtime = 1700000000.0

    strategy = Strategy(
        name="x265 HEVC CRF 20 标准转码",
        video=VideoRule(encoder="libx265", crf=20, preset="slow", pix_fmt="yuv420p10le"),
        audio=AudioRule(mode="keep_original"),
        subtitle=SubtitleRule(mode="keep_chinese"),
    )

    cmd = ["ffmpeg", "-y", "-i", "/src/movie.mkv", "-c:V", "libx265", "-crf", "20", "/out/movie_zcompressed.mkv"]

    task = EncodeTask(
        file_name="movie.mkv",
        input_path="/src/movie.mkv",
        output_path="/out/movie_zcompressed.mkv",
        strategy_name=strategy.name,
        strategy=strategy,
        snapshot=snap,
        original_size=snap.size_bytes,
    )
    task.compressed_size = 3_500_000_000
    task.started_at = 1700000100.0
    task.completed_at = 1700003700.0

    audit = build_audit(
        task=task,
        ffmpeg_command=cmd,
        adaptive_cq_original=23,
        adaptive_cq_adjusted=23,
        adaptive_cq_reason="bpp >= 8.0, no adjustment needed",
    )

    assert audit.library_folder_id == 1
    assert audit.relative_path == "test/movie.mkv"
    assert audit.source_path == "/src/movie.mkv"
    assert audit.source_size_bytes == 10_000_000_000
    assert audit.source_codec == "h264"
    assert audit.source_width == 1920
    assert audit.source_height == 1080
    assert audit.source_bitrate_bps == 15_000_000
    assert audit.source_duration_seconds == 3600.0
    assert audit.source_hdr == "SDR"

    assert audit.output_path == "/out/movie_zcompressed.mkv"
    assert audit.output_size_bytes == 3_500_000_000
    assert audit.savings_bytes == 6_500_000_000
    assert audit.savings_pct == 65.0

    assert audit.strategy_name == "x265 HEVC CRF 20 标准转码"
    assert audit.encoder == "libx265"
    assert audit.crf == 20
    assert audit.preset == "slow"
    assert audit.pix_fmt == "yuv420p10le"
    assert audit.audio_mode == "keep_original"
    assert audit.sub_mode == "keep_chinese"

    assert audit.ffmpeg_command == cmd
    assert audit.adaptive_cq_original == 23
    assert audit.adaptive_cq_adjusted == 23
    assert audit.status == "completed"
    assert audit.duration_seconds == 3600.0
    assert audit.platform != ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_audit.py::test_build_audit_captures_all_fields -v`
Expected: FAIL (ModuleNotFoundError — audit.py 不存在)

- [ ] **Step 3: 实现 `leanreel/services/audit.py`**

```python
"""压缩审计服务 — 构建、写入、读取 sidecar 文件"""
from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Optional

from leanreel.domain.models import CompressionAudit


_LEANREEL_VERSION = "0.1.0"


def build_audit(
    task,
    ffmpeg_command: list[str],
    adaptive_cq_original: int = 0,
    adaptive_cq_adjusted: int = 0,
    adaptive_cq_reason: str = "",
) -> CompressionAudit:
    """从编码任务和策略构建完整审计快照。"""
    snap = task.snapshot
    strategy = task.strategy

    savings_bytes = task.original_size - task.compressed_size if task.compressed_size > 0 else 0
    savings_pct = round(savings_bytes / task.original_size * 100, 1) if task.original_size > 0 else 0.0

    video = getattr(strategy, "video", None)
    audio = getattr(strategy, "audio", None)
    sub = getattr(strategy, "subtitle", None)

    return CompressionAudit(
        library_folder_id=getattr(snap, "library_folder_id", 0),
        relative_path=getattr(snap, "relative_path", ""),
        source_path=task.input_path,
        source_size_bytes=getattr(snap, "size_bytes", 0),
        source_mtime=getattr(snap, "file_mtime", 0.0),
        source_codec=getattr(snap, "video_codec", ""),
        source_width=getattr(snap, "video_width", 0),
        source_height=getattr(snap, "video_height", 0),
        source_pix_fmt=getattr(snap, "pix_fmt", ""),
        source_bitrate_bps=getattr(snap, "bitrate_bps", 0),
        source_duration_seconds=getattr(snap, "duration_seconds", 0.0),
        source_frame_rate=getattr(snap, "frame_rate", ""),
        source_hdr=getattr(getattr(snap, "hdr_type", None), "value", "SDR"),
        source_audio=[{
            "index": i, "codec": a.codec, "channels": a.channels,
            "language": a.language, "title": a.title,
            "is_commentary": a.is_commentary,
        } for i, a in enumerate(getattr(snap, "audio_tracks", []) or [])],
        source_subtitle=[{
            "index": i, "codec": s.codec,
            "language": s.language, "title": s.title,
            "is_forced": s.is_forced,
        } for i, s in enumerate(getattr(snap, "subtitle_tracks", []) or [])],

        output_path=task.output_path,
        output_size_bytes=task.compressed_size,
        savings_bytes=savings_bytes,
        savings_pct=savings_pct,

        strategy_name=getattr(strategy, "name", task.strategy_name),
        encoder=getattr(video, "encoder", "") if video else "",
        crf=getattr(video, "crf", 0) if video else 0,
        cq=getattr(video, "cq", 0) if video else 0,
        preset=getattr(video, "preset", "") if video else "",
        pix_fmt=getattr(video, "pix_fmt", "") if video else "",
        audio_mode=getattr(audio, "mode", "") if audio else "",
        sub_mode=getattr(sub, "mode", "") if sub else "",

        ffmpeg_command=list(ffmpeg_command),
        adaptive_cq_original=adaptive_cq_original,
        adaptive_cq_adjusted=adaptive_cq_adjusted,
        adaptive_cq_reason=adaptive_cq_reason,
        started_at=_iso(task.started_at) if getattr(task, "started_at", 0) else "",
        completed_at=_iso(task.completed_at) if getattr(task, "completed_at", 0) else "",
        duration_seconds=round(
            (task.completed_at - task.started_at) if (
                getattr(task, "completed_at", 0) and getattr(task, "started_at", 0)
            ) else 0, 1,
        ),
        status=task.status.value if hasattr(task.status, "value") else str(task.status),

        ffmpeg_version=_ffmpeg_version(),
        dovi_tool_version=_dovi_version(),
        leanreel_version=_LEANREEL_VERSION,
        platform=platform.platform(),
    )


def _iso(timestamp: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(timestamp).isoformat()


def _ffmpeg_version() -> str:
    from leanreel.executor.ffmpeg_builder import get_ffmpeg_version
    return get_ffmpeg_version()


def _dovi_version() -> str:
    from leanreel.executor.dovi import get_dovi_tool_version
    return get_dovi_tool_version()


def write_sidecar(audit: CompressionAudit) -> str:
    """将审计快照写入 sidecar JSON 文件。返回写入的路径。失败时返回空字符串。"""
    sidecar_path = _sidecar_path(audit.output_path)
    data = _audit_to_dict(audit)
    try:
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(sidecar_path)
    except Exception:
        import traceback
        traceback.print_exc()
        return ""


def read_sidecar(filepath: str) -> Optional[CompressionAudit]:
    """从 sidecar JSON 文件读取审计快照。失败返回 None。"""
    try:
        data = json.loads(Path(filepath).read_text(encoding="utf-8"))
        return _dict_to_audit(data)
    except Exception:
        return None


def find_sidecars_for_source(source_path: str) -> list[str]:
    """在源文件同目录下查找对应的 sidecar 文件。"""
    source = Path(source_path)
    pattern = f"{source.stem}_zcompressed.*.leanreel.json"
    return sorted(
        str(p) for p in source.parent.glob(pattern)
        if p.is_file()
    )


def _sidecar_path(output_path: str) -> Path:
    return Path(output_path + ".leanreel.json")


def _audit_to_dict(audit: CompressionAudit) -> dict:
    return {
        "version": "1.0",
        "tool": f"LeanReel {audit.leanreel_version}",
        "source": {
            "path": audit.source_path,
            "file_name": Path(audit.source_path).name if audit.source_path else "",
            "size_bytes": audit.source_size_bytes,
            "mtime": audit.source_mtime,
            "video": {
                "codec": audit.source_codec,
                "width": audit.source_width,
                "height": audit.source_height,
                "pix_fmt": audit.source_pix_fmt,
                "bitrate_bps": audit.source_bitrate_bps,
                "duration_seconds": audit.source_duration_seconds,
                "frame_rate": audit.source_frame_rate,
                "hdr_type": audit.source_hdr,
                "color_primaries": audit.source_color_primaries,
                "color_transfer": audit.source_color_transfer,
                "color_space": audit.source_color_space,
            },
            "audio": audit.source_audio,
            "subtitle": audit.source_subtitle,
        },
        "output": {
            "path": audit.output_path,
            "size_bytes": audit.output_size_bytes,
            "savings_bytes": audit.savings_bytes,
            "savings_pct": audit.savings_pct,
        },
        "strategy": {
            "name": audit.strategy_name,
            "video": {
                "encoder": audit.encoder,
                "crf" if audit.crf else "cq": audit.crf or audit.cq,
                "preset": audit.preset,
                "pix_fmt": audit.pix_fmt,
            },
            "audio": {"mode": audit.audio_mode},
            "subtitle": {"mode": audit.sub_mode},
        },
        "execution": {
            "command": audit.ffmpeg_command,
            "adaptive_cq": {
                "original": audit.adaptive_cq_original,
                "adjusted": audit.adaptive_cq_adjusted,
                "reason": audit.adaptive_cq_reason,
            } if audit.adaptive_cq_original else {},
            "started_at": audit.started_at,
            "completed_at": audit.completed_at,
            "duration_seconds": audit.duration_seconds,
            "status": audit.status,
        },
        "environment": {
            "ffmpeg_version": audit.ffmpeg_version,
            "dovi_tool_version": audit.dovi_tool_version,
            "leanreel_version": audit.leanreel_version,
            "platform": audit.platform,
        },
    }


def _dict_to_audit(data: dict) -> CompressionAudit:
    src = data.get("source", {})
    src_video = src.get("video", {})
    out = data.get("output", {})
    strat = data.get("strategy", {})
    strat_video = strat.get("video", {})
    exe = data.get("execution", {})
    env = data.get("environment", {})

    cq_val = strat_video.get("crf", strat_video.get("cq", 0))

    return CompressionAudit(
        source_path=src.get("path", ""),
        source_size_bytes=src.get("size_bytes", 0),
        source_mtime=src.get("mtime", 0.0),
        source_codec=src_video.get("codec", ""),
        source_width=src_video.get("width", 0),
        source_height=src_video.get("height", 0),
        source_pix_fmt=src_video.get("pix_fmt", ""),
        source_bitrate_bps=src_video.get("bitrate_bps", 0),
        source_duration_seconds=src_video.get("duration_seconds", 0.0),
        source_frame_rate=src_video.get("frame_rate", ""),
        source_hdr=src_video.get("hdr_type", "SDR"),
        source_audio=src.get("audio", []),
        source_subtitle=src.get("subtitle", []),
        output_path=out.get("path", ""),
        output_size_bytes=out.get("size_bytes", 0),
        savings_bytes=out.get("savings_bytes", 0),
        savings_pct=out.get("savings_pct", 0.0),
        strategy_name=strat.get("name", ""),
        encoder=strat_video.get("encoder", ""),
        cq=cq_val,
        preset=strat_video.get("preset", ""),
        pix_fmt=strat_video.get("pix_fmt", ""),
        audio_mode=strat.get("audio", {}).get("mode", ""),
        sub_mode=strat.get("subtitle", {}).get("mode", ""),
        ffmpeg_command=exe.get("command", []),
        adaptive_cq_original=exe.get("adaptive_cq", {}).get("original", 0),
        adaptive_cq_adjusted=exe.get("adaptive_cq", {}).get("adjusted", 0),
        adaptive_cq_reason=exe.get("adaptive_cq", {}).get("reason", ""),
        started_at=exe.get("started_at", ""),
        completed_at=exe.get("completed_at", ""),
        duration_seconds=exe.get("duration_seconds", 0.0),
        status=exe.get("status", "pending"),
        ffmpeg_version=env.get("ffmpeg_version", ""),
        dovi_tool_version=env.get("dovi_tool_version", ""),
        leanreel_version=env.get("leanreel_version", ""),
        platform=env.get("platform", ""),
    )
```

- [ ] **Step 4: 运行测试**

Run: `py -m pytest tests/test_audit.py::test_build_audit_captures_all_fields -v`
Expected: PASS

- [ ] **Step 5: 补充 sidecar 读写测试**

```python
def test_write_and_read_sidecar_roundtrip():
    from leanreel.domain.models import CompressionAudit

    audit = CompressionAudit(
        library_folder_id=1,
        relative_path="test/movie.mkv",
        source_path="/src/movie.mkv",
        source_size_bytes=10_000_000_000,
        source_codec="h264",
        source_hdr="SDR",
        output_path="/tmp/movie_zcompressed.mkv",
        output_size_bytes=3_500_000_000,
        savings_bytes=6_500_000_000,
        savings_pct=65.0,
        strategy_name="x265 HEVC CRF 20 标准转码",
        encoder="libx265",
        crf=20,
        preset="slow",
        ffmpeg_command=["ffmpeg", "-y", "-i", "src", "out"],
        started_at="2026-05-25T12:00:00",
        completed_at="2026-05-25T14:30:00",
        duration_seconds=9000.0,
        status="completed",
        ffmpeg_version="ffmpeg version 7.1",
        platform="Windows",
    )

    with tempfile.TemporaryDirectory() as tmp:
        audit.output_path = str(Path(tmp) / "movie_zcompressed.mkv")
        path = write_sidecar(audit)
        assert path != ""
        assert os.path.exists(path)

        loaded = read_sidecar(path)
        assert loaded is not None
        assert loaded.source_codec == audit.source_codec
        assert loaded.output_size_bytes == audit.output_size_bytes
        assert loaded.strategy_name == audit.strategy_name
        assert loaded.encoder == audit.encoder
        assert loaded.ffmpeg_command == audit.ffmpeg_command


def test_write_sidecar_failure_returns_empty():
    from leanreel.domain.models import CompressionAudit

    audit = CompressionAudit(output_path="/nonexistent/dir/movie_zcompressed.mkv")
    result = write_sidecar(audit)
    assert result == ""


def test_read_sidecar_invalid_json_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.leanreel.json"
        bad.write_text("not json")
        assert read_sidecar(str(bad)) is None


def test_find_sidecars_for_source():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "movie.mkv"
        src.touch()
        sidecar = Path(tmp) / "movie_zcompressed.mkv.leanreel.json"
        sidecar.write_text("{}")
        found = find_sidecars_for_source(str(src))
        assert len(found) == 1
        assert "movie_zcompressed" in found[0]


def test_find_sidecars_no_match_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "movie.mkv"
        src.touch()
        found = find_sidecars_for_source(str(src))
        assert found == []
```

- [ ] **Step 6: 运行测试**

Run: `py -m pytest tests/test_audit.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add leanreel/services/audit.py tests/test_audit.py
git commit -m "feat: add audit service — build_audit, write_sidecar, read_sidecar"
```

---

### Task 4: 输出文件后缀 `_SS` → `_zcompressed`

**Files:**
- Modify: `leanreel/controllers/encoding_controller.py:11`

- [ ] **Step 1: 修改 `make_output_path`**

```python
def make_output_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}_zcompressed{source.suffix}")
```

- [ ] **Step 2: 运行相关测试确认命名变更**

Run: `py -m pytest tests/ -k "encoding" -v`
Expected: 确认现有测试能通过且覆盖命名变更

- [ ] **Step 3: Commit**

```bash
git add leanreel/controllers/encoding_controller.py
git commit -m "feat: rename output suffix from _SS to _zcompressed"
```

---

### Task 5: DB migration — compression_history 扩展

**Files:**
- Modify: `leanreel/infrastructure/database.py`（`_create_tables` 新增列 + `_migrate` 新增 migration + `insert_compression` 更新）

- [ ] **Step 1: 在 `_migrate` 中添加新列检测和迁移**

在现有 migration 之后追加：

```python
# _migrate 方法中追加
existing_ch = {row[1] for row in conn.execute("PRAGMA table_info(compression_history)")}
ch_migrations = [
    ("output_path", "TEXT DEFAULT ''"),
    ("output_size_bytes", "INTEGER DEFAULT 0"),
    ("savings_pct", "REAL DEFAULT 0"),
    ("encoder", "TEXT DEFAULT ''"),
    ("cq_value", "INTEGER DEFAULT 0"),
    ("preset", "TEXT DEFAULT ''"),
    ("pix_fmt", "TEXT DEFAULT ''"),
    ("audio_mode", "TEXT DEFAULT ''"),
    ("sub_mode", "TEXT DEFAULT ''"),
    ("ffmpeg_command", "TEXT DEFAULT ''"),
    ("sidecar_path", "TEXT DEFAULT ''"),
    ("leanreel_version", "TEXT DEFAULT ''"),
]
for col_name, col_def in ch_migrations:
    if col_name not in existing_ch:
        conn.execute(f"ALTER TABLE compression_history ADD COLUMN {col_name} {col_def}")
```

- [ ] **Step 2: 更新 `insert_compression` 方法支持所有新字段**

```python
def insert_compression(self, record: CompressionRecord) -> int:
    """插入压缩历史记录，返回记录 ID。"""
    cols = [
        "file_snapshot_id", "strategy_name", "original_size", "compressed_size",
        "status", "duration_seconds", "error_message",
        "output_path", "output_size_bytes", "savings_pct",
        "encoder", "cq_value", "preset", "pix_fmt",
        "audio_mode", "sub_mode", "ffmpeg_command", "sidecar_path", "leanreel_version",
    ]
    values = [
        record.file_snapshot_id, record.strategy_name, record.original_size,
        record.compressed_size, record.status, record.duration_seconds,
        getattr(record, "error_message", ""),
        getattr(record, "output_path", ""),
        getattr(record, "output_size_bytes", 0),
        getattr(record, "savings_pct", 0.0),
        getattr(record, "encoder", ""),
        getattr(record, "cq_value", 0),
        getattr(record, "preset", ""),
        getattr(record, "pix_fmt", ""),
        getattr(record, "audio_mode", ""),
        getattr(record, "sub_mode", ""),
        getattr(record, "ffmpeg_command", ""),
        getattr(record, "sidecar_path", ""),
        getattr(record, "leanreel_version", ""),
    ]
    placeholders = ",".join("?" * len(cols))
    self.execute(
        f"INSERT INTO compression_history ({','.join(cols)}) VALUES ({placeholders})",
        values,
    )
    return self.last_insert_id
```

- [ ] **Step 3: 更新 `get_history_for_library` 读取新字段**

在 `get_history_for_library` 返回的 `CompressionRecord` 构造中，通过 `getattr` 不改变现有字段签名，新增字段通过 `getattr` 读取（DB 已有默认值，无需改动现有代码）。

- [ ] **Step 4: 运行 DB 测试确认迁移和字段通过**

Run: `py -m pytest tests/test_database.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add leanreel/infrastructure/database.py
git commit -m "feat: extend compression_history table with audit fields"
```

---

### Task 6: 集成审计到 FFmpegExecutor — 存储 ffmpeg 命令和 CQ 信息

**Files:**
- Modify: `leanreel/executor/ffmpeg.py`（在 encode 方法中捕获 cmd 和 cq 信息到 task 上）

- [ ] **Step 1: 在 task 上临时存储 ffmpeg 命令和 CQ 调整信息**

在 `ffmpeg.py` 的 `encode()` 方法中，transcode stage 的 `cmd` 变量定义之后，追加：

```python
# 存储命令和 CQ 信息到 task 用于后续审计
task._ffmpeg_command = list(cmd)
task._adaptive_cq = {"original": cq_original, "adjusted": cq, "reason": cq_reason}
```

需要在 transcode stage 的开头（`cq` 计算处）先保存原始 CQ：

```python
# 在 cq 计算之前
cq_original = strategy.video.cq if hasattr(strategy, "video") else 26
# ... 现有的自适应 CQ 计算代码 ...
# 记录调整原因
if bpp < 2.5:
    cq_reason = f"bpp {bpp:.1f} < 2.5, cq {cq_original} → {cq}"
elif bpp < 5.0:
    cq_reason = f"bpp {bpp:.1f} < 5.0, cq {cq_original} → {cq}"
elif bpp < 8.0:
    cq_reason = f"bpp {bpp:.1f} < 8.0, cq {cq_original} → {cq}"
else:
    cq_reason = f"bpp {bpp:.1f} >= 8.0, no adjustment needed"
```

- [ ] **Step 2: 在 move_out 完成后、清理前，添加审计双写调用**

在 `encode()` 的 try 块末尾，`move_out` stage 完成后，但在 finally 之前：

```python
# ── 审计双写 ──
try:
    from leanreel.services.audit import build_audit, write_sidecar
    cmd = getattr(task, "_ffmpeg_command", [])
    cq_info = getattr(task, "_adaptive_cq", {})
    audit = build_audit(
        task=task,
        ffmpeg_command=cmd,
        adaptive_cq_original=cq_info.get("original", 0),
        adaptive_cq_adjusted=cq_info.get("adjusted", 0),
        adaptive_cq_reason=cq_info.get("reason", ""),
    )
    sidecar_path = write_sidecar(audit)
    if sidecar_path:
        audit.sidecar_path = sidecar_path

    # 写入 DB
    if hasattr(task, '_db') and task._db is not None:
        from leanreel.infrastructure.database import _audit_to_record
        record = _audit_to_record(audit, snapshot_id=task.snapshot.id or 0)
        db_id = task._db.insert_compression(record)
        audit.db_record_id = db_id
        # 回写 sidecar（含 db_record_id）
        if db_id:
            write_sidecar(audit)
except Exception:
    import traceback
    traceback.print_exc()
```

- [ ] **Step 3: 运行 FFmpeg 相关测试**

Run: `py -m pytest tests/test_ffmpeg.py tests/test_worker.py -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add leanreel/executor/ffmpeg.py
git commit -m "feat: capture ffmpeg command and CQ info for audit trail"
```

---

### Task 7: DB 访问注入 — FFmpegExecutor 获取 Database 引用

**Files:**
- Modify: `leanreel/controllers/encoding_controller.py`（传递 db 到 executor）
- Modify: `leanreel/executor/ffmpeg.py`（接收可选的 db 参数）

- [ ] **Step 1: FFmpegExecutor 接受可选的 `db` 参数**

```python
class FFmpegExecutor:
    def __init__(self, progress_callback=None, temp_dir=None,
                 sync_output=False, keep_temp=False, db=None):
        # ... 现有初始化 ...
        self._db = db
```

- [ ] **Step 2: 在 encode 中将 db 传给 task**

在 `encode()` 开头（task 变量可用之后）：

```python
task._db = self._db
```

- [ ] **Step 3: EncodingController.start 传递 db**

在创建 `FFmpegExecutor` 时传入 db。在 `main.py` 中，`Application` 持有 `self.services.db`。EncodingController 的 `start` 方法需要接收 db。

这要求修改 `EncodingController.__init__` 接受 db 参数，或者在 start 时传递。

**选择：** 在 `__init__` 中接受 db：

```python
class EncodingController:
    def __init__(self, strategy_panel, win, queue_panel, notifier, db=None):
        # ... 现有初始化 ...
        self._db = db
```

在 `start()` 中创建 FFmpegExecutor 时传入：

```python
self.active_manager = WorkerManager(
    FFmpegExecutor(
        temp_dir=self._strategy_panel.temp_dir,
        progress_callback=lambda t: self._notifier.task_updated.emit(t),
        sync_output=self._strategy_panel.sync_output,
        keep_temp=self._strategy_panel.keep_temp,
        db=self._db,
    ),
    ...
)
```

- [ ] **Step 4: 更新 main.py 中 EncodingController 初始化**

```python
self.encoding_ctrl = EncodingController(
    strategy_panel=self.strategy_panel,
    win=self.win,
    queue_panel=self.queue_panel,
    notifier=self.notifier,
    db=self.services.db,
)
```

- [ ] **Step 5: Commit**

```bash
git add leanreel/executor/ffmpeg.py leanreel/controllers/encoding_controller.py leanreel/main.py
git commit -m "feat: inject db into FFmpegExecutor for audit persistence"
```

---

### Task 8: Sidecar 检测 → 扫描集成

**Files:**
- Modify: `leanreel/services/audit.py`（已有 `find_sidecars_for_source`）
- Modify: `leanreel/controllers/scan_controller.py`（在 `_on_scan_ready` 或 `_populate_file_list` 中检测 sidecar）
- Modify: `leanreel/gui/file_list.py`（添加 `compressed` 状态到 `_decision_display`）

- [ ] **Step 1: 在 `_populate_file_list` 中检测 sidecar 并标记已压缩文件**

在 `scan_controller.py` 的 `_populate_file_list` 方法中，构建 FileRow 时检测 sidecar：

```python
def _populate_file_list(self, snapshots):
    from leanreel.services.audit import find_sidecars_for_source
    
    matched: dict = {}
    for s in snapshots:
        key = (int(s.library_folder_id or 0), str(s.relative_path))
        strategy = self._services.matcher.match(s)
        if strategy is None:
            matched[key] = MatchResult(
                strategy=get_skip_reason(s) or "跳过",
                estimate={},
            )
            continue
        matched[key] = MatchResult(
            strategy=strategy,
            estimate=estimate_savings(s, strategy),
        )

    # 检测已压缩文件
    compressed_map: dict = {}
    if self._state.current_folder_paths:
        for s in snapshots:
            folder_path = self._state.current_folder_paths.get(s.library_folder_id)
            if folder_path:
                source_abs = str(Path(folder_path) / s.relative_path)
                sidecars = find_sidecars_for_source(source_abs)
                if sidecars:
                    compressed_map[(s.library_folder_id, s.relative_path)] = sidecars[0]

    rows = []
    for s in snapshots:
        key = (int(s.library_folder_id or 0), str(s.relative_path))
        m = matched.get(key)
        d = self._file_panel._decision_display(s, m, compressed_map.get(key))
        rows.append(FileRow(snap=s, match=m, decision=d))
    
    self._file_panel.set_strategy_lookup(self._services.strategies)
    self._store.rebuild(rows, strategies=self._services.strategies, keep_checked=False)
    ...
```

- [ ] **Step 2: 更新 `_decision_display` 签名和逻辑**

添加 `sidecar_path` 参数，在所有现有检查之前添加压缩状态检测：

```python
def _decision_display(self, snap, match, sidecar_path: str | None = None):
    # 已压缩检测 — 最早判断
    if sidecar_path:
        strategy_name = "已压缩"
        try:
            from leanreel.services.audit import read_sidecar
            audit_snap = read_sidecar(sidecar_path)
            if audit_snap:
                strategy_name = f"已压缩：{audit_snap.strategy_name}"
        except Exception:
            pass
        return FileDecisionDisplay(
            status_key="compressed",
            strategy_text=strategy_name,
            result_text="已完成",
            result_sort=-5,
            processable=False,
            tooltip=f"该文件已压缩，审计记录：{Path(sidecar_path).name}",
        )

    # ── 以下不变 ──
    # pending probe check...
    # skip_reason check...
    # probe_failed check...
    # resolve_match_display...
```

注意：现有调用方 `_decision_display(snap, match)` 不加第三个参数时 `sidecar_path=None`，行为不变。

- [ ] **Step 3: 运行测试**

Run: `py -m pytest tests/ -x -q`
Expected: 433+ tests pass, no regressions

- [ ] **Step 4: Commit**

```bash
git add leanreel/controllers/scan_controller.py leanreel/gui/file_list.py
git commit -m "feat: detect compressed files via sidecar during scan"
```

---

### Task 9: 端到端集成测试

**Files:**
- Modify: `tests/test_audit.py`（追加集成测试）

- [ ] **Step 1: 添加端到端审计流程测试**

```python
def test_audit_roundtrip_sidecar_to_display():
    """端到端：写 sidecar → 扫描检测 → 文件列表显示已压缩"""
    import tempfile
    from pathlib import Path
    from leanreel.domain.models import CompressionAudit, FileSnapshot
    from leanreel.gui.file_list import FileListPanel
    from leanreel.services.audit import write_sidecar, read_sidecar

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "movie_zcompressed.mkv"
        out.touch()
        sidecar = Path(tmp) / "movie_zcompressed.mkv.leanreel.json"

        audit = CompressionAudit(
            library_folder_id=1,
            relative_path="movie.mkv",
            source_path=str(Path(tmp) / "movie.mkv"),
            source_size_bytes=10_000_000_000,
            source_codec="h264",
            source_hdr="SDR",
            output_path=str(out),
            output_size_bytes=3_500_000_000,
            savings_bytes=6_500_000_000,
            savings_pct=65.0,
            strategy_name="x265 HEVC CRF 20 标准转码",
            encoder="libx265",
            crf=20,
            preset="slow",
            ffmpeg_command=["ffmpeg", "-y"],
            status="completed",
        )
        write_sidecar(audit)

        # 模拟扫描检测
        from leanreel.services.audit import find_sidecars_for_source
        source_path = str(Path(tmp) / "movie.mkv")
        found = find_sidecars_for_source(source_path)
        assert len(found) == 1

        # 验证 FileDecisionDisplay
        panel = FileListPanel()
        snap = FileSnapshot(
            library_folder_id=1,
            relative_path="movie.mkv",
            file_name="movie.mkv",
            size_bytes=10_000_000_000,
            video_codec="h264",
        )
        decision = panel._decision_display(snap, match=None, sidecar_path=found[0])
        assert decision.status_key == "compressed"
        assert decision.processable is False
        assert "x265" in decision.strategy_text
```

- [ ] **Step 2: 运行端到端测试**

Run: `py -m pytest tests/test_audit.py -v`
Expected: all PASS

- [ ] **Step 3: 运行全量测试确认无回归**

Run: `py -m pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_audit.py
git commit -m "test: e2e audit roundtrip — sidecar write, scan detect, display"
```

---

### 验证清单

完成所有任务后逐项确认：

1. `py -m leanreel.main` 启动正常
2. 扫描文件夹能检测到已压缩文件 → 显示 "已压缩：xxx"
3. 新建库 → 添加文件夹 → 压缩文件 → 确认生成了 `*_zcompressed.mkv.leanreel.json`
4. Sidecar JSON 包含完整命令行、策略参数、环境信息
5. `compression_history` 表包含新增字段的数据
6. 压缩后体积反超的情况 → sidecar 正确记录 `status: completed`
