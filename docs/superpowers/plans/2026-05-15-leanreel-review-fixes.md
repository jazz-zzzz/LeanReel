# LeanReel Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代码审查中确认的架构、功能流程、性能和易用性风险，并为每个风险补上能失败再通过的测试。

**Architecture:** 采用小步 TDD，不做大规模重构；优先修正数据一致性、编码输出安全、UI 行状态一致性和扫描会话隔离。保留现有 `gui / core / executor / data` 分层，只在 `Application`、`Scanner`、`WorkerManager` 和相关面板中收窄状态边界。

**Tech Stack:** Python 3.11+, PySide6, SQLite, FFmpeg/dovi_tool wrappers, pytest, pytest-qt style widget tests

---

## Assumptions, Constraints, And Success Criteria

**Assumptions**
- 当前工作分支是 `master`，且已确认与 `origin/master` 同步。
- 本轮修复不改变产品定位：仍是本地桌面批量视频压缩工具。
- 测试运行命令使用 Windows launcher：`py -m pytest -q` 和 `py -m compileall -q leanreel tests`。
- 不引入新第三方依赖；所有修复使用标准库和现有 PySide6/pytest。

**Constraints**
- 不重写 UI，不改动打包资源目录结构。
- 不覆盖用户已有配置目录中的策略文件；只改仓库内代码和测试。
- 不改变默认 `_SS` 输出命名语义，只修复临时输出冲突。
- 不在计划中依赖真实 FFmpeg 编码；编码相关测试继续 mock 外部进程。

**Measurable Success Criteria**
- 新增或修改的目标测试先能在当前实现下失败。
- 修复后 `py -m pytest -q` 全部通过。
- 修复后 `py -m compileall -q leanreel tests` 通过。
- 排序后后台探测更新不会写错表格行。
- 两个同名输出文件并发编码时临时文件路径不同。
- `begin -> execute -> rollback` 后不会留下已插入数据。
- `keep_original` 模式不会因为语言是 `und` 而丢掉所有音轨。
- 多次快速扫描不会互相覆盖待探测任务。

## Risk Review

**Builder View**
- 保持现有模块结构，按失败风险从底层到 UI 修复。
- 先修能破坏数据或输出文件的风险，再修用户可见状态问题。

**Reviewer View**
- 重点审查状态所有权：数据库事务由 `Database` 管，扫描会话由 `ScanBatch` 管，编码任务统计由 `EncodeTask/WorkerManager` 管，表格行定位由当前 UI 状态实时查询。

**Tester View**
- 每个 bug 至少一个回归测试。
- 对涉及分支的逻辑，测试包含非平凡数据，例如 `und` 音轨、同名不同目录输出、排序后行更新。

**Performance View**
- 扫描仍使用线程池。
- SQLite 写入不在本计划中改为多连接，但通过扫描会话隔离减少并发状态覆盖；如后续仍遇到锁，再单独做写入串行化计划。

**Edge Cases And Failure Modes**
- `rollback()` 在无显式事务时调用应保持安全。
- 临时目录和最终目录相同也要能设置任务大小。
- `keep_original` 仍应移除 commentary 音轨，但不应按语言过滤主音轨。
- 表格排序、用户选择策略、后台探测完成可以任意交错。
- 取消任务后进度百分比不能卡在未完成。
- 删除库或移除文件夹后，旧快照不能继续参与新一轮编码。

---

### Task 1: Fix Explicit SQLite Transactions

**Files:**
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/data/database.py:12-112`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_database.py`

- [ ] **Step 1: Write the failing rollback test**

Add this test to `tests/test_database.py` after `test_write_persists_across_connections`:

```python
def test_explicit_transaction_rolls_back_all_writes(tmp_path: Path):
    db_path = tmp_path / "rollback.db"
    db = Database(str(db_path))
    try:
        db.begin()
        db.execute("INSERT INTO library (name) VALUES (?)", ["Rollback Film"])
        db.execute("INSERT INTO library (name) VALUES (?)", ["Rollback TV"])
        db.rollback()

        rows = db.execute("SELECT name FROM library ORDER BY id")
    finally:
        db.close()

    assert rows == []
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
py -m pytest tests/test_database.py::test_explicit_transaction_rolls_back_all_writes -q
```

Expected before implementation: FAIL because `rows` contains `Rollback Film` and `Rollback TV`.

- [ ] **Step 3: Implement explicit transaction tracking**

Modify `leanreel/data/database.py`:

```python
class Database:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._explicit_transaction = False
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def execute(self, sql: str, params=None):
        try:
            cur = self.conn.execute(sql, params or [])
            rows = [dict(row) for row in cur.fetchall()] if cur.description else []
            if self.conn.in_transaction and not self._explicit_transaction:
                self.conn.commit()
            return rows
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            self._explicit_transaction = False
            raise

    def begin(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self._explicit_transaction = True

    def commit(self):
        self.conn.commit()
        self._explicit_transaction = False

    def rollback(self):
        self.conn.rollback()
        self._explicit_transaction = False
```

- [ ] **Step 4: Run database tests**

Run:

```bash
py -m pytest tests/test_database.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leanreel/data/database.py tests/test_database.py
git commit -m "fix: preserve explicit database transactions"
```

---

### Task 2: Prevent Temporary Encoding File Collisions And Record Sizes

**Files:**
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/main.py:71-96`
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/executor/ffmpeg.py:70-145`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_main.py`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_ffmpeg.py`

- [ ] **Step 1: Write failing task size test**

Add this test to `tests/test_main.py` near the existing `build_encode_tasks` tests:

```python
def test_build_encode_tasks_sets_original_size_from_snapshot():
    from leanreel.main import build_encode_tasks
    from leanreel.core.strategy import Strategy
    from leanreel.data.models import FileSnapshot

    snap = FileSnapshot(
        library_folder_id=1,
        relative_path="movie.mkv",
        file_name="movie.mkv",
        size_bytes=987654321,
    )
    strategy = Strategy(name="Balanced")

    tasks = build_encode_tasks([snap], {1: "C:/media"}, strategy)

    assert len(tasks) == 1
    assert tasks[0].original_size == 987654321
```

- [ ] **Step 2: Write failing temp collision test**

Add this test to `tests/test_ffmpeg.py` after `test_ffmpeg_executor_runs_built_command`:

```python
def test_ffmpeg_executor_uses_unique_temp_paths_for_same_output_names(monkeypatch, balanced_strategy, tmp_path):
    from leanreel.executor import ffmpeg
    from leanreel.executor.worker import EncodeTask

    commands = []

    def fake_run(cmd, progress_callback=None, cancel_event=None):
        commands.append(cmd)
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_text("encoded")
        return 0, ""

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_run)
    temp_dir = tmp_path / "temp"

    first_output = tmp_path / "Film A" / "movie_SS.mkv"
    second_output = tmp_path / "Film B" / "movie_SS.mkv"

    for output in (first_output, second_output):
        task = EncodeTask(
            file_name="movie.mkv",
            input_path=str(tmp_path / "source.mkv"),
            output_path=str(output),
            strategy=balanced_strategy,
            snapshot=FileSnapshot(video_codec="h264", size_bytes=1000),
        )
        FFmpegExecutor(temp_dir=str(temp_dir)).encode(task)
        assert task.compressed_size == len("encoded")

    assert len(commands) == 2
    assert commands[0][-1] != commands[1][-1]
    assert first_output.exists()
    assert second_output.exists()
```

- [ ] **Step 3: Run new tests and verify failures**

Run:

```bash
py -m pytest tests/test_main.py::test_build_encode_tasks_sets_original_size_from_snapshot tests/test_ffmpeg.py::test_ffmpeg_executor_uses_unique_temp_paths_for_same_output_names -q
```

Expected before implementation: FAIL because `original_size` remains `0` and both temp paths use `movie_SS.mkv`.

- [ ] **Step 4: Set original size when building tasks**

Modify the `EncodeTask(...)` construction in `leanreel/main.py`:

```python
        tasks.append(EncodeTask(
            file_name=snap.file_name,
            input_path=str(input_path),
            output_path=str(make_output_path(input_path)),
            strategy_name=selected_strategy.name,
            strategy=selected_strategy,
            snapshot=snap,
            original_size=snap.size_bytes,
        ))
```

- [ ] **Step 5: Use per-output temp subdirectories and record compressed size**

Modify `FFmpegExecutor.encode()` in `leanreel/executor/ffmpeg.py`.

Add import:

```python
import hashlib
```

Replace temp path setup:

```python
        final_output = Path(task.output_path)
        temp_dir = self._get_temp_dir()
        output_key = hashlib.sha1(str(final_output.resolve()).encode("utf-8")).hexdigest()[:12]
        task_temp_dir = temp_dir / output_key
        task_temp_dir.mkdir(parents=True, exist_ok=True)
        temp_output = task_temp_dir / final_output.name
        rpu_file: Optional[Path] = None
        dv_output: Optional[Path] = None
```

Replace RPU and DV temp path lines:

```python
                rpu_file = task_temp_dir / f"{final_output.stem}.rpu"
```

```python
                dv_output = task_temp_dir / f"{final_output.stem}_dv{final_output.suffix}"
```

After successful output placement, set size:

```python
            if temp_output.resolve() == final_output.resolve():
                if final_output.exists():
                    task.compressed_size = final_output.stat().st_size
                return

            final_output.parent.mkdir(parents=True, exist_ok=True)

            if final_output.exists():
                final_output.unlink()

            shutil.move(str(temp_output), str(final_output))
            if final_output.exists():
                task.compressed_size = final_output.stat().st_size
```

In `finally`, remove an empty per-task directory:

```python
            if rpu_file and rpu_file.exists():
                rpu_file.unlink()
            try:
                task_temp_dir.rmdir()
            except OSError:
                pass
```

- [ ] **Step 6: Run encoding and main tests**

Run:

```bash
py -m pytest tests/test_main.py tests/test_ffmpeg.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add leanreel/main.py leanreel/executor/ffmpeg.py tests/test_main.py tests/test_ffmpeg.py
git commit -m "fix: isolate encoding temp outputs"
```

---

### Task 3: Keep Original Audio Without Dropping Unknown-Language Tracks

**Files:**
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/executor/ffmpeg_builder.py:73-91`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_ffmpeg.py`

- [ ] **Step 1: Add failing regression test for `und` audio**

Add this test near the audio filtering tests in `tests/test_ffmpeg.py`:

```python
def test_build_keep_original_keeps_unknown_language_audio():
    from leanreel.data.models import AudioTrack

    strategy = Strategy.from_dict({
        "name": "keep-original",
        "audio": {
            "mode": "keep_original",
            "remove_commentary": True,
            "preferred_languages": ["chi", "zho", "eng"],
        },
        "subtitle": {"mode": "keep_all"},
        "video": {},
        "filters": {},
    })
    snap = FileSnapshot(video_codec="h264", audio_tracks=[
        AudioTrack(codec="truehd", channels=8, language="und", title="Main Atmos"),
        AudioTrack(codec="aac", channels=2, language="eng", title="Commentary", is_commentary=True),
    ])

    cmd = FFmpegBuilder.build(snap, strategy, "in.mkv", "out.mkv")
    joined = " ".join(cmd)

    assert "-map 0:a:0" in joined
    assert "-map 0:a:1" not in joined
    assert "-c:a copy" in joined
```

- [ ] **Step 2: Update existing preferred-language test to use explicit filtering mode**

In `tests/test_ffmpeg.py`, change `test_build_filters_by_preferred_languages()` strategy audio block to:

```python
        "name": "test", "audio": {"mode": "strip_non_preferred", "preferred_languages": ["chi", "zho", "eng"]},
```

- [ ] **Step 3: Run audio tests and verify the new test fails**

Run:

```bash
py -m pytest tests/test_ffmpeg.py::test_build_keep_original_keeps_unknown_language_audio tests/test_ffmpeg.py::test_build_filters_by_preferred_languages -q
```

Expected before implementation: first test FAILS because no audio map is emitted for `und`.

- [ ] **Step 4: Change audio filtering semantics**

Modify `leanreel/executor/ffmpeg_builder.py` audio loop:

```python
            remove_commentary = audio_rule.remove_commentary or audio_rule.mode == "strip_commentary"
            filter_languages = audio_rule.mode == "strip_non_preferred"
            preferred = audio_rule.preferred_languages
            kept_audio = []
            for i, track in enumerate(audio_tracks):
                if remove_commentary and track.is_commentary:
                    continue
                if filter_languages and preferred and track.language not in preferred:
                    continue
                kept_audio.append(i)
```

Keep the existing fallback below it, but add a fallback when every probed audio track was removed:

```python
            if kept_audio:
                cmd.extend(["-c:a", "copy"])
            elif audio_rule.mode == "keep_original":
                cmd.extend(["-map", "0:a", "-c:a", "copy"])
```

- [ ] **Step 5: Run FFmpeg tests**

Run:

```bash
py -m pytest tests/test_ffmpeg.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add leanreel/executor/ffmpeg_builder.py tests/test_ffmpeg.py
git commit -m "fix: keep original audio tracks by default"
```

---

### Task 4: Update File Rows Correctly After Sorting

**Files:**
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/gui/file_list.py:180-386`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_main_window.py`

- [ ] **Step 1: Add failing sorted-update test**

Add this test after `test_file_list_sorts_size_and_estimated_savings_numerically()`:

```python
def test_file_list_updates_correct_row_after_sorting():
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    large = FileSnapshot(relative_path="large.mkv", file_name="large.mkv", size_bytes=10 * 1024**3, video_codec="h264")
    small = FileSnapshot(relative_path="small.mkv", file_name="small.mkv", size_bytes=1 * 1024**3, video_codec="h264")

    panel.populate(
        [large, small],
        {
            "large.mkv": MatchResult(strategy="A", estimate={"estimated_min_bytes": 1, "estimated_max_bytes": 2}),
            "small.mkv": MatchResult(strategy="B", estimate={"estimated_min_bytes": 1, "estimated_max_bytes": 2}),
        },
    )
    panel.table.sortItems(1, Qt.AscendingOrder)

    large.video_codec = "hevc"
    panel.update_snapshot_row(large)

    visible = {
        panel.table.item(row, 0).data(Qt.UserRole): panel.table.item(row, 2).text()
        for row in range(panel.table.rowCount())
    }
    assert visible["large.mkv"].startswith("hevc")
    assert visible["small.mkv"].startswith("h264")
    panel.close()
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
py -m pytest tests/test_main_window.py::test_file_list_updates_correct_row_after_sorting -q
```

Expected before implementation: FAIL because `small.mkv` row receives the `hevc` update.

- [ ] **Step 3: Replace stale row index lookup with live table lookup**

Modify `_find_row_by_relative_path()` in `leanreel/gui/file_list.py`:

```python
    def _find_row_by_relative_path(self, relative_path: str) -> int | None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == relative_path:
                return row
        return None
```

Leave `_row_index` in place if other tests expect it, but stop relying on it for mutable UI updates.

- [ ] **Step 4: Run GUI list tests**

Run:

```bash
py -m pytest tests/test_main_window.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leanreel/gui/file_list.py tests/test_main_window.py
git commit -m "fix: update sorted file list rows by path"
```

---

### Task 5: Isolate Fast Scan Pending Jobs Per Scan Batch

**Files:**
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/core/scanner.py:1-408`
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/main.py:20-380`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_scanner.py`

- [ ] **Step 1: Add failing scanner batch isolation test**

Add this test to `tests/test_scanner.py` near `test_scanner_probes_changed_files_concurrently`:

```python
def test_fast_scan_batches_keep_independent_pending_jobs(tmp_path: Path):
    db = Database(str(tmp_path / "scan_batch.db"))
    try:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "a.mkv").write_bytes(b"first")
        (second / "b.mkv").write_bytes(b"second")

        scanner = Scanner(db, probe_runner=MockFFprobe(), max_workers=1)
        first_batch = scanner.scan_folder_fast_batch(1, str(first))
        second_batch = scanner.scan_folder_fast_batch(2, str(second))

        assert [job[1] for job in first_batch.pending_jobs] == ["a.mkv"]
        assert [job[1] for job in second_batch.pending_jobs] == ["b.mkv"]
    finally:
        db.close()
```

- [ ] **Step 2: Run the new scanner test and verify it fails**

Run:

```bash
py -m pytest tests/test_scanner.py::test_fast_scan_batches_keep_independent_pending_jobs -q
```

Expected before implementation: FAIL because `scan_folder_fast_batch` does not exist.

- [ ] **Step 3: Add `ScanBatch` and batch API**

Add imports and dataclass to `leanreel/core/scanner.py`:

```python
from dataclasses import asdict, dataclass
```

Add after `VIDEO_EXTENSIONS`:

```python
@dataclass
class ScanBatch:
    snapshots: list[FileSnapshot]
    pending_jobs: list[tuple[int, str, str, int]]
```

Extract the body of `scan_folder_fast()` into a new method:

```python
    def scan_folder_fast_batch(self, library_folder_id: int, folder_path: str) -> ScanBatch:
        folder_path = os.path.normpath(folder_path)
        found_files = find_video_files(folder_path)
        results: list[FileSnapshot] = []
        pending: list[tuple[int, str, str, int]] = []

        cached_dict = {s.relative_path: s for s in self._repo.load_all(library_folder_id)}

        for rel_path, abs_path in found_files:
            try:
                st = os.stat(abs_path)
                file_size, file_mtime = st.st_size, st.st_mtime
            except OSError:
                file_size, file_mtime = 0, 0.0

            existing = cached_dict.get(rel_path)
            if existing and existing.size_bytes == file_size and existing.file_mtime == file_mtime:
                results.append(existing)
                continue

            if existing and not existing.probe_ok and existing.file_mtime == file_mtime:
                results.append(existing)
                continue

            placeholder = FileSnapshot(
                library_folder_id=library_folder_id,
                relative_path=rel_path,
                file_name=os.path.basename(abs_path),
                size_bytes=file_size,
                file_mtime=file_mtime,
            )
            results.append(placeholder)
            pending.append((library_folder_id, rel_path, abs_path, file_size))

        return ScanBatch(snapshots=results, pending_jobs=pending)
```

Make existing `scan_folder_fast()` a compatibility wrapper:

```python
    def scan_folder_fast(self, library_folder_id: int, folder_path: str) -> list[FileSnapshot]:
        batch = self.scan_folder_fast_batch(library_folder_id, folder_path)
        with self._probe_lock:
            self._pending_jobs = list(batch.pending_jobs)
        return batch.snapshots
```

- [ ] **Step 4: Add explicit background probe method for a provided job list**

Add this method to `Scanner`:

```python
    def start_background_probe_jobs(
        self,
        jobs: list[tuple[int, str, str, int]],
        on_done: Callable[[FileSnapshot], None],
        on_finished: Callable[[], None] | None = None,
        on_progress: Callable[[], None] | None = None,
    ):
        import concurrent.futures

        jobs = list(jobs)

        def _probe_one(job):
            folder_id, rel_path, abs_path, file_size = job
            try:
                fmtime = os.path.getmtime(abs_path)
            except OSError:
                fmtime = 0.0
            probe = self._get_probe()
            try:
                snap = probe.probe(abs_path, folder_id)
                snap.relative_path = rel_path
                snap.file_mtime = fmtime
                snap.probe_ok = True
            except Exception:
                snap = FileSnapshot(
                    library_folder_id=folder_id,
                    relative_path=rel_path,
                    file_name=os.path.basename(abs_path),
                    size_bytes=file_size,
                    file_mtime=fmtime,
                    probe_ok=False,
                )
            self._repo.save(snap)
            if on_done:
                on_done(snap)
            if on_progress:
                on_progress()

        def _run():
            if jobs:
                workers = min(self.max_workers, len(jobs))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    list(pool.map(_probe_one, jobs))
            if on_finished:
                on_finished()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t
```

Then simplify existing `start_background_probe()` to delegate:

```python
    def start_background_probe(self, on_done, on_finished=None, on_progress=None):
        with self._probe_lock:
            jobs = list(self._pending_jobs)
            self._pending_jobs = []
        return self.start_background_probe_jobs(jobs, on_done, on_finished, on_progress)
```

- [ ] **Step 5: Update application scan signal and merge behavior**

In `leanreel/main.py`, change `ProbeNotifier.scan_finished`:

```python
    scan_finished = Signal(object, int, str, object)  # snapshots, folder_id, folder_path, pending_jobs
```

In `_on_folder_added()` background worker:

```python
        def _scan_in_background():
            batch = self.services.scanner.scan_folder_fast_batch(folder.id, path)
            self.notifier.scan_finished.emit(batch.snapshots, folder.id, path, batch.pending_jobs)
```

Change `_on_scan_finished` signature and merge state:

```python
    def _on_scan_finished(self, snapshots, folder_id, folder_path, pending_jobs):
        self.current_folder_paths[folder_id] = folder_path
        self.current_snapshots = [
            s for s in self.current_snapshots
            if s.library_folder_id != folder_id
        ] + list(snapshots)
        self.strategy_overrides = {
            path: strategy for path, strategy in self.strategy_overrides.items()
            if any(s.relative_path == path for s in self.current_snapshots)
        }

        self._populate_file_list(self.current_snapshots)

        if len(snapshots) == 0:
            self.win.set_status(f"未找到视频文件：{folder_path}")
            return

        pending = len(pending_jobs)
```

At the bottom of the pending branch, call the explicit job method:

```python
            self.services.scanner.start_background_probe_jobs(
                list(pending_jobs), on_probed, on_finished, on_progress
            )
```

- [ ] **Step 6: Run scanner tests**

Run:

```bash
py -m pytest tests/test_scanner.py -q
```

Expected: PASS.

- [ ] **Step 7: Run main tests**

Run:

```bash
py -m pytest tests/test_main.py tests/test_main_window.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add leanreel/core/scanner.py leanreel/main.py tests/test_scanner.py
git commit -m "fix: isolate scan pending jobs"
```

---

### Task 6: Refresh UI State After Library Or Folder Removal

**Files:**
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/main.py:285-430`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_main.py`

- [ ] **Step 1: Add unit tests for state cleanup helpers**

Add these tests to `tests/test_main.py`:

```python
def test_remove_folder_state_filters_snapshots_and_paths():
    from leanreel.main import remove_folder_from_current_state
    from leanreel.data.models import FileSnapshot

    snapshots = [
        FileSnapshot(library_folder_id=1, relative_path="a.mkv"),
        FileSnapshot(library_folder_id=2, relative_path="b.mkv"),
    ]
    folder_paths = {1: "C:/one", 2: "C:/two"}
    overrides = {"a.mkv": object(), "b.mkv": object()}

    new_snapshots, new_paths, new_overrides = remove_folder_from_current_state(
        snapshots, folder_paths, overrides, folder_id=1
    )

    assert [s.relative_path for s in new_snapshots] == ["b.mkv"]
    assert new_paths == {2: "C:/two"}
    assert list(new_overrides) == ["b.mkv"]


def test_clear_current_state_returns_empty_collections():
    from leanreel.main import clear_current_state

    snapshots, folder_paths, overrides = clear_current_state()

    assert snapshots == []
    assert folder_paths == {}
    assert overrides == {}
```

- [ ] **Step 2: Run new tests and verify they fail**

Run:

```bash
py -m pytest tests/test_main.py::test_remove_folder_state_filters_snapshots_and_paths tests/test_main.py::test_clear_current_state_returns_empty_collections -q
```

Expected before implementation: FAIL because helper functions do not exist.

- [ ] **Step 3: Add pure state helpers**

Add these functions to `leanreel/main.py` after `build_encode_tasks()`:

```python
def clear_current_state():
    return [], {}, {}


def remove_folder_from_current_state(snapshots, folder_paths, strategy_overrides, folder_id: int):
    remaining_snapshots = [s for s in snapshots if s.library_folder_id != folder_id]
    remaining_paths = {fid: path for fid, path in folder_paths.items() if fid != folder_id}
    remaining_relative_paths = {s.relative_path for s in remaining_snapshots}
    remaining_overrides = {
        path: strategy
        for path, strategy in strategy_overrides.items()
        if path in remaining_relative_paths
    }
    return remaining_snapshots, remaining_paths, remaining_overrides
```

- [ ] **Step 4: Route delete/remove signals through application handlers**

Change `_wire_signals()`:

```python
        self.lib_panel.library_deleted.connect(self._on_library_deleted)
        self.lib_panel.folder_removed.connect(self._on_folder_removed)
```

Add handlers:

```python
    def _on_library_deleted(self, lib_id):
        self.services.lib_mgr.delete_library(lib_id)
        self.current_snapshots, self.current_folder_paths, self.strategy_overrides = clear_current_state()
        self.file_panel.populate([], {}, self.services.strategies)
        self._refresh_libraries()
        self.win.set_status("库已删除")

    def _on_folder_removed(self, folder_id):
        self.services.lib_mgr.remove_folder(folder_id)
        self.current_snapshots, self.current_folder_paths, self.strategy_overrides = remove_folder_from_current_state(
            self.current_snapshots,
            self.current_folder_paths,
            self.strategy_overrides,
            folder_id,
        )
        self._populate_file_list(self.current_snapshots)
        self._refresh_libraries()
        self.win.set_status("文件夹已移除")
```

- [ ] **Step 5: Run main tests**

Run:

```bash
py -m pytest tests/test_main.py tests/test_main_window.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add leanreel/main.py tests/test_main.py
git commit -m "fix: refresh state after library changes"
```

---

### Task 7: Make Queue Cancellation And Clearing Explicit

**Files:**
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/gui/queue_panel.py:34-170`
- Modify: `C:/Users/groun/Desktop/Vide Coding/LeanReel/leanreel/executor/worker.py:136-145`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_queue_panel.py`
- Test: `C:/Users/groun/Desktop/Vide Coding/LeanReel/tests/test_worker.py`

- [ ] **Step 1: Add failing queue button signal test**

Add this test to `tests/test_queue_panel.py`:

```python
def test_queue_panel_cancel_all_button_emits_cancel_signal(qtbot):
    from leanreel.gui.queue_panel import QueuePanel

    panel = QueuePanel()
    qtbot.addWidget(panel)
    emitted = []
    panel.cancel_requested.connect(emitted.append)

    panel.cancel_btn.click()

    assert emitted == [-1]
```

- [ ] **Step 2: Add worker progress test for cancelled tasks**

Add this test to `tests/test_worker.py`:

```python
def test_get_progress_counts_cancelled_as_terminal():
    from leanreel.executor.worker import WorkerManager, EncodeTask
    from leanreel.data.models import TaskStatus

    manager = WorkerManager(FakeExecutor())
    manager._tasks = [
        EncodeTask(file_name="done.mkv", input_path="", output_path="", status=TaskStatus.COMPLETED),
        EncodeTask(file_name="cancelled.mkv", input_path="", output_path="", status=TaskStatus.CANCELLED),
        EncodeTask(file_name="pending.mkv", input_path="", output_path="", status=TaskStatus.PENDING),
    ]

    progress = manager.get_progress()

    assert progress["completed"] == 1
    assert progress["cancelled"] == 1
    assert progress["pending"] == 1
    assert progress["percentage"] == pytest.approx((2 / 3) * 100)
```

- [ ] **Step 3: Run new tests and verify failures**

Run:

```bash
py -m pytest tests/test_queue_panel.py::test_queue_panel_cancel_all_button_emits_cancel_signal tests/test_worker.py::test_get_progress_counts_cancelled_as_terminal -q
```

Expected before implementation: FAIL because `cancel_btn` and `cancelled` progress do not exist.

- [ ] **Step 4: Replace runtime clear button with cancel-all button**

In `QueuePanel.setup_ui()`, replace the clear button setup:

```python
        self.cancel_btn = QPushButton("取消全部")
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(-1))
        self.clear_btn = QPushButton("清空已完成")
        self.clear_btn.clicked.connect(self.clear_all)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.clear_btn)
```

Keep `clear_all()` for explicit UI cleanup after completion.

- [ ] **Step 5: Count cancelled tasks in progress**

Modify `WorkerManager.get_progress()`:

```python
    @property
    def cancelled_count(self) -> int:
        return sum(1 for t in self._tasks if t.status == TaskStatus.CANCELLED)

    def get_progress(self) -> dict:
        terminal = self.completed_count + self.failed_count + self.cancelled_count
        return {
            "total": self.total_tasks,
            "completed": self.completed_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
            "cancelled": self.cancelled_count,
            "pending": self.total_tasks - terminal,
            "percentage": (terminal / max(self.total_tasks, 1)) * 100,
        }
```

- [ ] **Step 6: Update queue label to include cancelled count**

Modify `QueuePanel.update_progress()`:

```python
        self.total_label.setText(
            f"完成 {progress['completed']}/{progress['total']}  "
            f"跳过 {progress['skipped']}  "
            f"失败 {progress['failed']}  "
            f"取消 {progress.get('cancelled', 0)}"
        )
```

- [ ] **Step 7: Run queue and worker tests**

Run:

```bash
py -m pytest tests/test_queue_panel.py tests/test_worker.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add leanreel/gui/queue_panel.py leanreel/executor/worker.py tests/test_queue_panel.py tests/test_worker.py
git commit -m "fix: make queue cancellation explicit"
```

---

### Task 8: Full Regression Verification

**Files:**
- Verify only

- [ ] **Step 1: Run compile check**

Run:

```bash
py -m compileall -q leanreel tests
```

Expected: exit code `0`.

- [ ] **Step 2: Run full test suite**

Run:

```bash
py -m pytest -q
```

Expected: all tests pass. The starting baseline before this plan was `250 passed`; after implementing this plan, the total should increase because new regression tests were added.

- [ ] **Step 3: Review git diff**

Run:

```bash
git diff --stat
git diff -- leanreel tests
```

Expected:
- Code changes are limited to `leanreel/data/database.py`, `leanreel/main.py`, `leanreel/core/scanner.py`, `leanreel/executor/ffmpeg.py`, `leanreel/executor/ffmpeg_builder.py`, `leanreel/executor/worker.py`, `leanreel/gui/file_list.py`, `leanreel/gui/queue_panel.py`.
- Test changes are limited to targeted regression tests.
- No resource binaries or generated cache files are staged.

- [ ] **Step 4: Commit verification if previous tasks were not committed individually**

If the implementation was intentionally done as one batch, commit with:

```bash
git add leanreel tests
git commit -m "fix: harden LeanReel workflow state"
```

---

## Self-Review

**Spec Coverage**
- 架构：Task 5 和 Task 6 收窄扫描/库状态边界；没有做大规模重构，符合当前小型应用阶段。
- 功能流程完整性：Task 2、Task 3、Task 4、Task 5、Task 6、Task 7 覆盖编码输出、音轨、排序更新、扫描、删除、取消。
- 性能：Task 5 保持并发扫描并隔离 pending jobs；Task 2 避免并发编码临时文件互相影响。
- 易用性：Task 4、Task 6、Task 7 修正用户可见状态错误。
- 测试：每个修复任务都有新增或修改的失败测试，以及局部/全量验证命令。

**Placeholder Scan**
- 本计划不包含 `TBD`、`TODO`、`implement later` 或无代码的“写测试”描述。
- 每个代码修改步骤给出具体函数、片段和验证命令。

**Type Consistency**
- `ScanBatch.pending_jobs` 使用现有 tuple 形状 `tuple[int, str, str, int]`。
- `cancel_requested` 继续使用现有 `Signal(int)`。
- `EncodeTask.original_size` 和 `EncodeTask.compressed_size` 继续使用现有字段。
- `Database._explicit_transaction` 是内部布尔状态，不改变外部 API。

## Confidence And Open Questions

**Confidence:** 0.84

**Remaining Uncertainties**
- 真实 FFmpeg/Dolby Vision 编码链路仍需人工抽样验证画面、音轨和元数据；本计划只覆盖命令构建与文件状态。
- SQLite 多线程写入仍共用一个连接；本计划降低扫描会话覆盖风险，但没有彻底改为每线程连接或写入队列。
- UI 文案当前在部分终端显示为乱码；本计划不修复编码显示问题，因为它不是本次审查确认的核心流程风险。
