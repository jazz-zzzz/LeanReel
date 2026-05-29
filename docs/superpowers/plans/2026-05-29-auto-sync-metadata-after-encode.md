# Auto-Sync File Snapshot After Encode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 编码成功后自动探测输出文件并同步到 `file_snapshot` 表；源文件删除时移除其快照条目。

**Architecture:** 在 `FFmpegExecutor` 中新增私有方法 `_sync_file_snapshot()`，在 `encode()` 的审计双写块内、源删除之后调用。方法内部创建 `FFprobeRunner` + `SnapshotRepository` 完成探测和持久化。

**Tech Stack:** Python 3.12, pytest, monkeypatch, sqlite3

**Spec:** `docs/superpowers/specs/2026-05-29-auto-sync-metadata-after-encode-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `leanreel/executor/ffmpeg.py` | Modify | 新增 `_sync_file_snapshot()` 方法；在 `encode()` 审计块末尾调用 |
| `tests/test_ffmpeg.py` | Modify | 新增 4 个测试用例覆盖新方法 |

---

### Task 1: Write tests for `_sync_file_snapshot`

**Files:**
- Modify: `tests/test_ffmpeg.py` (append 4 test functions at end)

- [ ] **Step 1: Add test — output file probed and saved on success**

In `tests/test_ffmpeg.py`, append after the last test:

```python
def test_sync_file_snapshot_probes_output_and_saves(monkeypatch, tmp_path):
    """编码成功后，探测输出文件并写入 file_snapshot"""
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask
    from leanreel.domain.models import TaskStatus, FileSnapshot

    saved_snaps = []
    deleted_entries = []

    class FakeDb:
        def execute(self, sql, params=None):
            if sql.strip().startswith("SELECT id FROM file_snapshot"):
                return [{"id": 99}]
            if sql.strip().startswith("DELETE FROM file_snapshot"):
                deleted_entries.append((sql, params))
            return []

        def update_compression_runtime(self, record_id, **kwargs):
            pass

        def finish_compression(self, record_id, **kwargs):
            pass

    class FakeRepo:
        def __init__(self, db):
            pass

        def save(self, snap):
            saved_snaps.append(snap)

        def load_all(self, folder_id):
            return []

    class FakeProbe:
        def __init__(self, ffprobe_path=None):
            pass

        def probe(self, file_path, library_folder_id=0):
            return FileSnapshot(
                library_folder_id=library_folder_id,
                relative_path="",
                file_name="",
                video_codec="av1",
                video_width=1920,
                video_height=1080,
                hdr_type="SDR",
                size_bytes=500,
                duration_seconds=100.0,
                probe_ok=True,
            )

    def fake_run_ffmpeg(cmd, progress_callback=None, cancel_event=None):
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x" * 500)
        return 0, ""

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr("leanreel.services.audit._ffmpeg_version", lambda: "test")
    monkeypatch.setattr("leanreel.services.audit._dovi_version", lambda: "")
    monkeypatch.setattr("leanreel.infrastructure.repository.SnapshotRepository", FakeRepo)
    monkeypatch.setattr("leanreel.executor.probe.FFprobeRunner", FakeProbe)

    strategy = _make_strategy("CQ28", "av1_nvenc")
    snap = FileSnapshot(
        video_codec="h264",
        library_folder_id=3,
        relative_path="subdir/movie.mkv",
        file_name="movie.mkv",
        size_bytes=1000,
        duration_seconds=100.0,
    )
    task = EncodeTask(
        file_name="movie.mkv",
        input_path=str(tmp_path / "movie.mkv"),
        output_path=str(tmp_path / "movie_zcompressed.mkv"),
        strategy=strategy,
        snapshot=snap,
        original_size=1000,
        history_id=42,
    )
    db = FakeDb()
    ffmpeg_mod.FFmpegExecutor(temp_dir=str(tmp_path / "temp"), db=db).encode(task)

    # 验证：输出文件被探测并保存
    assert len(saved_snaps) == 1
    s = saved_snaps[0]
    assert s.library_folder_id == 3
    assert s.relative_path == "subdir/movie_zcompressed.mkv"
    assert s.video_codec == "av1"
    assert s.probe_ok is True


def _make_strategy(name, encoder):
    from leanreel.domain.models import Strategy
    return Strategy.from_dict({
        "name": name,
        "video": {"encoder": encoder, "cq": 28, "preset": "p6", "pix_fmt": "yuv420p10le", "gpu": True},
        "audio": {"mode": "keep_original"},
        "subtitle": {"mode": "keep_all"},
        "filters": {},
    })
```

- [ ] **Step 2: Run the new test, verify it fails**

Run: `pytest tests/test_ffmpeg.py::test_sync_file_snapshot_probes_output_and_saves -v`
Expected: FAIL — `_sync_file_snapshot` not called yet

- [ ] **Step 3: Add test — source deleted removes old snapshot**

```python
def test_sync_file_snapshot_deletes_source_when_deleted(monkeypatch, tmp_path):
    """源文件被删除时，移除源文件的 file_snapshot 条目"""
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask
    from leanreel.domain.models import FileSnapshot

    deleted_params = []
    saved_snaps = []

    class FakeDb:
        def execute(self, sql, params=None):
            if sql.strip().startswith("SELECT id FROM file_snapshot"):
                return [{"id": 99}]
            if sql.strip().startswith("DELETE FROM file_snapshot"):
                deleted_params.append(params)
            return []

        def update_compression_runtime(self, record_id, **kwargs):
            pass

        def finish_compression(self, record_id, **kwargs):
            pass

    class FakeRepo:
        def __init__(self, db):
            pass

        def save(self, snap):
            saved_snaps.append(snap)

        def load_all(self, folder_id):
            return []

    class FakeProbe:
        def __init__(self, ffprobe_path=None):
            pass

        def probe(self, file_path, library_folder_id=0):
            return FileSnapshot(
                library_folder_id=library_folder_id,
                video_codec="av1",
                video_width=1920, video_height=1080,
                size_bytes=500, duration_seconds=100.0,
                probe_ok=True,
            )

    def fake_run_ffmpeg(cmd, progress_callback=None, cancel_event=None):
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x" * 500)
        return 0, ""

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr("leanreel.services.audit._ffmpeg_version", lambda: "test")
    monkeypatch.setattr("leanreel.services.audit._dovi_version", lambda: "")
    monkeypatch.setattr("leanreel.infrastructure.repository.SnapshotRepository", FakeRepo)
    monkeypatch.setattr("leanreel.executor.probe.FFprobeRunner", FakeProbe)

    snap = FileSnapshot(
        video_codec="h264",
        library_folder_id=5,
        relative_path="anime/ep01.mkv",
        file_name="ep01.mkv",
        size_bytes=1000,
        duration_seconds=100.0,
    )
    task = EncodeTask(
        file_name="ep01.mkv",
        input_path=str(tmp_path / "ep01.mkv"),
        output_path=str(tmp_path / "ep01_zcompressed.mkv"),
        strategy=_make_strategy("CQ28", "av1_nvenc"),
        snapshot=snap,
        original_size=1000,
        history_id=42,
    )
    task._delete_source = True  # 模拟 delete_source 开启
    db = FakeDb()

    ffmpeg_mod.FFmpegExecutor(temp_dir=str(tmp_path / "temp"), db=db).encode(task)

    # 验证：新文件已保存
    assert len(saved_snaps) == 1
    assert saved_snaps[0].relative_path == "anime/ep01_zcompressed.mkv"

    # 验证：源文件条目被删除
    assert len(deleted_params) == 1
    assert deleted_params[0] == [5, "anime/ep01.mkv"]
```

- [ ] **Step 4: Run the new test, verify it fails**

Run: `pytest tests/test_ffmpeg.py::test_sync_file_snapshot_deletes_source_when_deleted -v`
Expected: FAIL

- [ ] **Step 5: Add test — library_folder_id=0 skips silently**

```python
def test_sync_file_snapshot_skips_when_folder_id_zero(monkeypatch, tmp_path):
    """library_folder_id 为 0 时跳过同步"""
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask
    from leanreel.domain.models import FileSnapshot

    probe_calls = []

    class FakeDb:
        def execute(self, sql, params=None):
            if sql.strip().startswith("SELECT id FROM file_snapshot"):
                return [{"id": 99}]
            return []

        def update_compression_runtime(self, record_id, **kwargs):
            pass

        def finish_compression(self, record_id, **kwargs):
            pass

    class FakeRepo:
        def __init__(self, db):
            pass

        def save(self, snap):
            pass

    class FakeProbe:
        def __init__(self, ffprobe_path=None):
            pass

        def probe(self, file_path, library_folder_id=0):
            probe_calls.append(file_path)
            return FileSnapshot(library_folder_id=library_folder_id, probe_ok=True)

    def fake_run_ffmpeg(cmd, progress_callback=None, cancel_event=None):
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x" * 500)
        return 0, ""

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr("leanreel.services.audit._ffmpeg_version", lambda: "test")
    monkeypatch.setattr("leanreel.services.audit._dovi_version", lambda: "")
    monkeypatch.setattr("leanreel.infrastructure.repository.SnapshotRepository", FakeRepo)
    monkeypatch.setattr("leanreel.executor.probe.FFprobeRunner", FakeProbe)

    snap = FileSnapshot(
        video_codec="h264",
        library_folder_id=0,  # 关键：folder_id 为 0
        relative_path="orphan.mkv",
        file_name="orphan.mkv",
        size_bytes=1000,
        duration_seconds=100.0,
    )
    task = EncodeTask(
        file_name="orphan.mkv",
        input_path=str(tmp_path / "orphan.mkv"),
        output_path=str(tmp_path / "orphan_zcompressed.mkv"),
        strategy=_make_strategy("CQ28", "av1_nvenc"),
        snapshot=snap,
        original_size=1000,
        history_id=42,
    )
    db = FakeDb()

    ffmpeg_mod.FFmpegExecutor(temp_dir=str(tmp_path / "temp"), db=db).encode(task)

    # library_folder_id=0 → 不应触发探测
    assert len(probe_calls) == 0
```

- [ ] **Step 6: Run the new test, verify it fails**

Run: `pytest tests/test_ffmpeg.py::test_sync_file_snapshot_skips_when_folder_id_zero -v`
Expected: FAIL

- [ ] **Step 7: Add test — probe failure doesn't crash encode**

```python
def test_sync_file_snapshot_probe_failure_is_silent(monkeypatch, tmp_path):
    """探测失败时静默吞掉异常，不影响编码成功状态"""
    from leanreel.executor import ffmpeg as ffmpeg_mod
    from leanreel.executor.worker import EncodeTask
    from leanreel.domain.models import FileSnapshot, TaskStatus

    class FakeDb:
        def execute(self, sql, params=None):
            if sql.strip().startswith("SELECT id FROM file_snapshot"):
                return [{"id": 99}]
            return []

        def update_compression_runtime(self, record_id, **kwargs):
            pass

        def finish_compression(self, record_id, **kwargs):
            pass

    class FakeRepo:
        def __init__(self, db):
            pass

        def save(self, snap):
            pass

    class FailingProbe:
        def __init__(self, ffprobe_path=None):
            pass

        def probe(self, file_path, library_folder_id=0):
            raise RuntimeError("ffprobe crashed")

    def fake_run_ffmpeg(cmd, progress_callback=None, cancel_event=None):
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x" * 500)
        return 0, ""

    monkeypatch.setattr(ffmpeg_mod, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr("leanreel.services.audit._ffmpeg_version", lambda: "test")
    monkeypatch.setattr("leanreel.services.audit._dovi_version", lambda: "")
    monkeypatch.setattr("leanreel.infrastructure.repository.SnapshotRepository", FakeRepo)
    monkeypatch.setattr("leanreel.executor.probe.FFprobeRunner", FailingProbe)

    snap = FileSnapshot(
        video_codec="h264",
        library_folder_id=3,
        relative_path="show.mkv",
        file_name="show.mkv",
        size_bytes=1000,
        duration_seconds=100.0,
    )
    task = EncodeTask(
        file_name="show.mkv",
        input_path=str(tmp_path / "show.mkv"),
        output_path=str(tmp_path / "show_zcompressed.mkv"),
        strategy=_make_strategy("CQ28", "av1_nvenc"),
        snapshot=snap,
        original_size=1000,
        history_id=42,
    )
    db = FakeDb()

    # 不应抛异常
    ffmpeg_mod.FFmpegExecutor(temp_dir=str(tmp_path / "temp"), db=db).encode(task)

    # 编码状态仍为 COMPLETED
    assert task.status == TaskStatus.COMPLETED
```

- [ ] **Step 8: Run the new test, verify it fails**

Run: `pytest tests/test_ffmpeg.py::test_sync_file_snapshot_probe_failure_is_silent -v`
Expected: FAIL

- [ ] **Step 9: Commit**

```bash
git add tests/test_ffmpeg.py
git commit -m "test: add failing tests for _sync_file_snapshot after encode"
```

---

### Task 2: Implement `_sync_file_snapshot` and integrate call site

**Files:**
- Modify: `leanreel/executor/ffmpeg.py`

- [ ] **Step 1: Add `_sync_file_snapshot` method to `FFmpegExecutor`**

Insert after the `cancel` method (before `_emit_progress`), or at the end of the class:

```python
    def _sync_file_snapshot(self, task, final_output, source_was_deleted):
        """编码成功后：探测输出文件 → 写入 file_snapshot；源删除时清理旧条目。

        尽力而为 — 任何异常静默吞掉，不影响编码主流程。
        """
        snap = task.snapshot
        library_folder_id = int(getattr(snap, "library_folder_id", 0) or 0)
        if not library_folder_id or self._db is None:
            return
        try:
            from leanreel.executor.probe import FFprobeRunner
            from leanreel.infrastructure.repository import SnapshotRepository

            repo = SnapshotRepository(self._db)
            probe = FFprobeRunner()

            # 计算输出文件的 relative_path（与源文件同目录）
            source_rel = str(getattr(snap, "relative_path", "") or "")
            source_dir = os.path.dirname(source_rel)
            output_rel = os.path.join(source_dir, final_output.name) if source_dir else final_output.name

            # 探测新文件
            new_snap = probe.probe(str(final_output), library_folder_id)
            new_snap.relative_path = output_rel
            new_snap.file_mtime = final_output.stat().st_mtime
            new_snap.probe_ok = True
            repo.save(new_snap)

            # 删除源文件条目
            if source_was_deleted:
                self._db.execute(
                    "DELETE FROM file_snapshot WHERE library_folder_id=? AND relative_path=?",
                    [library_folder_id, source_rel],
                )
        except Exception:
            pass
```

- [ ] **Step 2: Call `_sync_file_snapshot` from `encode()` — in the audit block, after source deletion**

In `encode()`, inside the `if not getattr(task, "_output_discarded", False):` block, after the source deletion lines (after line 344):

Replace:
```python
                    if getattr(task, "_delete_source", False) and 0 < task.compressed_size < task.original_size:
                        _delete_source_file(task.input_path)
                        _finish_task(task, status=TaskStatus.COMPLETED.value, progress=100.0, source_deleted=1, ffmpeg_command=cmd_str)
                except Exception:
                    import traceback
                    traceback.print_exc()
```

With:
```python
                    source_was_deleted = False
                    if getattr(task, "_delete_source", False) and 0 < task.compressed_size < task.original_size:
                        _delete_source_file(task.input_path)
                        _finish_task(task, status=TaskStatus.COMPLETED.value, progress=100.0, source_deleted=1, ffmpeg_command=cmd_str)
                        source_was_deleted = True

                    # ── 自动同步 file_snapshot ──
                    self._sync_file_snapshot(task, final_output, source_was_deleted)
                except Exception:
                    import traceback
                    traceback.print_exc()
```

- [ ] **Step 3: Run all 4 new tests to verify they pass**

Run: `pytest tests/test_ffmpeg.py::test_sync_file_snapshot_probes_output_and_saves tests/test_ffmpeg.py::test_sync_file_snapshot_deletes_source_when_deleted tests/test_ffmpeg.py::test_sync_file_snapshot_skips_when_folder_id_zero tests/test_ffmpeg.py::test_sync_file_snapshot_probe_failure_is_silent -v`
Expected: 4 PASS

- [ ] **Step 4: Run full ffmpeg test suite to check no regressions**

Run: `pytest tests/test_ffmpeg.py -v --tb=short`
Expected: all 64 tests PASS

- [ ] **Step 5: Commit**

```bash
git add leanreel/executor/ffmpeg.py tests/test_ffmpeg.py
git commit -m "feat: auto-sync file_snapshot after encode — probe output, cleanup deleted source metadata"
```

---

### Task 3: Final verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -q --tb=short`
Expected: 508+ passed (same 2 pre-existing failures in test_strategy/test_main are OK)

- [ ] **Step 2: Verify integration — manually review the diff**

```bash
git diff HEAD~1 -- leanreel/executor/ffmpeg.py
```

Confirm:
- `_sync_file_snapshot` called only inside `not discarded` block
- Called AFTER `_delete_source_file` to correctly track `source_was_deleted`
- Wrapped in existing `try/except` so failures don't escape
- No change to `__init__` signature
