# UI Responsiveness Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make UI responsiveness a small, testable contract so slow cache, scan, probe, and strategy work cannot accidentally move back onto the Qt main thread.

**Architecture:** Keep the current signal-based design. Add one tiny thread-contract module, enforce it at UI mutation boundaries, keep slow work behind existing background threads, and add regression tests around the known freeze patterns. Do not introduce a full job framework in this pass.

**Tech Stack:** Python, PySide6, pytest, pytest-qt, standard `threading`.

---

## Assumptions, Constraints, And Success Criteria

**Assumptions**
- The Qt main thread is the only thread allowed to mutate widgets, Qt models, and `FileTableStore`.
- Slow work includes filesystem discovery, cache loading, ffprobe/probe callbacks, and hardware/strategy prioritization.
- Current signal names are already a good boundary and should be preserved.

**Constraints**
- Avoid broad refactors.
- Do not introduce asyncio, a custom scheduler, or a job framework.
- Keep existing app behavior and user-visible flow unchanged.
- Tests must run with the existing `py -3 -m pytest` workflow.

**Measurable Success Criteria**
- `FileTableStore.rebuild()`, `FileTableStore.update_row()`, and checked-state mutations raise in debug/test mode when called from a worker thread after the main thread is captured.
- Known slow paths still return quickly from UI-facing handlers when fake slow operations sleep for 150 ms.
- Probe worker callbacks only emit `probe_result`; the actual store/model update happens on the main thread.
- Repeated visible row updates under a filter do not emit full layout rebuilds.
- Full test suite passes.

## File Structure

- Create: `leanreel/core/threading_contract.py`
  - Single responsibility: record the GUI thread and provide small assertion helpers.
- Modify: `leanreel/data/file_store.py`
  - Single responsibility remains data storage; add write-boundary checks before mutating rows or selection state.
- Modify: `leanreel/main.py`
  - Single responsibility remains orchestration; capture the main thread during startup and assert UI commit slots run there.
- Modify: `tests/test_spec_compliance.py`
  - Add focused regression tests for the freeze-prone flows that already live in this file.
- Create: `tests/test_threading_contract.py`
  - Unit tests for the thread-contract helper and `FileTableStore` mutation boundary.
- Create: `docs/engineering/ui-responsiveness-contract.md`
  - A short engineering note listing the rules future code must follow.

---

### Task 1: Add The Thread Contract Helper

**Files:**
- Create: `leanreel/core/threading_contract.py`
- Create: `tests/test_threading_contract.py`

- [ ] **Step 1: Write failing tests for the helper**

Create `tests/test_threading_contract.py` with:

```python
import threading

import pytest

from leanreel.core import threading_contract


def setup_function():
    threading_contract._reset_for_tests()


def test_require_main_thread_allows_captured_thread():
    threading_contract.capture_main_thread()

    threading_contract.require_main_thread("store update")


def test_require_main_thread_rejects_worker_thread():
    threading_contract.capture_main_thread()
    errors = []

    def worker():
        try:
            threading_contract.require_main_thread("store update")
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "store update" in errors[0]
    assert "main thread" in errors[0]


def test_forbid_main_thread_rejects_captured_thread():
    threading_contract.capture_main_thread()

    with pytest.raises(RuntimeError, match="cache loading"):
        threading_contract.forbid_main_thread("cache loading")


def test_forbid_main_thread_allows_worker_thread():
    threading_contract.capture_main_thread()
    errors = []

    def worker():
        try:
            threading_contract.forbid_main_thread("cache loading")
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors == []
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
py -3 -m pytest tests/test_threading_contract.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `threading_contract`.

- [ ] **Step 3: Implement the minimal helper**

Create `leanreel/core/threading_contract.py`:

```python
"""Small runtime checks for keeping slow work off the Qt main thread."""

from __future__ import annotations

import threading

_MAIN_THREAD_ID: int | None = None


def capture_main_thread() -> int:
    """Record and return the thread that owns UI mutations."""
    global _MAIN_THREAD_ID
    if _MAIN_THREAD_ID is None:
        _MAIN_THREAD_ID = threading.get_ident()
    return _MAIN_THREAD_ID


def is_main_thread() -> bool:
    """Return True when running on the captured main thread."""
    return _MAIN_THREAD_ID is not None and threading.get_ident() == _MAIN_THREAD_ID


def require_main_thread(action: str = "UI mutation") -> None:
    """Raise if a UI/data mutation happens outside the captured main thread."""
    if _MAIN_THREAD_ID is None:
        return
    if threading.get_ident() != _MAIN_THREAD_ID:
        raise RuntimeError(f"{action} must run on the main thread")


def forbid_main_thread(action: str = "slow operation") -> None:
    """Raise if slow work is attempted on the captured main thread."""
    if _MAIN_THREAD_ID is None:
        return
    if threading.get_ident() == _MAIN_THREAD_ID:
        raise RuntimeError(f"{action} must not run on the main thread")


def _reset_for_tests() -> None:
    global _MAIN_THREAD_ID
    _MAIN_THREAD_ID = None
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```powershell
py -3 -m pytest tests/test_threading_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add leanreel/core/threading_contract.py tests/test_threading_contract.py
git commit -m "test: add UI thread contract helper"
```

---

### Task 2: Guard Store Mutations

**Files:**
- Modify: `leanreel/data/file_store.py`
- Modify: `tests/test_threading_contract.py`

- [ ] **Step 1: Add failing tests for store write boundaries**

Append to `tests/test_threading_contract.py`:

```python
from leanreel.data.file_store import FileRow, FileTableStore
from leanreel.data.models import FileSnapshot


def _snapshot(name="a.mkv"):
    return FileSnapshot(
        library_folder_id=1,
        relative_path=name,
        file_name=name,
        size_bytes=10,
        probe_ok=False,
    )


def test_file_table_store_rejects_worker_thread_rebuild_after_capture():
    threading_contract.capture_main_thread()
    store = FileTableStore()
    errors = []

    def worker():
        try:
            store.rebuild([FileRow(snap=_snapshot())])
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "FileTableStore.rebuild" in errors[0]


def test_file_table_store_rejects_worker_thread_update_after_capture():
    threading_contract.capture_main_thread()
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snapshot())])
    errors = []

    def worker():
        try:
            store.update_row((1, "a.mkv"), _snapshot())
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "FileTableStore.update_row" in errors[0]
```

- [ ] **Step 2: Run the store boundary tests and verify they fail**

Run:

```powershell
py -3 -m pytest tests/test_threading_contract.py::test_file_table_store_rejects_worker_thread_rebuild_after_capture tests/test_threading_contract.py::test_file_table_store_rejects_worker_thread_update_after_capture -q
```

Expected: FAIL because worker-thread store writes are still allowed.

- [ ] **Step 3: Add store write assertions**

Modify `leanreel/data/file_store.py`.

Add import near the existing imports:

```python
from leanreel.core.threading_contract import require_main_thread
```

At the top of each write method, add the exact guard:

```python
def rebuild(self, rows: list[FileRow], strategies=None, keep_checked: bool = True):
    require_main_thread("FileTableStore.rebuild")
    ...

def update_row(self, key: tuple[int, str], snap: FileSnapshot, match=None, decision=None):
    require_main_thread("FileTableStore.update_row")
    ...

def set_checked(self, key: tuple[int, str], state: bool):
    require_main_thread("FileTableStore.set_checked")
    ...

def toggle_checked(self, key: tuple[int, str]):
    require_main_thread("FileTableStore.toggle_checked")
    ...
```

- [ ] **Step 4: Run store tests and existing freeze regression tests**

Run:

```powershell
py -3 -m pytest tests/test_threading_contract.py tests/test_spec_compliance.py::test_f1_probe_results_are_committed_on_main_thread -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add leanreel/data/file_store.py tests/test_threading_contract.py
git commit -m "fix: guard file store mutations to UI thread"
```

---

### Task 3: Guard Application UI Commit Slots

**Files:**
- Modify: `leanreel/main.py`
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Add failing test for a worker-thread UI commit**

Append to `tests/test_spec_compliance.py`:

```python
def test_f1_probe_commit_slot_rejects_worker_thread_direct_call(qtbot):
    """Probe commits are UI work and should reject direct worker-thread calls."""
    _qapp()
    import threading
    from types import SimpleNamespace

    import pytest

    from leanreel.core import threading_contract
    from leanreel.main import Application

    threading_contract._reset_for_tests()
    threading_contract.capture_main_thread()
    errors = []

    fake_app = SimpleNamespace(
        _scan_token=1,
        _probe_token=1,
        current_snapshots=[_snap(library_folder_id=1, relative_path="a.mkv", file_name="a.mkv")],
        services=SimpleNamespace(matcher=SimpleNamespace(match=lambda snap: None)),
        notifier=SimpleNamespace(
            probed=SimpleNamespace(emit=lambda snap, match: None),
            progress=SimpleNamespace(emit=lambda done, total: None),
            all_done=SimpleNamespace(emit=lambda: None),
        ),
        file_panel=SimpleNamespace(
            _decision_display=lambda snap, match: _decision(),
            refresh_btn=SimpleNamespace(setEnabled=lambda value: None),
            set_progress_visible=lambda value: None,
        ),
        store=SimpleNamespace(update_row=lambda key, snap, match=None, decision=None: None),
        _probe_done=0,
        _probe_total=1,
        _refresh_running=True,
    )

    def worker():
        try:
            Application._on_probe_result(
                fake_app,
                _snap(library_folder_id=1, relative_path="a.mkv", file_name="a.mkv"),
                1,
            )
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "Application._on_probe_result" in errors[0]

    threading_contract._reset_for_tests()
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
py -3 -m pytest tests/test_spec_compliance.py::test_f1_probe_commit_slot_rejects_worker_thread_direct_call -q
```

Expected: FAIL because `_on_probe_result` does not yet assert main-thread affinity.

- [ ] **Step 3: Capture main thread and guard UI commit slots**

Modify `leanreel/main.py`.

Add import:

```python
from leanreel.core.threading_contract import capture_main_thread, require_main_thread
```

Call `capture_main_thread()` at the start of `_init_state`:

```python
def _init_state(self):
    capture_main_thread()
    self.current_snapshots: list = []
    ...
```

Add commit-slot assertions:

```python
def _on_strategies_ready(self, strategies):
    require_main_thread("Application._on_strategies_ready")
    ...

def _on_library_cache_loaded(self, snapshots, folder_paths, my_token):
    require_main_thread("Application._on_library_cache_loaded")
    ...

def _on_scan_ready(self, placeholders, folder_inputs, my_token):
    require_main_thread("Application._on_scan_ready")
    ...

def _on_scan_resolved(self, resolved, folder_inputs, my_token):
    require_main_thread("Application._on_scan_resolved")
    ...

def _on_probe_result(self, snap, my_token):
    require_main_thread("Application._on_probe_result")
    ...
```

- [ ] **Step 4: Run commit-slot and existing thread-boundary tests**

Run:

```powershell
py -3 -m pytest tests/test_spec_compliance.py::test_f1_probe_commit_slot_rejects_worker_thread_direct_call tests/test_spec_compliance.py::test_f1_scan_ready_offloads_slow_cache_resolution tests/test_spec_compliance.py::test_f1_library_selection_offloads_slow_cache_loading tests/test_spec_compliance.py::test_f1_probe_results_are_committed_on_main_thread -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add leanreel/main.py tests/test_spec_compliance.py
git commit -m "fix: assert UI commit slots run on main thread"
```

---

### Task 4: Add A Small Slow-Work Guard At Call Sites

**Files:**
- Modify: `leanreel/main.py`
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Add failing test for cache loading staying off the main thread**

Append to `tests/test_spec_compliance.py`:

```python
def test_f1_library_cache_loader_rejects_main_thread_cache_work(qtbot):
    """The cache loader must execute load_cached in the background worker."""
    _qapp()
    import threading
    from types import SimpleNamespace

    from leanreel.controllers.signals import AppSignals
    from leanreel.core import threading_contract
    from leanreel.main import Application

    threading_contract._reset_for_tests()
    threading_contract.capture_main_thread()
    load_threads = []

    class RecordingScanner:
        def load_cached(self, folder_id, path):
            load_threads.append(threading.get_ident())
            return []

    fake_notifier = AppSignals()
    fake_app = SimpleNamespace(
        _scan_token=1,
        services=SimpleNamespace(
            db=SimpleNamespace(get_folders_for_library=lambda lib_id: [SimpleNamespace(id=1, path="C:/videos")]),
            scanner=RecordingScanner(),
        ),
        current_folder_paths={},
        strategy_overrides={},
        current_snapshots=[],
        notifier=fake_notifier,
        win=SimpleNamespace(set_status=lambda text: None),
        _populate_file_list=lambda snapshots, fast=False: None,
    )
    fake_notifier.library_cache_loaded.connect(
        lambda snapshots, paths, token: Application._on_library_cache_loaded(fake_app, snapshots, paths, token)
    )

    Application._on_library_selected(fake_app, 1)

    qtbot.waitUntil(lambda: bool(load_threads), timeout=1000)
    assert all(thread_id != threading_contract.capture_main_thread() for thread_id in load_threads)
    threading_contract._reset_for_tests()
```

- [ ] **Step 2: Run the test**

Run:

```powershell
py -3 -m pytest tests/test_spec_compliance.py::test_f1_library_cache_loader_rejects_main_thread_cache_work -q
```

Expected: PASS today if the current background behavior is intact. If it fails, fix the regression before continuing.

- [ ] **Step 3: Add explicit slow-work guards inside existing workers**

Modify the import in `leanreel/main.py`:

```python
from leanreel.core.threading_contract import capture_main_thread, forbid_main_thread, require_main_thread
```

Inside each existing worker function, before the slow call, add the guard:

```python
def _detect_in_background():
    forbid_main_thread("strategy prioritization")
    prioritized = _prioritize_strategies(strategies)
    self.notifier.strategies_ready.emit(prioritized)
```

```python
def _load_cache_in_background():
    forbid_main_thread("library cache loading")
    snapshots: list = []
    ...
```

```python
def _resolve_cache_in_background():
    forbid_main_thread("scan cache resolution")
    try:
        ...
```

```python
def _scan_in_background():
    forbid_main_thread("file discovery")
    ...
```

```python
def _prepare_in_background():
    forbid_main_thread("single-folder file discovery")
    ...
```

- [ ] **Step 4: Run the slow-path tests**

Run:

```powershell
py -3 -m pytest tests/test_main.py::test_init_services_does_not_run_nvenc_detection_synchronously tests/test_spec_compliance.py::test_f1_scan_ready_offloads_slow_cache_resolution tests/test_spec_compliance.py::test_f1_library_selection_offloads_slow_cache_loading tests/test_spec_compliance.py::test_f1_library_cache_loader_rejects_main_thread_cache_work -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add leanreel/main.py tests/test_spec_compliance.py
git commit -m "test: guard slow UI-triggered work off main thread"
```

---

### Task 5: Add A Bounded Model-Update Regression

**Files:**
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Add a failing-or-passing budget test for repeated filtered updates**

Append to `tests/test_spec_compliance.py`:

```python
def test_f1_repeated_filtered_updates_do_not_rebuild_layout():
    """Visible probe updates under an active filter should remain incremental."""
    import time

    from leanreel.data.file_store import FileRow, FileTableStore
    from leanreel.gui.adapters.file_table_model import FileTableModel

    _qapp()
    store = FileTableStore()
    view = QTableView()
    model = FileTableModel(store, view)
    view.setModel(model)

    protected = _decision(status_key="protected", processable=False)
    rows = [
        FileRow(snap=_snap(relative_path=f"f{i}.mkv", file_name=f"f{i}.mkv"), decision=protected)
        for i in range(1000)
    ]
    store.rebuild(rows)
    model.set_filter("protected")
    layout_changes = []
    model.layoutChanged.connect(lambda: layout_changes.append(True))

    start = time.perf_counter()
    for i in range(200):
        store.update_row(
            (7, f"f{i}.mkv"),
            _snap(relative_path=f"f{i}.mkv", file_name=f"f{i}.mkv", size_bytes=2048 + i),
        )
    elapsed = time.perf_counter() - start

    assert layout_changes == []
    assert model.rowCount() == 1000
    assert elapsed < 0.5
```

- [ ] **Step 2: Run the budget test**

Run:

```powershell
py -3 -m pytest tests/test_spec_compliance.py::test_f1_repeated_filtered_updates_do_not_rebuild_layout -q
```

Expected: PASS if the current incremental update fix is intact. If it fails, inspect `leanreel/gui/adapters/file_table_model.py::_on_row_updated` and preserve `dataChanged` for visible-to-visible updates.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_spec_compliance.py
git commit -m "test: budget repeated filtered row updates"
```

---

### Task 6: Document The Minimal Responsiveness Contract

**Files:**
- Create: `docs/engineering/ui-responsiveness-contract.md`

- [ ] **Step 1: Create the engineering note**

Create `docs/engineering/ui-responsiveness-contract.md`:

```markdown
# UI Responsiveness Contract

LeanReel keeps the Qt main thread reserved for UI event handling and light commits.

## Rules

1. Slow work runs in a worker thread.
   - File discovery
   - Cache loading
   - Cache resolution
   - ffprobe/probe callbacks
   - Hardware detection and strategy prioritization

2. Worker threads return data through `AppSignals`.
   - Workers may emit signals.
   - Workers must not mutate Qt widgets, Qt models, or `FileTableStore`.

3. UI commit slots run on the main thread.
   - `_on_scan_ready`
   - `_on_scan_resolved`
   - `_on_library_cache_loaded`
   - `_on_probe_result`
   - `_on_strategies_ready`

4. Large UI updates should be incremental when possible.
   - Per-row probe updates should emit `dataChanged`.
   - Avoid `layoutChanged` or model reset for visible-to-visible row updates.
   - Hidden views should be marked dirty and rebuilt only when shown.

## Tests To Add For New Slow Paths

When adding a UI-triggered operation that may touch disk, subprocesses, hardware, network paths, or many rows:

1. Add a fake slow dependency that sleeps for at least 150 ms.
2. Call the public UI handler.
3. Assert the handler returns in less than 50 ms.
4. Assert the slow dependency ran outside the captured main thread.
5. Assert the final store/model mutation happened on the main thread.
```

- [ ] **Step 2: Review the note for scope creep**

Confirm the document does not require a new job framework, scheduler, or architecture rewrite.

- [ ] **Step 3: Commit**

```powershell
git add docs/engineering/ui-responsiveness-contract.md
git commit -m "docs: record UI responsiveness contract"
```

---

### Task 7: Full Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run focused responsiveness tests**

Run:

```powershell
py -3 -m pytest tests/test_threading_contract.py tests/test_main.py::test_init_services_does_not_run_nvenc_detection_synchronously tests/test_spec_compliance.py::test_f1_scan_ready_offloads_slow_cache_resolution tests/test_spec_compliance.py::test_f1_library_selection_offloads_slow_cache_loading tests/test_spec_compliance.py::test_f1_probe_results_are_committed_on_main_thread tests/test_spec_compliance.py::test_f1_probe_commit_slot_rejects_worker_thread_direct_call tests/test_spec_compliance.py::test_f1_library_cache_loader_rejects_main_thread_cache_work tests/test_spec_compliance.py::test_f1_repeated_filtered_updates_do_not_rebuild_layout -q
```

Expected: PASS.

- [ ] **Step 2: Run the full test suite**

Run:

```powershell
py -3 -m pytest -q
```

Expected: PASS. If pytest emits the known Windows temp symlink cleanup `PermissionError` after reporting all tests passed, record it as an environment cleanup warning, not a product test failure.

- [ ] **Step 3: Manual smoke test**

Run the app, rebuild cache on a library with enough files to notice UI stalls, and verify:

```powershell
py -3 -m leanreel.main
```

Expected:
- Window can be moved during rebuild.
- File list can scroll during rebuild.
- Progress updates continue.
- Switching flat/tree view does not freeze before data is visible.

- [ ] **Step 4: Final commit if Task 7 caused any small test-only adjustment**

Only run this if files changed during verification:

```powershell
git add leanreel tests docs
git commit -m "test: verify UI responsiveness guardrails"
```

---

## Internal Agent Review

**Builder perspective:** This is intentionally small. It adds a contract module, attaches it to existing write boundaries, and preserves the current signal design.

**Reviewer perspective:** The plan avoids overdesign because it does not add a job framework, task registry, or async runtime. The most important review point is keeping `threading_contract.py` dependency-free so it remains safe to import from core/data code.

**Tester perspective:** Tests cover helper behavior, store mutation boundaries, known slow UI paths, direct worker-thread commit mistakes, and repeated filtered model updates.

**Performance perspective:** This prevents the two highest-risk regressions: slow work returning to UI handlers and high-frequency row updates triggering full layout rebuilds. It does not fully solve huge one-time model resets; that remains a separate measured optimization if real data proves it necessary.

## Risks And Failure Modes

- Existing tests that mutate `FileTableStore` from worker threads may fail after the guard is added; fix those tests to route through signals instead of weakening the guard.
- Direct calls to commit slots in tests may need `threading_contract._reset_for_tests()` to avoid leaking captured thread state.
- If a worker emits a signal to a non-Qt fake object in tests, PySide may not queue the call the same way as production; keep tests explicit about thread identity.
- A full `store.rebuild()` for very large libraries can still be expensive on the main thread. This plan guards boundaries first; chunked rebuilds should be a follow-up only if measured.

## Self-Review

**Spec coverage:** The plan addresses the cache rebuild freeze class by enforcing thread responsibility, keeping slow work off the UI thread, preventing worker-thread UI commits, and adding performance-oriented regression tests.

**Placeholder scan:** No task relies on unspecified behavior. Every code-changing task includes concrete code snippets and exact test commands.

**Type consistency:** `capture_main_thread`, `require_main_thread`, `forbid_main_thread`, `is_main_thread`, and `_reset_for_tests` are defined before they are used. Store and application guard names match the tests.

## Confidence

Confidence: 0.86.

Main uncertainty: whether very large real libraries require chunked `store.rebuild()` beyond these guardrails. This plan deliberately leaves that as a measured follow-up to avoid overdesign.
