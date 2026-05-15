# LeanReel UI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the LeanReel desktop UI so the user can quickly understand which files are safe to process, why protected sources are skipped, which strategy will run, and what the queue is doing.

**Architecture:** Keep the existing PySide6 three-pane workbench: library navigation, file decision table, strategy and execution panel, with a bottom queue dock. Introduce explicit UI state helpers for file decisions, make filters real, separate protected-source display from unmatched errors, and align queue/library actions with their labels. Preserve dense table-first interaction rather than moving toward card-heavy layouts.

**Tech Stack:** Python 3, PySide6, pytest, pytest-qt, LeanReel dataclass models, existing `leanreel.gui` modules, existing `PRODUCT.md` and `DESIGN.md` product context.

---

## Assumptions, Limits, And Success Criteria

**Assumptions**

- LeanReel is a product UI, not a brand surface. The interface serves batch video library decisions.
- HEVC/H.265, HDR10, HDR10+, and Dolby Vision are protected sources by default and must not be selected by bulk processing UI.
- Users understand technical terms like CRF, CQ, NVENC, x265, HDR10, and Dolby Vision, but the UI must still explain decisions plainly.
- The current codebase favors direct PySide widgets and unit tests with pytest-qt. The refactor should fit that style.

**Limits**

- This plan does not introduce playback, thumbnails, media posters, or a new visual identity.
- This plan does not add a hidden advanced path to force-process protected HEVC/HDR/Dolby Vision sources.
- This plan does not redesign persistence or the database schema.
- Visual verification is limited to PySide screenshots and widget tests, because the app is not a browser UI.

**Measurable Success Criteria**

- Protected rows display `跳过：HEVC/H.265 片源`, `跳过：HDR10 片源`, `跳过：HDR10+ 片源`, or `跳过：Dolby Vision 片源` in the processing-state column.
- Protected rows display `不处理` in the expected-result column.
- `全选` selects only processable rows, and the selection label counts processable files, not every scanned file.
- The filter control actually filters rows by `全部`, `可处理`, `已保护跳过`, `探测失败`, and `已选择`.
- Tree view columns line up with their headers.
- Strategy names such as `x265 HEVC CRF 18 高质量转码` remain readable in the table and strategy panel.
- `清空已完成` only removes terminal task rows and keeps running or pending rows visible.
- Failed queue rows show a readable failure reason.
- Destructive library actions require confirmation and explain that disk files are not deleted if that is the actual behavior.
- Related tests pass with `py -m pytest tests/test_main_window.py tests/test_queue_panel.py tests/test_preset_card_panel.py tests/test_library_panel.py -q`.
- Full suite passes with `py -m pytest -q`.

## Design Principles To Preserve

- File table is the center of gravity.
- Amber is reserved for primary action, focus, selected strategy, and progress.
- Protected-source skip states use information blue, not warning yellow or danger red.
- Status never relies on color alone.
- Strategy names use technical names first, short explanation second.
- The UI remains dense and scannable. Do not add marketing cards, gradients, glass effects, hero sections, or decorative motion.

## File Structure

**Modify**

- `leanreel/gui/file_list.py`: file decision display helper, protected-source display, real filters, tree headers, selection count, lazy strategy editing foundation.
- `leanreel/gui/strategy_panel.py`: readable two-line strategy rows, dynamic custom encoder controls, generated custom strategy names, correct GPU/copy metadata.
- `leanreel/gui/queue_panel.py`: terminal-row clearing, failure and skip reason display, safer cancel semantics.
- `leanreel/gui/library_panel.py`: confirmation dialogs, search empty state, clearer destructive copy.
- `leanreel/gui/main_window.py`: wider default strategy pane and corrected about text.
- `leanreel/gui/theme.py`: named primary button selector and row/status styles if needed.
- `README.md`: update screenshots or UI behavior copy if existing usage docs mention old filter or queue behavior.
- `docs/ui-optimization-principles.md`: record the final UI rules after implementation.

**Create**

- `tests/test_library_panel.py`: tests for library deletion confirmation, folder removal confirmation, and empty search.

**Modify Tests**

- `tests/test_main_window.py`: file list display, filtering, tree alignment, protected row text, selection count.
- `tests/test_queue_panel.py`: terminal clearing and failure reason display.
- `tests/test_preset_card_panel.py`: readable strategy row text, technical names, selected description behavior.

## Task 1: File Decision Display Model

**Files:**

- Modify: `leanreel/gui/file_list.py`
- Modify: `tests/test_main_window.py`

- [ ] **Step 1: Write failing tests for protected-source display**

Add these tests to `tests/test_main_window.py` near the existing `FileListPanel` tests.

```python
def test_file_list_protected_sources_show_skip_reason_and_not_processing():
    from leanreel.data.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(
            relative_path="hevc.mkv",
            file_name="hevc.mkv",
            size_bytes=1024,
            video_codec="hevc",
            hdr_type=HDRType.SDR,
        ),
        FileSnapshot(
            relative_path="hdr10.mkv",
            file_name="hdr10.mkv",
            size_bytes=2048,
            video_codec="h264",
            hdr_type=HDRType.HDR10,
        ),
    ]

    panel.populate(
        snapshots,
        {
            "hevc.mkv": MatchResult(strategy=None),
            "hdr10.mkv": MatchResult(strategy=None),
        },
    )

    assert panel.table.item(0, 5).text() == "跳过：HEVC/H.265 片源"
    assert panel.table.item(0, 6).text() == "不处理"
    assert panel.table.item(1, 5).text() == "跳过：HDR10 片源"
    assert panel.table.item(1, 6).text() == "不处理"
    assert panel.table.item(0, 0).toolTip() == "跳过：HEVC/H.265 片源"
    assert panel.table.item(1, 0).toolTip() == "跳过：HDR10 片源"
    panel.close()


def test_file_list_unmatched_non_protected_source_still_shows_unmatched():
    from leanreel.data.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(
        relative_path="unknown.mkv",
        file_name="unknown.mkv",
        size_bytes=4096,
        video_codec="h264",
        hdr_type=HDRType.SDR,
    )

    panel.populate([snap], {"unknown.mkv": None})

    assert panel.table.item(0, 5).text() == "未匹配"
    assert panel.table.item(0, 6).text() == "—"
    panel.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
py -m pytest tests/test_main_window.py::test_file_list_protected_sources_show_skip_reason_and_not_processing tests/test_main_window.py::test_file_list_unmatched_non_protected_source_still_shows_unmatched -q
```

Expected: first test fails because protected rows currently show `未匹配` or an ordinary strategy value instead of a skip reason.

- [ ] **Step 3: Add a display dataclass and protected display branch**

In `leanreel/gui/file_list.py`, update the matcher import.

```python
from leanreel.core.matcher import get_skip_reason, is_protected_source
```

Add this dataclass below `MatchResult`.

```python
@dataclass(frozen=True)
class FileDecisionDisplay:
    status_key: str
    strategy_text: str
    result_text: str
    result_sort: int | float
    processable: bool
    tooltip: str
```

Add this method inside `FileListPanel` before `_resolve_match_display`.

```python
    def _decision_display(self, snap: Any, match: MatchResult | None) -> FileDecisionDisplay:
        skip_reason = get_skip_reason(snap)
        if skip_reason:
            return FileDecisionDisplay(
                status_key="protected",
                strategy_text=skip_reason,
                result_text="不处理",
                result_sort=-2,
                processable=False,
                tooltip=skip_reason,
            )

        if getattr(snap, "probe_ok", None) is False and not getattr(snap, "video_codec", ""):
            probe_error = getattr(snap, "probe_error", "") or "探测失败"
            return FileDecisionDisplay(
                status_key="probe_failed",
                strategy_text="探测失败",
                result_text="无法估算",
                result_sort=-3,
                processable=False,
                tooltip=probe_error,
            )

        strategy_name, savings_text, savings_sort = self._resolve_match_display(snap, match)
        return FileDecisionDisplay(
            status_key="processable" if strategy_name != "未匹配" else "unmatched",
            strategy_text=strategy_name,
            result_text=savings_text,
            result_sort=savings_sort,
            processable=strategy_name != "未匹配",
            tooltip=strategy_name,
        )
```

In `populate()`, replace the direct `_resolve_match_display()` usage with `decision = self._decision_display(...)`. Use `decision.strategy_text`, `decision.result_text`, and `decision.result_sort` for columns 5 and 6.

```python
            decision = self._decision_display(
                snap, matched_strategies.get(snap.relative_path)
            )
            self.table.setItem(
                row, 6,
                SortableTableWidgetItem(decision.result_text, decision.result_sort),
            )
            if strategies and decision.processable:
                self.table.setCellWidget(
                    row, 5,
                    self._create_strategy_combo(snap.relative_path, decision.strategy_text),
                )
            else:
                strategy_item = QTableWidgetItem(decision.strategy_text)
                strategy_item.setToolTip(decision.tooltip)
                if decision.status_key == "protected":
                    strategy_item.setForeground(_COLOR_HDR_DV)
                self.table.setItem(row, 5, strategy_item)
```

Update the checkbox setup in `populate()` so the tooltip is the exact skip reason.

```python
            check_item = QTableWidgetItem()
            skip_reason = get_skip_reason(snap)
            if skip_reason:
                check_item.setFlags(Qt.ItemIsUserCheckable)
                check_item.setToolTip(skip_reason)
            else:
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, check_item)
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
py -m pytest tests/test_main_window.py::test_file_list_protected_sources_show_skip_reason_and_not_processing tests/test_main_window.py::test_file_list_unmatched_non_protected_source_still_shows_unmatched -q
```

Expected: both tests pass.

- [ ] **Step 5: Run file list tests**

Run:

```bash
py -m pytest tests/test_main_window.py -q
```

Expected: all tests in `tests/test_main_window.py` pass.

- [ ] **Step 6: Commit**

```bash
git add leanreel/gui/file_list.py tests/test_main_window.py
git commit -m "fix: show protected source decisions in file list"
```

## Task 2: Real File Filters And Accurate Selection Counts

**Files:**

- Modify: `leanreel/gui/file_list.py`
- Modify: `tests/test_main_window.py`

- [ ] **Step 1: Write failing tests for filters**

Add these tests to `tests/test_main_window.py`.

```python
def test_file_list_filter_shows_only_protected_rows():
    from leanreel.data.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(relative_path="sdr.mkv", file_name="sdr.mkv", size_bytes=1024, video_codec="h264"),
        FileSnapshot(relative_path="hevc.mkv", file_name="hevc.mkv", size_bytes=1024, video_codec="hevc"),
        FileSnapshot(relative_path="hdr.mkv", file_name="hdr.mkv", size_bytes=1024, video_codec="h264", hdr_type=HDRType.HDR10),
    ]
    matches = {
        "sdr.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"}),
        "hevc.mkv": MatchResult(strategy=None),
        "hdr.mkv": MatchResult(strategy=None),
    }

    panel.populate(snapshots, matches)
    panel.filter_combo.setCurrentText("已保护跳过")

    assert panel.table.isRowHidden(0)
    assert not panel.table.isRowHidden(1)
    assert not panel.table.isRowHidden(2)
    panel.close()


def test_file_list_selection_count_uses_processable_total():
    from leanreel.data.models import FileSnapshot, HDRType
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snapshots = [
        FileSnapshot(relative_path="sdr-a.mkv", file_name="sdr-a.mkv", size_bytes=1024, video_codec="h264"),
        FileSnapshot(relative_path="sdr-b.mkv", file_name="sdr-b.mkv", size_bytes=1024, video_codec="h264"),
        FileSnapshot(relative_path="hdr.mkv", file_name="hdr.mkv", size_bytes=1024, video_codec="h264", hdr_type=HDRType.HDR10),
    ]
    matches = {
        "sdr-a.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"}),
        "sdr-b.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"}),
        "hdr.mkv": MatchResult(strategy=None),
    }

    panel.populate(snapshots, matches)
    panel.select_all()

    assert panel.selection_label.text() == "已选中 2/2 个可处理文件"
    panel.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
py -m pytest tests/test_main_window.py::test_file_list_filter_shows_only_protected_rows tests/test_main_window.py::test_file_list_selection_count_uses_processable_total -q
```

Expected: filter test fails because the filter does not hide rows; selection label test fails because total includes protected rows.

- [ ] **Step 3: Implement filter data and connections**

In `FileListPanel.__init__`, add:

```python
        self._row_status_keys: dict[int, str] = {}
        self._row_processable: dict[int, bool] = {}
```

Replace filter combo setup with data-backed items.

```python
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部", "all")
        self.filter_combo.addItem("可处理", "processable")
        self.filter_combo.addItem("已保护跳过", "protected")
        self.filter_combo.addItem("探测失败", "probe_failed")
        self.filter_combo.addItem("已选择", "checked")
        self.filter_combo.currentIndexChanged.connect(lambda _i: self._apply_filter())
```

In `populate()`, reset maps before row creation.

```python
        self._row_status_keys = {}
        self._row_processable = {}
```

After building `decision` for each row, store:

```python
            self._row_status_keys[row] = decision.status_key
            self._row_processable[row] = decision.processable
```

After `_populate_tree(...)`, apply the current filter.

```python
        self._apply_filter()
```

Add the filter method to `FileListPanel`.

```python
    def _apply_filter(self):
        filter_key = self.filter_combo.currentData() if hasattr(self, "filter_combo") else "all"
        for row in range(self.table.rowCount()):
            status_key = self._row_status_keys.get(row, "unmatched")
            check_item = self.table.item(row, 0)
            checked = check_item is not None and check_item.checkState() == Qt.Checked
            hide = False
            if filter_key == "processable":
                hide = not self._row_processable.get(row, False)
            elif filter_key == "protected":
                hide = status_key != "protected"
            elif filter_key == "probe_failed":
                hide = status_key != "probe_failed"
            elif filter_key == "checked":
                hide = not checked
            self.table.setRowHidden(row, hide)
        self._update_selection_count()
```

In `_on_item_changed`, apply the checked filter after updates.

```python
    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            self._apply_filter()
```

Replace `_update_selection_count()` with:

```python
    def _update_selection_count(self):
        checked = 0
        processable_total = 0
        for row in range(self.table.rowCount()):
            if self._row_processable.get(row, False):
                processable_total += 1
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked and item.flags() & Qt.ItemIsEnabled:
                checked += 1
        self.selection_label.setText(
            f"已选中 {checked}/{processable_total} 个可处理文件"
        )
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
py -m pytest tests/test_main_window.py::test_file_list_filter_shows_only_protected_rows tests/test_main_window.py::test_file_list_selection_count_uses_processable_total -q
```

Expected: both tests pass.

- [ ] **Step 5: Run file list tests**

Run:

```bash
py -m pytest tests/test_main_window.py -q
```

Expected: all tests in `tests/test_main_window.py` pass.

- [ ] **Step 6: Commit**

```bash
git add leanreel/gui/file_list.py tests/test_main_window.py
git commit -m "feat: add real file decision filters"
```

## Task 3: Tree View Column Alignment

**Files:**

- Modify: `leanreel/gui/file_list.py`
- Modify: `tests/test_main_window.py`

- [ ] **Step 1: Write failing test for tree columns**

Add this test to `tests/test_main_window.py`.

```python
def test_file_list_tree_view_columns_are_aligned_with_headers():
    from leanreel.data.models import FileSnapshot
    from leanreel.gui.file_list import FileListPanel, MatchResult

    app = get_app()
    panel = FileListPanel()
    snap = FileSnapshot(
        relative_path="Season 01/Episode 01.mkv",
        file_name="Episode 01.mkv",
        size_bytes=10 * 1024**3,
        video_codec="h264",
        video_width=1920,
        video_height=1080,
    )

    panel.populate(
        [snap],
        {"Season 01/Episode 01.mkv": MatchResult(strategy="x265 HEVC CRF 20 标准转码", estimate={"percentage": "35-50%"})},
    )
    panel.set_view_mode("tree")

    folder = panel.tree.topLevelItem(0)
    child = folder.child(0)
    assert panel.tree.headerItem().text(0) == "文件名"
    assert child.text(0) == "Episode 01.mkv"
    assert "GB" in child.text(1)
    assert "h264" in child.text(2)
    assert child.text(3) == "SDR"
    assert child.text(4) == "x265 HEVC CRF 20 标准转码"
    assert "GB" in child.text(5)
    panel.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
py -m pytest tests/test_main_window.py::test_file_list_tree_view_columns_are_aligned_with_headers -q
```

Expected: fails because tree view currently uses the table header with a leading checkbox column.

- [ ] **Step 3: Define separate tree headers**

In `leanreel/gui/file_list.py`, add this constant under `_HEADERS`.

```python
_TREE_HEADERS = ["文件名", "体积", "编码信息", "HDR", "处理状态", "预计结果"]
```

Replace the tree setup.

```python
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(_TREE_HEADERS))
        self.tree.setHeaderLabels(_TREE_HEADERS)
        self.tree.setSortingEnabled(True)
        self.tree.hide()
```

Replace the child creation in `_populate_tree()` with decision display values.

```python
            decision = self._decision_display(
                snap, matched_strategies.get(snap.relative_path)
            )
            child = QTreeWidgetItem([
                snap.file_name,
                _format_bytes(snap.size_bytes),
                self._format_codec(snap),
                self._format_hdr(snap.hdr_type),
                decision.strategy_text,
                decision.result_text,
            ])
            child.setToolTip(4, decision.tooltip)
            child.setData(0, Qt.UserRole, snap.relative_path)
```

- [ ] **Step 4: Run targeted test**

Run:

```bash
py -m pytest tests/test_main_window.py::test_file_list_tree_view_columns_are_aligned_with_headers -q
```

Expected: test passes.

- [ ] **Step 5: Run file list tests**

Run:

```bash
py -m pytest tests/test_main_window.py -q
```

Expected: all tests in `tests/test_main_window.py` pass.

- [ ] **Step 6: Commit**

```bash
git add leanreel/gui/file_list.py tests/test_main_window.py
git commit -m "fix: align file tree view columns"
```

## Task 4: Strategy Panel Readability And Main Layout Width

**Files:**

- Modify: `leanreel/gui/strategy_panel.py`
- Modify: `leanreel/gui/main_window.py`
- Modify: `tests/test_preset_card_panel.py`
- Modify: `tests/test_main_window.py`

- [ ] **Step 1: Write failing tests for technical strategy row readability**

Add this test to `tests/test_preset_card_panel.py`.

```python
def test_strategy_rows_use_two_line_technical_layout(qtbot):
    panel = PresetCardPanel()
    qtbot.addWidget(panel)
    strategies = [
        Strategy.from_dict({
            "name": "x265 HEVC CRF 18 高质量转码",
            "description": "CPU x265 慢速高质量，适合值得保留细节的 SDR H.264 片源。",
            "is_preset": True,
            "video": {"encoder": "libx265", "crf": 18, "preset": "slow"},
            "estimated_savings": "20-35%",
        }),
    ]

    panel.set_strategies(strategies)

    button = panel.card_group.buttons()[0]
    assert "x265 HEVC CRF 18 高质量转码" in button.text()
    assert "\n" in button.text()
    assert "CPU" in button.text()
    assert "20-35%" in button.text()
    assert button.minimumHeight() >= 42
```

Add this test to `tests/test_main_window.py`.

```python
def test_main_window_default_splitter_gives_strategy_panel_room():
    from leanreel.gui.main_window import MainWindow

    app = get_app()
    window = MainWindow()
    sizes = window.splitter.sizes()

    assert len(sizes) == 3
    assert sizes[2] >= 320
    window.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
py -m pytest tests/test_preset_card_panel.py::test_strategy_rows_use_two_line_technical_layout tests/test_main_window.py::test_main_window_default_splitter_gives_strategy_panel_room -q
```

Expected: strategy row test fails because rows are one line; splitter width test fails because the strategy pane is 240.

- [ ] **Step 3: Update strategy row text and sizing**

In `PresetCardPanel._make_row_button()`, replace text construction with:

```python
        text = f"{prefix}  {s.name}\n   [{tag}]  {savings}"
```

After creating the button, set height and tooltip.

```python
        btn.setMinimumHeight(44)
        btn.setToolTip(f"{s.name}\n{s.description}".strip())
```

In `_update_indicators()`, use the same text construction.

```python
            text = f"{prefix}  {s.name}\n   [{tag}]  {savings}"
```

Update `_ROW_STYLE` so line-height-like spacing remains readable in a button.

```python
_ROW_STYLE = """
QPushButton {
    background-color: #1c1a16;
    border: 1px solid #2e2b25;
    border-radius: 4px;
    padding: 5px 8px;
    text-align: left;
    min-height: 42px;
    font-size: 12px;
    color: #c8c0b8;
}
QPushButton:hover {
    border-color: #5c4a2e;
    background-color: #24221d;
}
QPushButton:checked {
    border: 1px solid #d4a853;
    background-color: #3d2e14;
    color: #f0e6d0;
}
QPushButton:checked:hover {
    border-color: #e0b85c;
    background-color: #45341a;
}
"""
```

- [ ] **Step 4: Update main splitter sizes**

In `leanreel/gui/main_window.py`, replace:

```python
        self.splitter.setSizes([220, 700, 240])
```

with:

```python
        self.splitter.setSizes([240, 820, 340])
```

If later visual QA shows 900px width is cramped, keep the minimum window at 900px but allow the splitter to compress the center panel first by assigning minimum widths to the side panels in the implementation.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
py -m pytest tests/test_preset_card_panel.py::test_strategy_rows_use_two_line_technical_layout tests/test_main_window.py::test_main_window_default_splitter_gives_strategy_panel_room -q
```

Expected: both tests pass.

- [ ] **Step 6: Run related UI tests**

Run:

```bash
py -m pytest tests/test_preset_card_panel.py tests/test_main_window.py -q
```

Expected: all tests pass. If older tests assert one-line strategy text, update those assertions to check for strategy name, tag, and savings separately.

- [ ] **Step 7: Commit**

```bash
git add leanreel/gui/strategy_panel.py leanreel/gui/main_window.py tests/test_preset_card_panel.py tests/test_main_window.py
git commit -m "feat: improve strategy panel readability"
```

## Task 5: Dynamic Custom Strategy Controls

**Files:**

- Modify: `leanreel/gui/strategy_panel.py`
- Modify: `tests/test_main_window.py`

- [ ] **Step 1: Write failing tests for custom strategy generation**

Add these tests near `test_strategy_panel_custom_controls_emit_recomputed_strategy` in `tests/test_main_window.py`.

```python
def test_strategy_panel_custom_x265_uses_crf_name_and_cpu_metadata():
    from leanreel.gui.strategy_panel import StrategyPanel

    app = get_app()
    panel = StrategyPanel()
    panel.show_custom_strategy()
    panel.custom_encoder_combo.setCurrentText("libx265")
    panel.custom_crf_spin.setValue(18)

    strategy = panel.current_strategy

    assert strategy.name == "x265 HEVC CRF 18 自定义转码"
    assert strategy.video.encoder == "libx265"
    assert strategy.video.gpu is False
    assert strategy.video.crf == 18
    assert strategy.quality_impact == "CPU x265 编码"
    panel.close()


def test_strategy_panel_custom_copy_hides_quality_controls_and_uses_copy_metadata():
    from leanreel.gui.strategy_panel import StrategyPanel

    app = get_app()
    panel = StrategyPanel()
    panel.show_custom_strategy()
    panel.custom_encoder_combo.setCurrentText("copy")

    strategy = panel.current_strategy

    assert strategy.name == "Copy Streams 自定义流复制"
    assert strategy.video.encoder == "copy"
    assert strategy.video.gpu is False
    assert strategy.quality_impact == "不重编码视频"
    assert not panel.custom_cq_spin.isVisibleTo(panel)
    assert not panel.custom_crf_spin.isVisibleTo(panel)
    panel.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
py -m pytest tests/test_main_window.py::test_strategy_panel_custom_x265_uses_crf_name_and_cpu_metadata tests/test_main_window.py::test_strategy_panel_custom_copy_hides_quality_controls_and_uses_copy_metadata -q
```

Expected: tests fail because `libx265` is not available in the custom encoder combo and `custom_crf_spin` does not exist.

- [ ] **Step 3: Add CPU encoder and CRF controls**

In `leanreel/gui/strategy_panel.py`, replace encoder constants.

```python
_CPU_ENCODERS = ["libx265"]
_GPU_ENCODERS = ["hevc_nvenc", "h264_nvenc"]
_ALL_ENCODERS = [*_CPU_ENCODERS, *_GPU_ENCODERS, "copy"]
```

In `setup_ui()`, add CRF controls after encoder combo and before CQ controls.

```python
        self.custom_crf_spin = QSpinBox()
        self.custom_crf_spin.setRange(0, 51)
        self.custom_crf_spin.setValue(20)
        self.crf_label = QLabel("CRF")
        self.crf_label.setToolTip("x265 质量参数，数字越小画质越高，体积越大")
```

Add the CRF row before the CQ row.

```python
        custom_layout.addRow(self.crf_label, self.custom_crf_spin)
```

Add `self.custom_crf_spin` to the signal connection tuple.

```python
            self.custom_crf_spin,
```

- [ ] **Step 4: Implement dynamic visibility**

Replace `_on_encoder_changed()` with:

```python
    def _on_encoder_changed(self):
        encoder = self.custom_encoder_combo.currentText()
        is_cpu = encoder in _CPU_ENCODERS
        is_gpu = encoder in _GPU_ENCODERS

        self.crf_label.setVisible(is_cpu)
        self.custom_crf_spin.setVisible(is_cpu)
        self.cq_label.setVisible(is_gpu)
        self.custom_cq_spin.setVisible(is_gpu)
        self.nvpreset_label.setVisible(is_gpu)
        self.custom_nvpreset_combo.setVisible(is_gpu)

        self._emit_custom_strategy()
```

Call it at the end of `setup_ui()` after all controls have been created.

```python
        self._on_encoder_changed()
```

- [ ] **Step 5: Replace `custom_strategy` generation**

Replace the `custom_strategy` property with:

```python
    @property
    def custom_strategy(self):
        encoder = self.custom_encoder_combo.currentText()
        is_gpu = encoder in _GPU_ENCODERS
        is_cpu = encoder in _CPU_ENCODERS
        is_copy = encoder == "copy"

        if is_copy:
            name = "Copy Streams 自定义流复制"
            savings = "5-15%"
            quality_impact = "不重编码视频"
            crf_val = 0
            cq_val = 0
        elif is_cpu:
            crf_val = self.custom_crf_spin.value()
            cq_val = 0
            name = f"x265 HEVC CRF {crf_val} 自定义转码"
            quality_impact = "CPU x265 编码"
            if crf_val <= 18:
                savings = "20-35%"
            elif crf_val <= 20:
                savings = "35-50%"
            elif crf_val <= 22:
                savings = "50-70%"
            else:
                savings = "60-75%"
        else:
            crf_val = 0
            cq_val = self.custom_cq_spin.value()
            name = f"NVENC HEVC CQ {cq_val} 自定义转码"
            quality_impact = "GPU 硬件编码"
            if cq_val <= 20:
                savings = "15-30%"
            elif cq_val <= 24:
                savings = "25-45%"
            elif cq_val <= 28:
                savings = "35-55%"
            else:
                savings = "45-65%"

        nv_preset = self.custom_nvpreset_combo.currentText().lower()

        return Strategy.from_dict({
            "name": name,
            "description": "手动配置的压缩策略",
            "is_preset": False,
            "video": {
                "encoder": encoder,
                "crf": crf_val,
                "preset": "slow" if is_cpu else "",
                "pix_fmt": "yuv420p10le",
                "gpu": is_gpu,
                "nv_preset": nv_preset if is_gpu else "",
                "rc": "vbr" if is_gpu else "",
                "cq": cq_val,
            },
            "audio": {"mode": self.custom_audio_combo.currentText()},
            "subtitle": {"mode": self.custom_subtitle_combo.currentText()},
            "filters": {"skip_x265": False},
            "estimated_savings": savings,
            "quality_impact": quality_impact,
        })
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
py -m pytest tests/test_main_window.py::test_strategy_panel_custom_x265_uses_crf_name_and_cpu_metadata tests/test_main_window.py::test_strategy_panel_custom_copy_hides_quality_controls_and_uses_copy_metadata tests/test_main_window.py::test_strategy_panel_custom_controls_emit_recomputed_strategy -q
```

Expected: all three tests pass. If the existing recomputed-strategy test expects `name == "自定义"`, update it to expect `NVENC HEVC CQ 25 自定义转码` after setting CQ to 25.

- [ ] **Step 7: Run strategy tests**

Run:

```bash
py -m pytest tests/test_main_window.py tests/test_preset_card_panel.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add leanreel/gui/strategy_panel.py tests/test_main_window.py
git commit -m "feat: add encoder-aware custom strategies"
```

## Task 6: Queue Panel Semantics And Error Readability

**Files:**

- Modify: `leanreel/gui/queue_panel.py`
- Modify: `tests/test_queue_panel.py`

- [ ] **Step 1: Replace old clear-all expectation with terminal-clear tests**

In `tests/test_queue_panel.py`, replace `test_clear_all_removes_all_task_rows_including_running` with:

```python
    def test_clear_finished_keeps_running_and_pending_rows(self, qtbot):
        """清空已完成只移除终态任务，保留 RUNNING 和 PENDING。"""
        panel = QueuePanel()
        qtbot.addWidget(panel)

        tasks = [
            EncodeTask(
                file_name="running_task.mkv",
                input_path="/movies/running_task.mkv",
                output_path="/movies/running_task_SS.mkv",
                status=TaskStatus.RUNNING,
                original_size=5_000_000_000,
                progress=45.0,
            ),
            EncodeTask(
                file_name="completed_task.mkv",
                input_path="/movies/completed_task.mkv",
                output_path="/movies/completed_task_SS.mkv",
                status=TaskStatus.COMPLETED,
                original_size=8_000_000_000,
                compressed_size=3_000_000_000,
            ),
            EncodeTask(
                file_name="pending_task.mkv",
                input_path="/movies/pending_task.mkv",
                output_path="/movies/pending_task_SS.mkv",
                status=TaskStatus.PENDING,
                original_size=2_000_000_000,
            ),
            EncodeTask(
                file_name="failed_task.mkv",
                input_path="/movies/failed_task.mkv",
                output_path="/movies/failed_task_SS.mkv",
                status=TaskStatus.FAILED,
                original_size=6_000_000_000,
                compressed_size=0,
                error_message="编码错误",
            ),
        ]

        for task in tasks:
            panel.add_task_row(task)

        panel.clear_finished()
        qtbot.wait(50)

        visible_names = []
        for index in range(panel.task_layout.count() - 1):
            row = panel.task_layout.itemAt(index).widget()
            visible_names.append(row.findChild(QLabel, "queue_name").text())

        assert visible_names == ["running_task.mkv", "pending_task.mkv"]
```

Add this test for failure detail.

```python
def test_queue_panel_failed_task_shows_error_message(qtbot):
    from PySide6.QtWidgets import QLabel
    from leanreel.encoding.models import EncodeTask
    from leanreel.gui.queue_panel import QueuePanel

    panel = QueuePanel()
    qtbot.addWidget(panel)
    task = EncodeTask(
        file_name="failed.mkv",
        input_path="/movies/failed.mkv",
        output_path="/movies/failed_SS.mkv",
        status=TaskStatus.FAILED,
        original_size=1_000_000_000,
        compressed_size=0,
        error_message="编码器崩溃",
    )

    panel.add_task_row(task)

    row = panel.task_layout.itemAt(0).widget()
    info_label = row.findChild(QLabel, "queue_info")
    assert info_label.text() == "失败：编码器崩溃"
    assert info_label.toolTip() == "编码器崩溃"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
py -m pytest tests/test_queue_panel.py::TestQueuePanelClear::test_clear_finished_keeps_running_and_pending_rows tests/test_queue_panel.py::test_queue_panel_failed_task_shows_error_message -q
```

Expected: tests fail because `clear_finished()` does not exist and failed rows show size text.

- [ ] **Step 3: Store row status and error data**

In `QueuePanel.add_task_row()`, after `row = QWidget()`, add:

```python
        row.setProperty("task_status", task.status.value)
```

When calculating `info`, handle failed before completed.

```python
        if task.status == TaskStatus.FAILED:
            error_message = getattr(task, "error_message", "") or "未知错误"
            info = f"失败：{error_message}"
        elif task.status == TaskStatus.COMPLETED:
            orig = _format_bytes(task.original_size)
            comp = _format_bytes(task.compressed_size) if task.compressed_size else "—"
            ratio = ""
            if task.compressed_size and task.original_size:
                pct = (1 - task.compressed_size / task.original_size) * 100
                ratio = f" ({pct:.0f}%)"
            info = f"{orig} → {comp}{ratio}"
        elif task.status == TaskStatus.SKIPPED:
            info = getattr(task, "error_message", "") or "已跳过"
```

After `info_label = QLabel(info)`, set tooltip for failed rows.

```python
        if task.status == TaskStatus.FAILED:
            info_label.setToolTip(getattr(task, "error_message", "") or "未知错误")
```

In `update_task_row()`, update row property when status changes.

```python
                row.setProperty("task_status", task.status.value)
```

Apply the same failed/completed/skipped branch in `update_task_row()` when setting `info_label`.

- [ ] **Step 4: Implement terminal clearing**

Add a constant near `_STATUS_ICONS`.

```python
_TERMINAL_STATUSES = {
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.SKIPPED.value,
    TaskStatus.CANCELLED.value,
}
```

Replace the clear button connection.

```python
        self.clear_btn.clicked.connect(self.clear_finished)
```

Add this method.

```python
    def clear_finished(self):
        """清空已完成、失败、跳过和已取消任务，保留运行中和等待中任务。"""
        for i in reversed(range(self.task_layout.count() - 1)):
            item = self.task_layout.itemAt(i)
            widget = item.widget() if item else None
            if widget and widget.property("task_status") in _TERMINAL_STATUSES:
                widget.deleteLater()
```

Keep `clear_all()` for full internal cleanup by `clear_tasks()`, and leave its docstring explicit.

- [ ] **Step 5: Run queue tests**

Run:

```bash
py -m pytest tests/test_queue_panel.py -q
```

Expected: all queue tests pass. Update tests that say the clear button removes all rows so they assert terminal-only behavior.

- [ ] **Step 6: Commit**

```bash
git add leanreel/gui/queue_panel.py tests/test_queue_panel.py
git commit -m "fix: make queue actions match their labels"
```

## Task 7: Library Panel Safety And Empty Search

**Files:**

- Modify: `leanreel/gui/library_panel.py`
- Create: `tests/test_library_panel.py`

- [ ] **Step 1: Create tests for confirmation and empty search**

Create `tests/test_library_panel.py`.

```python
from PySide6.QtWidgets import QMessageBox

from leanreel.data.models import Library, LibraryFolder
from leanreel.gui.library_panel import LibraryPanel


def test_library_delete_requires_confirmation(qtbot, monkeypatch):
    panel = LibraryPanel()
    qtbot.addWidget(panel)
    emitted = []
    panel.library_deleted.connect(emitted.append)
    panel.populate([Library(id=7, name="电影库")], {7: []})

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    panel._delete_library(7)
    assert emitted == []

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    panel._delete_library(7)
    assert emitted == [7]


def test_folder_remove_requires_confirmation(qtbot, monkeypatch):
    panel = LibraryPanel()
    qtbot.addWidget(panel)
    emitted = []
    panel.folder_removed.connect(emitted.append)
    panel.populate(
        [Library(id=3, name="剧集")],
        {3: [LibraryFolder(id=11, library_id=3, path="Z:/Series")]},
    )

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    panel._remove_folder(11)
    assert emitted == []

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    panel._remove_folder(11)
    assert emitted == [11]


def test_library_search_empty_state_is_visible(qtbot):
    panel = LibraryPanel()
    qtbot.addWidget(panel)
    panel.populate([Library(id=1, name="电影库")], {1: []})

    panel.search_edit.setText("no-match")

    assert panel.empty_item is not None
    assert panel.tree.topLevelItem(0).text(0) == "没有匹配的库或文件夹"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
py -m pytest tests/test_library_panel.py -q
```

Expected: confirmation tests fail because actions emit immediately; empty-state test fails because `empty_item` does not exist.

- [ ] **Step 3: Add empty search state**

In `LibraryPanel.__init__`, add:

```python
        self.empty_item = None
```

At the end of `_rebuild_tree()`, after all libraries have been processed, add:

```python
        if self.tree.topLevelItemCount() == 0:
            self.empty_item = QTreeWidgetItem(["没有匹配的库或文件夹"])
            self.empty_item.setFlags(Qt.NoItemFlags)
            self.empty_item.setForeground(0, Qt.gray)
            self.tree.addTopLevelItem(self.empty_item)
        else:
            self.empty_item = None
```

- [ ] **Step 4: Add confirmation dialogs**

Replace `_delete_library()` with:

```python
    def _delete_library(self, lib_id):
        result = QMessageBox.question(
            self,
            "删除库",
            "从 LeanReel 删除这个库？磁盘上的视频文件不会被删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.library_deleted.emit(lib_id)
```

Replace `_remove_folder()` with:

```python
    def _remove_folder(self, folder_id):
        result = QMessageBox.question(
            self,
            "移除文件夹",
            "从当前片库移除这个文件夹？磁盘上的视频文件不会被删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.folder_removed.emit(folder_id)
```

Update context menu action labels for clarity.

```python
            menu.addAction("从 LeanReel 删除库", lambda: self._delete_library(obj_id))
```

```python
            menu.addAction("从片库移除文件夹", lambda: self._remove_folder(obj_id))
```

- [ ] **Step 5: Run library tests**

Run:

```bash
py -m pytest tests/test_library_panel.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Run broader UI tests**

Run:

```bash
py -m pytest tests/test_library_panel.py tests/test_main_window.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add leanreel/gui/library_panel.py tests/test_library_panel.py
git commit -m "fix: confirm destructive library actions"
```

## Task 8: Copy, Theme Consistency, And About Text

**Files:**

- Modify: `leanreel/gui/main_window.py`
- Modify: `leanreel/gui/theme.py`
- Modify: `leanreel/gui/strategy_panel.py`
- Modify: `tests/test_main_window.py`

- [ ] **Step 1: Write failing tests for copy and primary action styling**

Add these tests to `tests/test_main_window.py`.

```python
def test_about_text_avoids_absolute_lossless_claim(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from leanreel.gui.main_window import MainWindow

    app = get_app()
    captured = {}
    monkeypatch.setattr(
        QMessageBox,
        "about",
        lambda parent, title, text: captured.update({"title": title, "text": text}),
    )
    window = MainWindow()

    window._show_about()

    assert "完整无损" not in captured["text"]
    assert "默认保护 HEVC/HDR/Dolby Vision 片源" in captured["text"]
    window.close()


def test_start_button_uses_primary_action_object_name():
    from leanreel.gui.strategy_panel import StrategyPanel

    app = get_app()
    panel = StrategyPanel()

    assert panel.start_btn.objectName() == "primary_action"
    assert panel.start_btn.styleSheet() == ""
    panel.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
py -m pytest tests/test_main_window.py::test_about_text_avoids_absolute_lossless_claim tests/test_main_window.py::test_start_button_uses_primary_action_object_name -q
```

Expected: about text still includes `完整无损`; start button uses inline stylesheet.

- [ ] **Step 3: Move primary button style into theme**

In `leanreel/gui/theme.py`, replace the unused `QPushButton.accent` selector with object-name selectors.

```python
QPushButton#primary_action {{
    background-color: {C_ACCENT};
    color: {C_BASE};
    border: none;
    border-radius: 6px;
    font-weight: bold;
    font-size: 15px;
    padding: 12px 24px;
}}
QPushButton#primary_action:hover {{
    background-color: {C_ACCENT_HOVER};
}}
QPushButton#primary_action:pressed {{
    background-color: #b88730;
}}
QPushButton#primary_action:disabled {{
    background-color: {C_BORDER};
    color: {C_TEXT_MUTED};
}}
```

In `StrategyPanel.setup_ui()`, replace the inline stylesheet block for `self.start_btn` with:

```python
        self.start_btn = QPushButton("开始压缩")
        self.start_btn.setObjectName("primary_action")
        self.start_btn.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.start_btn)
```

- [ ] **Step 4: Update about text**

In `MainWindow._show_about()`, replace the body text with:

```python
        QMessageBox.about(self, "关于 LeanReel",
            "LeanReel — 视频压缩管理工具\n\n"
            "默认保护 HEVC/HDR/Dolby Vision 片源。\n"
            "为 SDR 旧编码片源提供可解释的本地转码策略。"
        )
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
py -m pytest tests/test_main_window.py::test_about_text_avoids_absolute_lossless_claim tests/test_main_window.py::test_start_button_uses_primary_action_object_name -q
```

Expected: both tests pass.

- [ ] **Step 6: Run UI tests**

Run:

```bash
py -m pytest tests/test_main_window.py tests/test_preset_card_panel.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add leanreel/gui/main_window.py leanreel/gui/theme.py leanreel/gui/strategy_panel.py tests/test_main_window.py
git commit -m "chore: align UI copy and primary styling"
```

## Task 9: Visual QA And Documentation

**Files:**

- Modify: `README.md`
- Modify: `docs/ui-optimization-principles.md`

- [ ] **Step 1: Update UI behavior documentation**

In `README.md`, update the UI section so it describes:

- Protected sources show explicit skip reasons.
- `全选` excludes protected sources.
- Filters are `全部`, `可处理`, `已保护跳过`, `探测失败`, and `已选择`.
- `清空已完成` only removes terminal rows.
- Custom strategies are named by encoder and parameter.

Add this exact paragraph near the existing file-list usage section.

```markdown
文件列表现在以“处理状态”为核心展示决策。HEVC/H.265、HDR10、HDR10+ 和 Dolby Vision 会显示明确的跳过原因，并在预计结果中显示“不处理”。`全选` 只选择可处理文件，筛选器可快速查看可处理、已保护跳过、探测失败和已选择文件。
```

In `docs/ui-optimization-principles.md`, add an implementation-status section.

```markdown
## 实施后的 UI 规则

- 文件表中的保护片源必须显示跳过原因，不能显示为“未匹配”。
- 预计结果列对保护片源显示“不处理”。
- 筛选器只暴露已经实现的状态。
- 队列里的“清空已完成”只清除终态任务。
- 策略面板使用技术名，长名称必须可读并提供 tooltip。
```

- [ ] **Step 2: Run documentation scan**

Run:

```bash
rg -n "视觉无损|完整无损|轻量压缩|均衡压缩|极限压缩" README.md docs leanreel/gui tests
```

Expected: any remaining hits are either historical tests that will be updated in this plan or unrelated low-level data tests. No user-facing UI copy should contain `视觉无损` or `完整无损`.

- [ ] **Step 3: Capture visual screenshot**

Run the app manually or use the existing offscreen screenshot technique from the review session. Capture these states:

- 1400x900 default workbench.
- 900x600 minimum window.
- File table with one SDR H.264 row, one HEVC row, one HDR10 row, and one long filename row.
- Queue with running, skipped, failed, and completed rows.

Pass criteria:

- Strategy names are readable or have tooltips.
- Protected rows are visibly non-actionable.
- Filters are visible and not cramped.
- Queue failed row shows the failure reason.
- Bottom queue buttons do not imply a broader action than they perform.

- [ ] **Step 4: Run full verification**

Run:

```bash
py -m pytest -q
```

Expected: the full test suite passes.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ui-optimization-principles.md
git commit -m "docs: record leanreel ui decision rules"
```

## Edge Cases, Failure Modes, And Risks

**Protected Source Priority**

- If a file is both HEVC and HDR10, the UI may show only one primary skip reason. Prefer codec first: `跳过：HEVC/H.265 片源`. Use tooltip or future details panel for the secondary HDR fact.

**Probe Failure**

- Probe failure must not appear as a processable file.
- Probe failure should be filterable separately from protected skip.

**Long Strategy Names**

- Table cells may still truncate at narrow widths. Tooltip is required. Wider default columns reduce the common case.

**Large Libraries**

- Creating one `QComboBox` per row scales poorly. This plan keeps the current behavior for compatibility except where protected rows avoid combos. A later performance pass should replace per-row combo widgets with a delegate editor.

**Queue Semantics**

- `clear_tasks()` remains a full internal reset. UI button `清空已完成` should call `clear_finished()`, not `clear_tasks()` or `clear_all()`.

**Confirmation Dialogs**

- Confirmation dialogs must not claim disk files are preserved if the repository layer later changes behavior. Keep wording aligned with actual deletion semantics.

**Visual Styling**

- Do not increase amber usage beyond primary action, focus, selected strategy, and progress.
- Do not add side-stripe accents, gradients, glass effects, or decorative cards.

## Internal Role Review

**Builder**

The implementation is deliberately incremental. Each task modifies one UI area with focused tests. The display helper in `file_list.py` becomes the main boundary for deciding what the table should say.

**Reviewer**

The highest-value correction is semantic, not decorative: protected sources must not look like unmatched errors. Queue button labels must match behavior. Destructive actions need confirmation.

**Tester**

The plan uses pytest-qt tests for behavior, plus screenshot inspection for layout. The important regressions are row state display, filter behavior, selection counts, and queue clearing semantics.

**Performance**

The plan reduces unnecessary strategy combos for protected rows, but it does not fully solve per-row widget cost for very large libraries. A future task should introduce a delegate editor if thousands of rows are common.

## Validation Plan

Run these commands after all tasks are implemented.

```bash
py -m pytest tests/test_main_window.py tests/test_queue_panel.py tests/test_preset_card_panel.py tests/test_library_panel.py -q
```

Expected:

```text
all selected UI tests pass
```

Run:

```bash
py -m pytest -q
```

Expected:

```text
all repository tests pass
```

Run:

```bash
rg -n "完整无损|视觉无损" leanreel/gui README.md docs
```

Expected: no user-facing hits.

Visual QA must confirm:

- 1400x900 layout gives strategy panel enough width.
- 900x600 remains usable without text overlap.
- Protected rows are readable and non-actionable.
- Queue terminal clearing leaves running and pending rows in place.
- Failed rows show failure reason.

## Self-Review

**Spec coverage:** The plan covers protected-source display, real filtering, readable technical strategy names, queue safety, destructive library actions, copy cleanup, documentation, and validation.

**Red-flag scan:** The plan avoids unresolved markers and avoids asking implementers to infer test coverage without concrete examples.

**Type consistency:** New names are consistent across tasks: `FileDecisionDisplay`, `_decision_display()`, `_apply_filter()`, `_TREE_HEADERS`, `clear_finished()`, `custom_crf_spin`, and `primary_action`.

## Confidence

Confidence: `0.87`

Main uncertainties:

- Whether 320-360px is the ideal strategy-panel width on the user's real monitor and DPI.
- Whether the user wants tree view to support row checkboxes later.
- Whether historical compression records should be included in filters in a later iteration.
- Whether very large libraries require immediate delegate-based table editing rather than a later performance pass.
