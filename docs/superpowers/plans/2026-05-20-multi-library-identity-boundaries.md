# Multi-Library Identity Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make multi-library and multi-folder identity explicit so UI state, scan results, tree nodes, strategy overrides, and encoding tasks cannot merge objects that merely share display names.

**Architecture:** Introduce small domain key aliases/helpers for file and directory identity, then migrate only the identity-sensitive maps/signals/indexes to those keys. Display fields such as `relative_path` and `folder_name` remain available for labels and sorting, but must not be used as unique identifiers across controller/store/adapter boundaries.

**Tech Stack:** Python 3.12, PySide6, pytest, pytest-qt, SQLite-backed LeanReel data model.

---

## Assumptions, Constraints, Success Criteria

**Assumptions**
- A library may contain multiple `library_folder` roots.
- Different folders may contain the same `relative_path`, such as `movie.mkv`.
- Different folders may contain the same visible directory path, such as `Season 1`.
- The visible tree is a view of current library files, not a persistent storage model.

**Constraints**
- Do not redesign the UI or replace `QTreeWidget`/`QTableView`.
- Do not change SQLite schema for this fix.
- Preserve current queue behavior: one active encoding batch at a time.
- Keep string-key compatibility only where tests or legacy call sites still require it, and never let compatibility paths override exact tuple keys.

**Measurable Success**
- Duplicate `relative_path` across folders no longer shares scan match state.
- Duplicate directory names across folders no longer merge into one tree node.
- Tree folder refresh targets the correct `library_folder_id`.
- Strategy overrides created by UI are stored as `(library_folder_id, relative_path)`.
- `py -3 -m pytest -q` passes.
- Static guard tests fail if identity-sensitive code reintroduces display-only keys.

---

## File Structure

- Modify `leanreel/domain/models.py`
  - Add explicit key aliases and helper methods for file and directory identity.
- Modify `leanreel/controllers/scan_controller.py`
  - Use file keys for scan match maps.
- Modify `leanreel/state/file_store.py`
  - Return directory stats keyed by explicit directory key, not display folder name.
- Modify `leanreel/gui/adapters/tree_adapter.py`
  - Use directory key for folder nodes and keep folder id on the node for refresh.
- Modify `leanreel/controllers/encoding_controller.py`
  - Remove strategy override fallback that lets bare `relative_path` affect encoding tasks when tuple keys exist.
- Modify `leanreel/gui/file_list.py`
  - Keep compatibility fallbacks local; make tuple key the normal path for UI signals.
- Test `tests/test_spec_compliance.py`
  - Add cross-folder duplicate identity tests.
- Test `tests/test_file_store.py`
  - Update folder stats tests to assert key shape and aggregation.
- Test `tests/test_tree_adapter.py`
  - Add duplicate tree directory tests and folder refresh target tests.
- Test `tests/test_main_window.py`
  - Keep existing UI contract tests aligned with tuple-key signals.

---

### Task 1: Add Explicit Identity Helpers

**Files:**
- Modify: `leanreel/domain/models.py:258-274`
- Test: `tests/test_file_store.py`

- [ ] **Step 1: Write failing tests for file and directory keys**

Add this test to `tests/test_file_store.py`:

```python
def test_file_row_identity_keys_include_library_folder_id():
    row = FileRow(snap=_snap(
        library_folder_id=42,
        relative_path="Season 1/E01.mkv",
        file_name="E01.mkv",
    ))

    assert row.key == (42, "Season 1/E01.mkv")
    assert row.directory_key == (42, "Season 1")
    assert row.folder_name == "Season 1"


def test_file_row_root_directory_key_includes_library_folder_id():
    row = FileRow(snap=_snap(
        library_folder_id=77,
        relative_path="movie.mkv",
        file_name="movie.mkv",
    ))

    assert row.key == (77, "movie.mkv")
    assert row.directory_key == (77, ".")
    assert row.folder_name == "."
```

- [ ] **Step 2: Run tests and verify red**

Run:

```powershell
py -3 -m pytest tests/test_file_store.py::test_file_row_identity_keys_include_library_folder_id tests/test_file_store.py::test_file_row_root_directory_key_includes_library_folder_id -q
```

Expected:

```text
FAILED ... AttributeError: 'FileRow' object has no attribute 'directory_key'
```

- [ ] **Step 3: Add minimal identity helpers**

Modify `leanreel/domain/models.py` near `FileRow`:

```python
FileKey = tuple[int, str]
DirectoryKey = tuple[int, str]


@dataclass
class FileRow:
    """One visible file row.

    ``key`` is the stable file identity: (library_folder_id, relative_path).
    ``directory_key`` is the stable tree directory identity:
    (library_folder_id, directory_relative_path).
    """
    snap: FileSnapshot
    match: MatchResult | None = field(default=None, repr=False)
    decision: FileDecisionDisplay | None = field(default=None, repr=False)

    @property
    def key(self) -> FileKey:
        return (self.snap.library_folder_id, self.snap.relative_path)

    @property
    def directory_key(self) -> DirectoryKey:
        return (self.snap.library_folder_id, self.folder_name)

    @property
    def folder_name(self) -> str:
        path = str(self.snap.relative_path).replace("\\", "/")
        parts = path.rsplit("/", 1)
        return parts[0] if len(parts) > 1 else "."
```

- [ ] **Step 4: Run tests and verify green**

Run:

```powershell
py -3 -m pytest tests/test_file_store.py::test_file_row_identity_keys_include_library_folder_id tests/test_file_store.py::test_file_row_root_directory_key_includes_library_folder_id -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```powershell
git add leanreel/domain/models.py tests/test_file_store.py
git commit -m "refactor: define stable media identity keys"
```

---

### Task 2: Key Scan Match Maps by File Identity

**Files:**
- Modify: `leanreel/controllers/scan_controller.py:125-143`
- Test: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write failing scan match isolation test**

Add this test to `tests/test_spec_compliance.py`:

```python
def test_scan_populate_matches_duplicate_relative_paths_by_file_key(qtbot):
    """Scan population must not let one folder's match leak to another folder."""
    _qapp()
    from types import SimpleNamespace
    from leanreel.controllers.scan_controller import ScanController
    from leanreel.domain.models import Strategy
    from leanreel.state.file_store import FileTableStore

    strategy = Strategy(name="Only Folder 2")

    class Matcher:
        def match(self, snap):
            return strategy if snap.library_folder_id == 2 else None

    panel = FileListPanel()
    qtbot.addWidget(panel)
    store = FileTableStore()
    panel.set_store(store)
    ctrl = SimpleNamespace(
        _services=SimpleNamespace(matcher=Matcher(), strategies=[strategy]),
        _file_panel=panel,
        _store=store,
    )
    snapshots = [
        _snap(library_folder_id=1, relative_path="movie.mkv", file_name="movie.mkv"),
        _snap(library_folder_id=2, relative_path="movie.mkv", file_name="movie.mkv"),
    ]

    ScanController._populate_file_list(ctrl, snapshots)

    decisions = {row.key: row.decision.strategy_text for row in store.rows()}
    assert decisions[(1, "movie.mkv")] == "跳过"
    assert decisions[(2, "movie.mkv")] == "Only Folder 2"
    panel.close()
```

- [ ] **Step 2: Run test and verify red**

Run:

```powershell
py -3 -m pytest tests/test_spec_compliance.py::test_scan_populate_matches_duplicate_relative_paths_by_file_key -q
```

Expected:

```text
FAILED ... assert 'Only Folder 2' == '跳过'
```

- [ ] **Step 3: Use file keys in scan match map**

Modify `leanreel/controllers/scan_controller.py`:

```python
    def _populate_file_list(self, snapshots) -> dict[tuple[int, str], MatchResult]:
        matched: dict[tuple[int, str], MatchResult] = {}
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
        rows = []
        for s in snapshots:
            key = (int(s.library_folder_id or 0), str(s.relative_path))
            m = matched.get(key)
            d = self._file_panel._decision_display(s, m)
            rows.append(FileRow(snap=s, match=m, decision=d))
        self._file_panel.set_strategy_lookup(self._services.strategies)
        self._store.rebuild(rows, strategies=self._services.strategies, keep_checked=False)
        self._file_panel._show_current_view()
        self._file_panel.refresh_summary(snapshots)
        if self._services.strategies and self._file_panel._flat_adapter:
            self._file_panel._flat_adapter.create_combo_cells(self._file_panel._create_strategy_combo)
        return matched
```

- [ ] **Step 4: Run targeted tests**

Run:

```powershell
py -3 -m pytest tests/test_spec_compliance.py::test_scan_populate_matches_duplicate_relative_paths_by_file_key tests/test_spec_compliance.py::test_strategy_combo_change_targets_duplicate_relative_path_by_file_key -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```powershell
git add leanreel/controllers/scan_controller.py tests/test_spec_compliance.py
git commit -m "fix: match scan rows by file identity"
```

---

### Task 3: Key Tree Directory Nodes by Directory Identity

**Files:**
- Modify: `leanreel/state/file_store.py:107-112`
- Modify: `leanreel/gui/adapters/tree_adapter.py:22-145`
- Test: `tests/test_tree_adapter.py`
- Test: `tests/test_file_store.py`

- [ ] **Step 1: Write failing store stats test**

Replace `test_store_folder_stats` in `tests/test_file_store.py` with:

```python
def test_store_folder_stats_keyed_by_directory_identity():
    store = FileTableStore()
    store.rebuild([
        FileRow(snap=_snap(library_folder_id=1, relative_path="S1/a.mkv", size_bytes=1000)),
        FileRow(snap=_snap(library_folder_id=1, relative_path="S1/b.mkv", size_bytes=2000)),
        FileRow(snap=_snap(library_folder_id=2, relative_path="S1/c.mkv", size_bytes=500)),
    ])

    stats = store.folder_stats()

    assert stats[(1, "S1")] == (3000, 2)
    assert stats[(2, "S1")] == (500, 1)
```

- [ ] **Step 2: Write failing tree node isolation test**

Add this test to `tests/test_tree_adapter.py`:

```python
def test_tree_adapter_keeps_duplicate_directory_names_separate(qtbot):
    store = FileTableStore()
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(7)
    TreeAdapter(store, tree)

    store.rebuild([
        _row(_snap(library_folder_id=1, relative_path="Season 1/E01.mkv", file_name="E01.mkv", size_bytes=1000), _make_decision()),
        _row(_snap(library_folder_id=2, relative_path="Season 1/E02.mkv", file_name="E02.mkv", size_bytes=2000), _make_decision()),
    ])

    assert tree.topLevelItemCount() == 2
    folder_ids = {
        tree.topLevelItem(0).data(0, Qt.UserRole),
        tree.topLevelItem(1).data(0, Qt.UserRole),
    }
    assert folder_ids == {1, 2}
```

- [ ] **Step 3: Run tests and verify red**

Run:

```powershell
py -3 -m pytest tests/test_file_store.py::test_store_folder_stats_keyed_by_directory_identity tests/test_tree_adapter.py::test_tree_adapter_keeps_duplicate_directory_names_separate -q
```

Expected:

```text
FAILED ... KeyError: (1, 'S1')
FAILED ... assert 1 == 2
```

- [ ] **Step 4: Change store folder stats to directory keys**

Modify `leanreel/state/file_store.py`:

```python
    def folder_stats(self) -> dict[tuple[int, str], tuple[int, int]]:
        """Return directory identity -> (total size, file count)."""
        stats: dict[tuple[int, str], tuple[int, int]] = {}
        for row in self._rows:
            size, count = stats.get(row.directory_key, (0, 0))
            stats[row.directory_key] = (size + row.snap.size_bytes, count + 1)
        return stats
```

- [ ] **Step 5: Change tree adapter folder maps to directory keys**

Modify `leanreel/gui/adapters/tree_adapter.py`:

```python
        self._folder_items: dict[tuple[int, str], QTreeWidgetItem] = {}
```

Modify `_rebuild_now()`:

```python
        stats = store.folder_stats()
        for i in range(store.count()):
            row = store.row_at(i)
            folder_key = row.directory_key
            folder = self._folder_items.get(folder_key)
            if folder is None:
                total, count = stats.get(folder_key, (0, 0))
                folder = _SortableTreeItem([row.folder_name, _format_bytes(total), str(count), "", "", "", ""])
                folder.setData(0, Qt.UserRole, row.key[0])
                folder.setData(1, Qt.UserRole, total)
                folder.setData(2, Qt.UserRole, count)
                font = folder.font(0)
                font.setBold(True)
                folder.setFont(0, font)
                self._folder_items[folder_key] = folder
                self._tree.addTopLevelItem(folder)
            child = self._render_child(row)
            self._child_by_key[row.key] = child
            folder.addChild(child)
```

Modify `_on_row_updated()`:

```python
        folder = self._folder_items.get(row.directory_key)
        if folder:
            stats = self._store.folder_stats()
            total, count = stats.get(row.directory_key, (0, 0))
            folder.setText(1, _format_bytes(total))
            folder.setData(1, Qt.UserRole, total)
            folder.setText(2, str(count))
            folder.setData(2, Qt.UserRole, count)
```

- [ ] **Step 6: Run targeted tests**

Run:

```powershell
py -3 -m pytest tests/test_file_store.py::test_store_folder_stats_keyed_by_directory_identity tests/test_tree_adapter.py::test_tree_adapter_keeps_duplicate_directory_names_separate tests/test_tree_adapter.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 7: Commit**

```powershell
git add leanreel/state/file_store.py leanreel/gui/adapters/tree_adapter.py tests/test_file_store.py tests/test_tree_adapter.py
git commit -m "fix: isolate tree folders by directory identity"
```

---

### Task 4: Remove Strategy Override String Leakage from Encoding

**Files:**
- Modify: `leanreel/controllers/encoding_controller.py:22-48`
- Test: `tests/test_encoding_controller.py`

- [ ] **Step 1: Write failing encoding override isolation test**

Add this test to `tests/test_encoding_controller.py`:

```python
def test_build_encode_tasks_ignores_bare_relative_path_override_when_file_key_absent(default_strategy, hq_strategy):
    snapshots = [
        FileSnapshot(
            library_folder_id=1,
            relative_path="movie.mkv",
            file_name="movie.mkv",
            size_bytes=1000,
            video_codec="h264",
        ),
        FileSnapshot(
            library_folder_id=2,
            relative_path="movie.mkv",
            file_name="movie.mkv",
            size_bytes=1000,
            video_codec="h264",
        ),
    ]

    tasks = build_encode_tasks(
        snapshots,
        {1: "C:/one", 2: "C:/two"},
        default_strategy,
        {"movie.mkv": hq_strategy},
    )

    assert [task.strategy_name for task in tasks] == ["均衡压缩", "均衡压缩"]
```

- [ ] **Step 2: Run test and verify red**

Run:

```powershell
py -3 -m pytest tests/test_encoding_controller.py::test_build_encode_tasks_ignores_bare_relative_path_override_when_file_key_absent -q
```

Expected:

```text
FAILED ... ['高质量压缩', '高质量压缩'] != ['均衡压缩', '均衡压缩']
```

- [ ] **Step 3: Use tuple key only for encoding overrides**

Modify `leanreel/controllers/encoding_controller.py`:

```python
def build_encode_tasks(
    snapshots,
    folder_paths: dict[int, str],
    strategy: Strategy,
    strategy_overrides: dict[tuple[int, str], Strategy] | None = None,
) -> list[EncodeTask]:
    tasks: list[EncodeTask] = []
    strategy_overrides = strategy_overrides or {}
    for snap in snapshots:
        if is_protected_source(snap):
            continue
        folder_path = folder_paths.get(snap.library_folder_id)
        if not folder_path:
            continue
        file_key = (int(snap.library_folder_id or 0), str(snap.relative_path))
        selected_strategy = strategy_overrides.get(file_key, strategy)
        input_path = Path(folder_path) / snap.relative_path
        tasks.append(EncodeTask(
            file_name=snap.file_name,
            input_path=str(input_path),
            output_path=str(make_output_path(input_path)),
            strategy_name=selected_strategy.name,
            strategy=selected_strategy,
            snapshot=snap,
            original_size=snap.size_bytes,
        ))
    return tasks
```

- [ ] **Step 4: Run encoding tests**

Run:

```powershell
py -3 -m pytest tests/test_encoding_controller.py tests/test_spec_compliance.py::test_start_request_uses_checked_file_keys_for_duplicate_relative_paths -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: Commit**

```powershell
git add leanreel/controllers/encoding_controller.py tests/test_encoding_controller.py
git commit -m "fix: require file identity for encoding overrides"
```

---

### Task 5: Add Static Guardrails Against Display Keys as Identity

**Files:**
- Test: `tests/test_spec_compliance.py`

- [ ] **Step 1: Add static guard test**

Add this test to `tests/test_spec_compliance.py`:

```python
def test_identity_sensitive_maps_do_not_use_display_only_keys():
    """Controllers/adapters must not use folder_name or relative_path as unique map keys."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    scan_source = (root / "leanreel" / "controllers" / "scan_controller.py").read_text(encoding="utf-8")
    assert "matched[s.relative_path]" not in scan_source
    assert "matched.get(s.relative_path)" not in scan_source

    tree_source = (root / "leanreel" / "gui" / "adapters" / "tree_adapter.py").read_text(encoding="utf-8")
    assert "self._folder_items.get(fname)" not in tree_source
    assert "self._folder_items[fname]" not in tree_source

    encoding_source = (root / "leanreel" / "controllers" / "encoding_controller.py").read_text(encoding="utf-8")
    assert "strategy_overrides.get(snap.relative_path" not in encoding_source
```

- [ ] **Step 2: Run guard test**

Run:

```powershell
py -3 -m pytest tests/test_spec_compliance.py::test_identity_sensitive_maps_do_not_use_display_only_keys -q
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Run full suite**

Run:

```powershell
py -3 -m pytest -q
```

Expected:

```text
407 passed
```

The exact pass count may be higher if additional tests were added during implementation.

- [ ] **Step 4: Check diff hygiene**

Run:

```powershell
git diff --check
```

Expected:

```text
no whitespace errors
```

Existing CRLF warnings are acceptable if there are no whitespace error lines.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_spec_compliance.py
git commit -m "test: guard multi-folder identity boundaries"
```

---

## Edge Cases and Failure Modes

- Two library folders both contain root-level `movie.mkv`.
- Two library folders both contain `Season 1/E01.mkv`.
- A tree folder node is right-clicked after duplicate directory names exist.
- A scan result arrives for a background library while another library is visible.
- A legacy caller passes a bare string to `apply_strategy_to_row`; it may still work locally, but must not become a cross-layer identity path.
- A filter is active when a tree row updates.
- A scan refresh rebuilds rows while the user is in tree view.

---

## Internal Review Roles

**Builder**
- Keep the change small: identity helpers, map keys, tests.
- Avoid rewriting UI adapters beyond the exact key changes.

**Reviewer**
- Reject any dict/set/cache keyed by `relative_path` or `folder_name` where uniqueness matters.
- Allow display-only uses in labels, sorting text, summaries, and tooltips.

**Tester**
- Require duplicate-name tests for every identity-sensitive map.
- Verify red before green for each task.

**Performance**
- Directory key changes are constant-time tuple key changes.
- Tree rebuild remains O(n) over visible rows.
- No additional full table rebuilds should be introduced in probe result paths.

---

## Self-Review

**Spec coverage**
- Multi-library file identity: Task 1, Task 2, Task 4.
- Multi-folder tree identity: Task 1, Task 3.
- UI behavior and refresh target: Task 3.
- Regression prevention: Task 5.

**Placeholder scan**
- No `TBD`, `TODO`, or unspecified implementation steps are present.
- Every code-changing task includes exact file paths, test code, implementation code, and commands.

**Type consistency**
- `FileKey` is `tuple[int, str]`.
- `DirectoryKey` is `tuple[int, str]`.
- `FileRow.key` returns `FileKey`.
- `FileRow.directory_key` returns `DirectoryKey`.
- Store and tree adapter consume `directory_key`.

---

## Final Verification

Run:

```powershell
py -3 -m pytest -q
git diff --check
git status --short --branch
```

Expected:

```text
all tests pass
no whitespace errors
working tree contains only intentional committed changes
```
