# LeanReel Robustness Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the highest-risk review findings around probe/cache trust, dual-view consistency, queue identity, safe output handling, and user-facing recoverability.

**Architecture:** Keep the current PySide6 widget architecture intact, but introduce stable file identity and persisted diagnostics at the existing boundaries. Favor small TDD fixes over a broad table-model rewrite so each change is verifiable and low-risk.

**Tech Stack:** Python 3.11, PySide6, SQLite, pytest, FFmpeg/FFprobe wrappers.

---

## Assumptions

- Product expectations are defined by `README.md`, `PRODUCT.md`, `DESIGN.md`, and current tests.
- A media file identity is `(library_folder_id, relative_path)`, matching the SQLite uniqueness contract.
- Probe failures should be diagnosable after app restart.
- Existing `_SS` outputs are user data and must not be silently destroyed.
- This pass will not replace the table widget with a model/delegate architecture; it will remove the highest-risk inconsistencies first.

## Constraints

- Preserve existing public workflows and test expectations unless a test encodes a reviewed bug.
- Do not revert unrelated dirty workspace files.
- Keep UI copy consistent with the existing localized app strings.
- Avoid adding new runtime dependencies.

## Measurable Success Criteria

- Full suite passes: `py -m pytest -q`.
- Targeted suites pass: `py -m pytest tests/test_probe.py tests/test_scanner.py tests/test_snapshot_repository.py tests/test_main_window.py tests/test_queue_panel.py tests/test_library.py tests/test_ffmpeg.py -q`.
- A failed probe saves and reloads `probe_error`.
- Same-size/same-mtime cache rows with missing codec/width/height are re-probed.
- Flat and tree checked state remains consistent across view switches and filters.
- Duplicate basenames in the queue update the correct row by task identity.
- Existing output files are preserved if move-out fails.

## Internal Agent Simulation

- Builder: implement narrow helpers at existing seams: repository migration, scanner cache predicate, file-list key helpers, queue row keying, output move helper.
- Reviewer: watch for identity regressions where `relative_path` alone still leaks across folders.
- Tester: add failing tests first for each bug, confirm red, implement minimal green, then run targeted and full suites.
- Performance: prefer O(1) maps for row and tree item lookup; lazy tree construction is a follow-up unless needed for correctness.

## Edge Cases, Failure Modes, Risks

- Two folders can both contain `Movie.mkv`; all overrides, selections, and queue updates must remain distinct.
- A temporary FFprobe timeout can persist as a failed snapshot and must show the original cause after reload.
- Existing bad cache rows created by older versions may have `probe_ok=1` but empty codec or dimensions.
- Sorting a table changes visual row order; filters must not depend on stale row indexes.
- Existing `_SS` outputs may be locked, read-only, or valid prior runs.
- In-flight scan callbacks may arrive after folder deletion; this remains a follow-up if outside this pass.

---

### Task 1: Persist Probe Diagnostics And Reprobe Incomplete Cache

**Files:**
- Modify: `leanreel/data/database.py`
- Modify: `leanreel/core/repository.py`
- Modify: `leanreel/core/scanner.py`
- Test: `tests/test_snapshot_repository.py`
- Test: `tests/test_scanner.py`

- [ ] **Step 1: Write failing repository tests**

Add tests proving `probe_error` round-trips and migration adds the column:

```python
def test_save_roundtrips_probe_error(repo, folder_id):
    snap = make_snap(folder_id, rel_path="bad.mkv", file_name="bad.mkv", probe_ok=False)
    snap.probe_error = "ffprobe timed out after 30s"

    repo.save(snap)

    loaded = repo.get_cached(folder_id, "bad.mkv")
    assert loaded is not None
    assert loaded.probe_ok is False
    assert loaded.probe_error == "ffprobe timed out after 30s"
```

- [ ] **Step 2: Verify repository tests fail**

Run: `py -m pytest tests/test_snapshot_repository.py::test_save_roundtrips_probe_error -q`

Expected: FAIL because `probe_error` is not persisted.

- [ ] **Step 3: Add DB column and repository mapping**

Add `probe_error TEXT DEFAULT ''` to `file_snapshot`, migrate it, include it in insert/update params, and load it into `FileSnapshot.probe_error`.

- [ ] **Step 4: Write failing scanner cache tests**

Add tests where cached rows have the same size/mtime but `probe_ok=True` with empty `video_codec` or zero dimensions, and assert `Scanner.scan_folder()` / `scan_folder_fast_batch()` schedule or run a re-probe.

- [ ] **Step 5: Add shared cache completeness predicate**

Implement `is_probe_complete(snapshot)` in `scanner.py` requiring `probe_ok`, `video_codec`, `video_width`, and `video_height`. Use it in both synchronous and fast scan cache decisions.

- [ ] **Step 6: Verify**

Run: `py -m pytest tests/test_snapshot_repository.py tests/test_scanner.py -q`

Expected: PASS.

### Task 2: Stabilize File Identity And Dual-View Checked State

**Files:**
- Modify: `leanreel/gui/file_list.py`
- Modify: `leanreel/main.py`
- Test: `tests/test_main_window.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing dual-view tests**

Add tests for flat checked -> tree checked, tree checked -> flat checked, checked filter in tree mode, and duplicate `relative_path` across different `library_folder_id` values.

- [ ] **Step 2: Verify tests fail**

Run: `py -m pytest tests/test_main_window.py -q`

Expected: FAIL on checked state/filter or duplicate-path behavior.

- [ ] **Step 3: Add stable UI key helpers**

Represent keys internally as `(library_folder_id, relative_path)`, store them in `Qt.UserRole`, and keep a shared `_checked_keys` set. Preserve `get_checked_relative_paths()` for compatibility, and add `get_checked_file_keys()`.

- [ ] **Step 4: Render both views from shared checked state**

When either view changes a checkbox, update `_checked_keys`; when switching views or rebuilding tree, set checkbox state from `_checked_keys`.

- [ ] **Step 5: Apply filters to tree**

Use the same filter predicate for table rows and tree leaves; hide parent folders when all children are hidden.

- [ ] **Step 6: Update app task selection path**

Use `get_checked_file_keys()` in `_on_start_requested()` and key `strategy_overrides` by the same stable key where needed.

- [ ] **Step 7: Verify**

Run: `py -m pytest tests/test_main_window.py tests/test_main.py -q`

Expected: PASS.

### Task 3: Queue Rows Use Task Identity

**Files:**
- Modify: `leanreel/gui/queue_panel.py`
- Test: `tests/test_queue_panel.py`

- [ ] **Step 1: Write failing duplicate basename test**

Create two tasks with the same `file_name` and different `input_path`, update the second task, and assert only the second row changes.

- [ ] **Step 2: Verify test fails**

Run: `py -m pytest tests/test_queue_panel.py::test_queue_updates_duplicate_basenames_by_input_path -q`

Expected: FAIL because update currently matches by visible file name.

- [ ] **Step 3: Store task row keys**

Set `row.setProperty("task_key", task.input_path or task.file_name)` in `add_task_row()` and match the same key in `update_task_row()`.

- [ ] **Step 4: Add path tooltip**

Set the name label tooltip to `task.input_path` so users can distinguish duplicate basenames.

- [ ] **Step 5: Verify**

Run: `py -m pytest tests/test_queue_panel.py -q`

Expected: PASS.

### Task 4: Safer Output Move-Out

**Files:**
- Modify: `leanreel/executor/ffmpeg.py`
- Test: `tests/test_ffmpeg.py`

- [ ] **Step 1: Write failing output-preservation test**

Patch `shutil.move` or `Path.unlink` to fail during move-out with an existing final output and assert the existing file remains intact.

- [ ] **Step 2: Verify test fails**

Run: `py -m pytest tests/test_ffmpeg.py -q`

Expected: FAIL under the new preservation assertion.

- [ ] **Step 3: Add atomic-ish replace helper**

Move the encoded temp output to a sibling staging path, verify it exists and has nonzero size, then use `os.replace`. If any step fails, preserve the previous final output and remove only staging/temp artifacts owned by the current task.

- [ ] **Step 4: Verify**

Run: `py -m pytest tests/test_ffmpeg.py tests/test_worker.py -q`

Expected: PASS.

### Task 5: Duplicate Folder Recovery And Build Extra

**Files:**
- Modify: `leanreel/core/library.py`
- Modify: `leanreel/main.py`
- Modify: `pyproject.toml`
- Test: `tests/test_library.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing duplicate folder tests**

Assert `LibraryManager.add_folder()` raises `ValueError` for the same normalized path in the same library, and app folder addition catches the error into a status message.

- [ ] **Step 2: Verify tests fail**

Run: `py -m pytest tests/test_library.py tests/test_main.py -q`

Expected: FAIL because duplicate folder insertion relies on SQLite errors.

- [ ] **Step 3: Normalize and validate folder paths**

Normalize with `os.path.normcase(os.path.normpath(path))` for comparison, keep stored path normalized, and raise `ValueError` before insert.

- [ ] **Step 4: Catch app-level folder add errors**

Wrap `_on_folder_added()` setup in `try/except ValueError` and set a concise status instead of letting Qt slot exceptions escape.

- [ ] **Step 5: Add build dependency extra**

Add `[project.optional-dependencies].build = ["pyinstaller>=6.0"]` or include it in the existing optional dependency table without changing runtime dependencies.

- [ ] **Step 6: Verify**

Run: `py -m pytest tests/test_library.py tests/test_main.py -q`

Expected: PASS.

---

## Final Verification

- [ ] Run `py -m pytest -q`.
- [ ] Run `py -m compileall -q leanreel tests`.
- [ ] Review `git diff --stat` and spot-check changed files.

## Review Coverage Mapping

- Functional completeness: Tasks 1, 2, 5.
- Robustness and anti-interference: Tasks 1, 3, 4, 5.
- Performance: Task 2 reduces row lookup drift and tree/filter inconsistencies; larger model/delegate rewrite remains a follow-up.
- Data integrity and consistency: Tasks 1, 2, 3, 4.
- User friendliness and lower debugging cost: Tasks 1, 3, 5, plus follow-up logging/history work.

## Follow-Up Backlog

- Replace table/tree widgets with a shared `QAbstractTableModel` and delegates for large libraries.
- Add rotating app logs and Help menu diagnostics actions.
- Write compression history records and expose a history/details panel.
- Add ffmpeg idle/global timeout and poll-based cancellation.
- Preflight temp free space and support direct encode fallback.
- Invalidate in-flight scans when folders/libraries are deleted.

## Confidence

Initial plan confidence: `0.82`.

Main uncertainties: how much duplicate-path identity refactoring can be completed without touching more UI call sites, and whether existing `_SS` replacement is an intentional user workflow. Verification will raise or lower this confidence based on targeted tests and full-suite results.
