# Scan Progress Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scanning show immediate, accurate progress across toolbar, sidebar refresh, and tree refresh entry points.

**Architecture:** The frontend owns scan orchestration and generates a `scan_id` before invoking Tauri. The Rust scanner emits phase and progress payloads with `scan_id` / `folder_id`, while filesystem discovery streams indeterminate progress. A small frontend reducer filters stale events and maps scan events to UI state.

**Tech Stack:** Rust, Tauri 2 events, Svelte 5 runes, Node built-in test runner.

---

## File Map

- Modify `src-tauri/src/infrastructure/filesystem.rs`: add `FileDiscoveryProgress` and progress/cancel callback support.
- Modify `src-tauri/tests/filesystem_tests.rs`: update signatures and add progress/cancel tests.
- Modify `src-tauri/src/services/scanner.rs`: add scan phase/progress event structs and scan id aware callbacks.
- Modify `src-tauri/tests/scanner_tests.rs`: add phase/progress callback tests.
- Modify `src-tauri/src/commands/scan.rs`: accept optional `scan_id` and pass it into scanner.
- Modify `src-tauri/src/lib.rs`: emit `scan-phase` and expanded `scan-progress` payloads.
- Modify `src/lib/api.ts`: pass optional `scanId`.
- Modify `src/lib/stores/files.ts`: expand scan progress type.
- Create `src/lib/scanProgress.js`: pure frontend scan state reducer.
- Create `src/lib/scanProgress.test.mjs`: reducer regression tests.
- Create `src/lib/treeNodes.js`: pure helper for tree-node refresh identity.
- Create `src/lib/treeNodes.test.mjs`: regression tests that prevent parsing folder ids from encoded keys.
- Modify `src/routes/+page.svelte`: centralize scan orchestration and use reducer output.
- Modify `src/lib/components/LibraryPanel.svelte`: delegate folder refresh to parent prop.
- Modify `src/lib/components/TreeView.svelte`: add context menu that delegates root-folder refresh to parent prop.

---

### Task 1: Stream Filesystem Discovery Progress

**Files:**
- Modify: `src-tauri/src/infrastructure/filesystem.rs`
- Modify: `src-tauri/tests/filesystem_tests.rs`

- [ ] **Step 1: Write failing discovery progress tests**

Add tests to `src-tauri/tests/filesystem_tests.rs`:

```rust
#[test]
fn test_reports_discovery_progress_for_visited_entries_and_video_count() {
    use leanreel_rs_lib::infrastructure::filesystem::FileDiscoveryProgress;
    use std::sync::{Arc, Mutex};

    let dir = std::env::temp_dir().join("leanreel_test_discovery_progress");
    fs::create_dir_all(dir.join("nested")).unwrap();
    fs::write(dir.join("nested").join("movie_a.mkv"), b"x").unwrap();
    fs::write(dir.join("nested").join("movie_b.mp4"), b"x").unwrap();
    fs::write(dir.join("notes.txt"), b"x").unwrap();

    let events: Arc<Mutex<Vec<FileDiscoveryProgress>>> = Arc::new(Mutex::new(Vec::new()));
    let captured = events.clone();
    let (files, warnings) = find_video_files(
        &dir,
        Some(&move |progress| {
            captured.lock().unwrap().push(progress);
            true
        }),
    );
    fs::remove_dir_all(&dir).ok();

    assert!(warnings.is_empty(), "test directory should scan cleanly: {warnings:?}");
    assert_eq!(files.len(), 2);
    let events = events.lock().unwrap();
    assert!(!events.is_empty(), "discovery should emit progress events");
    let final_event = events.last().unwrap();
    assert!(
        final_event.visited_entries >= 4,
        "should count directories and files as visited entries: {final_event:?}"
    );
    assert_eq!(final_event.video_files_found, 2);
}

#[test]
fn test_discovery_progress_can_stop_walk() {
    let dir = std::env::temp_dir().join("leanreel_test_discovery_cancel");
    fs::create_dir_all(&dir).unwrap();
    fs::write(dir.join("movie_a.mkv"), b"x").unwrap();
    fs::write(dir.join("movie_b.mp4"), b"x").unwrap();

    let (files, warnings) = find_video_files(&dir, Some(&|_progress| false));
    fs::remove_dir_all(&dir).ok();

    assert!(warnings.is_empty(), "manual stop is not an IO warning");
    assert!(
        files.len() <= 1,
        "callback returning false should stop before collecting the full directory: {files:?}"
    );
}
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
cargo test --test filesystem_tests -- --nocapture
```

Expected: compile failure because `FileDiscoveryProgress` and the new `find_video_files` signature do not exist.

- [ ] **Step 3: Implement discovery callback**

In `src-tauri/src/infrastructure/filesystem.rs`, add:

```rust
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FileDiscoveryProgress {
    pub visited_entries: usize,
    pub video_files_found: usize,
}

const DISCOVERY_PROGRESS_FILE_INTERVAL: usize = 50;
const DISCOVERY_PROGRESS_TIME_INTERVAL: Duration = Duration::from_millis(200);
```

Change the function signature:

```rust
pub fn find_video_files(
    root: &Path,
    on_progress: Option<&dyn Fn(FileDiscoveryProgress) -> bool>,
) -> (Vec<(String, PathBuf)>, Vec<String>)
```

Inside the walk loop, increment `visited_entries` for every successful entry, increment `video_files_found` only when a supported video file is found, call the callback on the first entry, every 50 visited entries, every 200ms, and once at the end. If the callback returns `false`, break the walk and return collected files.

- [ ] **Step 4: Update old call sites in tests**

Replace old calls in `src-tauri/tests/filesystem_tests.rs`:

```rust
find_video_files(&dir)
```

with:

```rust
find_video_files(&dir, None)
```

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
cargo test --test filesystem_tests -- --nocapture
```

Expected: all filesystem tests pass.

---

### Task 2: Add Scanner Phase and Progress Events

**Files:**
- Modify: `src-tauri/src/services/scanner.rs`
- Modify: `src-tauri/tests/scanner_tests.rs`
- Modify: `src-tauri/src/commands/scan.rs`
- Modify: `src-tauri/src/lib.rs`

- [ ] **Step 1: Write failing scanner event tests**

Add tests to `src-tauri/tests/scanner_tests.rs`:

```rust
#[test]
fn test_scanner_emits_discovering_probing_and_done_phases_with_scan_id() {
    use leanreel_rs_lib::services::scanner::{ScanPhase, ScanPhaseEvent};
    use std::sync::{Arc, Mutex};

    let dir = std::env::temp_dir().join("leanreel_test_scan_phase");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("movie.mkv"), b"content").unwrap();

    let (prober, _) = CountingProber::new();
    let (store, _) = CountingStore::new();
    let phases: Arc<Mutex<Vec<ScanPhaseEvent>>> = Arc::new(Mutex::new(Vec::new()));
    let phases_clone = phases.clone();
    let mut scanner = Scanner::new(Box::new(prober), Box::new(store));
    scanner.on_phase = Some(Box::new(move |event| {
        phases_clone.lock().unwrap().push(event.clone());
    }));

    let result = scanner.scan_directory(&dir, 7, "scan-test-1").unwrap();
    std::fs::remove_dir_all(&dir).ok();

    assert_eq!(result.total_files, 1);
    let phases = phases.lock().unwrap();
    assert_eq!(phases.len(), 3);
    assert_eq!(phases[0].scan_id, "scan-test-1");
    assert_eq!(phases[0].folder_id, 7);
    assert_eq!(phases[0].phase, ScanPhase::Discovering);
    assert_eq!(phases[1].phase, ScanPhase::Probing);
    assert_eq!(phases[2].phase, ScanPhase::Done);
}

#[test]
fn test_scanner_progress_includes_discovery_and_probe_payloads() {
    use leanreel_rs_lib::services::scanner::{ScanPhase, ScanProgressEvent};
    use std::sync::{Arc, Mutex};

    let dir = std::env::temp_dir().join("leanreel_test_scan_progress_payload");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("movie_a.mkv"), b"content a").unwrap();
    std::fs::write(dir.join("movie_b.mp4"), b"content b").unwrap();

    let (prober, _) = CountingProber::new();
    let (store, _) = CountingStore::new();
    let progress: Arc<Mutex<Vec<ScanProgressEvent>>> = Arc::new(Mutex::new(Vec::new()));
    let progress_clone = progress.clone();
    let mut scanner = Scanner::new(Box::new(prober), Box::new(store));
    scanner.on_progress = Some(Box::new(move |event| {
        progress_clone.lock().unwrap().push(event.clone());
    }));

    let result = scanner.scan_directory(&dir, 9, "scan-test-2").unwrap();
    std::fs::remove_dir_all(&dir).ok();

    assert_eq!(result.total_files, 2);
    let progress = progress.lock().unwrap();
    assert!(
        progress.iter().any(|event| event.phase == ScanPhase::Discovering
            && event.scan_id == "scan-test-2"
            && event.folder_id == 9
            && event.total == 0
            && event.video_files_found >= 1),
        "expected discovery progress payload: {progress:?}"
    );
    assert!(
        progress.iter().any(|event| event.phase == ScanPhase::Probing
            && event.done == 2
            && event.total == 2),
        "expected probing progress payload: {progress:?}"
    );
}
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
cargo test --test scanner_tests -- --nocapture
```

Expected: compile failure because `ScanPhase`, `ScanPhaseEvent`, `ScanProgressEvent`, and the new scanner signature do not exist.

- [ ] **Step 3: Add scanner event types and callbacks**

In `src-tauri/src/services/scanner.rs`, define:

```rust
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ScanPhase {
    Discovering,
    Probing,
    Done,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ScanPhaseEvent {
    pub scan_id: String,
    pub folder_id: i64,
    pub phase: ScanPhase,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ScanProgressEvent {
    pub scan_id: String,
    pub folder_id: i64,
    pub phase: ScanPhase,
    pub done: usize,
    pub total: usize,
    pub visited_entries: usize,
    pub video_files_found: usize,
}
```

Change scanner fields:

```rust
pub on_phase: Option<Box<dyn Fn(ScanPhaseEvent) + Send>>,
pub on_progress: Option<Box<dyn Fn(ScanProgressEvent) + Send>>,
```

Change scanner method signature:

```rust
pub fn scan_directory(&self, root: &Path, folder_id: i64, scan_id: &str) -> Result<ScanResult, String>
```

Emit `Discovering` before calling `find_video_files`, discovery progress from the filesystem callback, `Probing` after discovery completes, probing progress during cache/probe handling, and `Done` before returning.

- [ ] **Step 4: Update command and app setup**

In `src-tauri/src/commands/scan.rs`, change command signature:

```rust
pub async fn scan_directory(
    path: String,
    folder_id: i64,
    scan_id: Option<String>,
    state: State<'_, AppState>,
) -> Result<ScanCommandResult, String>
```

Use:

```rust
let scan_id = scan_id.unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
scanner.scan_directory(std::path::Path::new(&path), actual_folder_id, &scan_id)?;
```

In `src-tauri/src/lib.rs`, set `scanner.on_phase` to emit `"scan-phase"` and set `scanner.on_progress` to emit `"scan-progress"` with the serialized event.

- [ ] **Step 5: Update old scanner tests and command signature test**

Replace old scanner calls:

```rust
scanner.scan_directory(&dir, 1)
```

with:

```rust
scanner.scan_directory(&dir, 1, "test-scan")
```

Update the async command type assertion in `src-tauri/src/commands/scan.rs` to accept the new `Option<String>` parameter.

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
cargo test --test scanner_tests -- --nocapture
cargo test --test commands_tests -- --nocapture
```

Expected: scanner and command tests pass.

---

### Task 3: Add Frontend Scan State Reducer

**Files:**
- Create: `src/lib/scanProgress.js`
- Create: `src/lib/scanProgress.test.mjs`
- Modify: `src/lib/stores/files.ts`

- [ ] **Step 1: Write failing reducer tests**

Create `src/lib/scanProgress.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createInitialScanUiState,
  beginScan,
  applyScanPhase,
  applyScanProgress,
} from './scanProgress.js';

test('beginScan creates immediate visible discovery state', () => {
  const state = beginScan(createInitialScanUiState(), {
    scanId: 'scan-1',
    folderId: 12,
    label: 'Movies',
  });

  assert.equal(state.activeScanId, 'scan-1');
  assert.equal(state.folderId, 12);
  assert.equal(state.phase, 'discovering');
  assert.equal(state.progressMode, 'indeterminate');
  assert.equal(state.visible, true);
  assert.equal(state.statusText, '正在扫描目录 Movies...');
});

test('discovery progress formats visited and found counts', () => {
  const started = beginScan(createInitialScanUiState(), {
    scanId: 'scan-1',
    folderId: 12,
    label: 'Movies',
  });
  const state = applyScanProgress(started, {
    scan_id: 'scan-1',
    folder_id: 12,
    phase: 'discovering',
    done: 23,
    total: 0,
    visited_entries: 1234,
    video_files_found: 23,
  });

  assert.equal(state.progressMode, 'indeterminate');
  assert.equal(state.statusText, '正在扫描目录 Movies...已访问 1,234 项，发现 23 个视频');
  assert.equal(state.progress.done, 23);
  assert.equal(state.progress.total, 0);
});

test('probing phase and progress switch to determinate mode', () => {
  const started = beginScan(createInitialScanUiState(), {
    scanId: 'scan-2',
    folderId: 3,
    label: 'Anime',
  });
  const probing = applyScanPhase(started, {
    scan_id: 'scan-2',
    folder_id: 3,
    phase: 'probing',
  });
  const state = applyScanProgress(probing, {
    scan_id: 'scan-2',
    folder_id: 3,
    phase: 'probing',
    done: 45,
    total: 150,
  });

  assert.equal(state.progressMode, 'determinate');
  assert.equal(state.statusText, '正在分析文件 45/150');
  assert.equal(state.progress.done, 45);
  assert.equal(state.progress.total, 150);
});

test('ignores stale scan events', () => {
  const started = beginScan(createInitialScanUiState(), {
    scanId: 'new-scan',
    folderId: 1,
    label: 'New',
  });
  const state = applyScanProgress(started, {
    scan_id: 'old-scan',
    folder_id: 1,
    phase: 'discovering',
    done: 99,
    total: 0,
    visited_entries: 999,
    video_files_found: 99,
  });

  assert.deepEqual(state, started);
});

test('done phase keeps a complete visible state for delayed hiding', () => {
  const started = beginScan(createInitialScanUiState(), {
    scanId: 'scan-3',
    folderId: 5,
    label: 'Done',
  });
  const state = applyScanPhase(started, {
    scan_id: 'scan-3',
    folder_id: 5,
    phase: 'done',
  });

  assert.equal(state.phase, 'done');
  assert.equal(state.progressMode, 'determinate');
  assert.equal(state.visible, true);
  assert.equal(state.statusText, '扫描完成');
});
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
node --test src/lib/scanProgress.test.mjs
```

Expected: failure because `src/lib/scanProgress.js` does not exist.

- [ ] **Step 3: Implement reducer**

Create `src/lib/scanProgress.js` with:

```javascript
export function createInitialScanUiState() {
  return {
    activeScanId: null,
    folderId: null,
    label: '',
    phase: null,
    progressMode: 'hidden',
    visible: false,
    statusText: '',
    progress: null,
  };
}

export function beginScan(_state, { scanId, folderId, label }) {
  return {
    activeScanId: scanId,
    folderId,
    label: label || '',
    phase: 'discovering',
    progressMode: 'indeterminate',
    visible: true,
    statusText: `正在扫描目录${label ? ` ${label}` : ''}...`,
    progress: {
      scan_id: scanId,
      folder_id: folderId,
      phase: 'discovering',
      done: 0,
      total: 0,
      visited_entries: 0,
      video_files_found: 0,
    },
  };
}

function isCurrentScan(state, event) {
  return state.activeScanId === event.scan_id;
}

export function applyScanPhase(state, event) {
  if (!isCurrentScan(state, event)) return state;
  if (event.phase === 'probing') {
    return {
      ...state,
      phase: 'probing',
      progressMode: 'determinate',
      visible: true,
      statusText: '正在分析文件 0/0',
      progress: { scan_id: event.scan_id, folder_id: event.folder_id, phase: 'probing', done: 0, total: 0 },
    };
  }
  if (event.phase === 'done') {
    return {
      ...state,
      phase: 'done',
      progressMode: 'determinate',
      visible: true,
      statusText: '扫描完成',
      progress: { scan_id: event.scan_id, folder_id: event.folder_id, phase: 'done', done: 1, total: 1 },
    };
  }
  return {
    ...state,
    phase: 'discovering',
    progressMode: 'indeterminate',
    visible: true,
  };
}

export function applyScanProgress(state, event) {
  if (!isCurrentScan(state, event)) return state;
  if (event.phase === 'discovering') {
    const visited = event.visited_entries ?? 0;
    const found = event.video_files_found ?? event.done ?? 0;
    return {
      ...state,
      phase: 'discovering',
      progressMode: 'indeterminate',
      visible: true,
      statusText: `正在扫描目录${state.label ? ` ${state.label}` : ''}...已访问 ${visited.toLocaleString()} 项，发现 ${found.toLocaleString()} 个视频`,
      progress: event,
    };
  }
  const total = event.total || 0;
  const done = event.done || 0;
  return {
    ...state,
    phase: 'probing',
    progressMode: 'determinate',
    visible: true,
    statusText: `正在分析文件 ${done}/${total}`,
    progress: event,
  };
}
```

- [ ] **Step 4: Expand store type**

In `src/lib/stores/files.ts`, change `scanProgress` to:

```ts
export type ScanPhase = 'discovering' | 'probing' | 'done';

export interface ScanProgressState {
  scan_id: string;
  folder_id: number;
  phase: ScanPhase;
  done: number;
  total: number;
  visited_entries?: number;
  video_files_found?: number;
}

export const scanProgress = writable<ScanProgressState | null>(null);
```

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
node --test src/lib/scanProgress.test.mjs
```

Expected: all reducer tests pass.

---

### Task 4: Integrate Frontend Entrypoints

**Files:**
- Modify: `src/lib/api.ts`
- Modify: `src/routes/+page.svelte`
- Modify: `src/lib/components/LibraryPanel.svelte`
- Modify: `src/lib/components/TreeView.svelte`

- [ ] **Step 1: Update API wrapper**

Change `scanDirectory` in `src/lib/api.ts` to:

```ts
export async function scanDirectory(path: string, folderId: number, scanId?: string): Promise<ScanResult> {
  return invoke('scan_directory', { path, folderId, scanId });
}
```

- [ ] **Step 2: Centralize scan orchestration in `+page.svelte`**

Import reducer helpers:

```ts
import { createInitialScanUiState, beginScan, applyScanPhase, applyScanProgress } from '$lib/scanProgress.js';
```

Add local state:

```ts
let scanUi = $state(createInitialScanUiState());
let scanHideTimer: ReturnType<typeof setTimeout> | null = null;
```

Add helpers:

```ts
function folderLabel(path: string): string {
  return path.split(/[/\\]/).pop() || path;
}

function makeScanId(folderId: number): string {
  return `scan-${folderId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function selectedFolderPath(folderId: number): string | null {
  for (const lib of $libraries) {
    const folder = lib.folders.find(f => f.id === folderId);
    if (folder) return folder.path;
  }
  return null;
}

async function reloadVisibleFiles() {
  if ($selectedFolderId) {
    await loadFolderFiles($selectedFolderId);
  } else if ($selectedLibraryId) {
    await loadLibraryFiles($selectedLibraryId);
  }
}

async function refreshFolder(folderId: number) {
  const path = selectedFolderPath(folderId);
  if (!path) { scanStatus.set('未找到文件夹路径'); return; }
  const scanId = makeScanId(folderId);
  scanUi = beginScan(scanUi, { scanId, folderId, label: folderLabel(path) });
  scanProgress.set(scanUi.progress);
  scanStatus.set(scanUi.statusText);
  try {
    await scanDirectory(path, folderId, scanId);
    await reloadVisibleFiles();
    const libs = await listLibraries();
    libraries.set(libs);
  } catch (e) {
    scanStatus.set(`错误: ${e}`);
  }
}
```

Update `handleScan` so selected-folder and library-folder loops call `refreshFolder(folder.id)`.

- [ ] **Step 3: Listen for phase/progress events**

In `onMount`, add:

```ts
listen<{scan_id: string, folder_id: number, phase: 'discovering' | 'probing' | 'done'}>('scan-phase', (event) => {
  scanUi = applyScanPhase(scanUi, event.payload);
  scanProgress.set(scanUi.progress);
  scanStatus.set(scanUi.statusText);
  if (event.payload.phase === 'done') {
    if (scanHideTimer) clearTimeout(scanHideTimer);
    scanHideTimer = setTimeout(() => {
      scanProgress.set(null);
      scanUi = createInitialScanUiState();
    }, 1500);
  }
});

listen<ScanProgressState>('scan-progress', (event) => {
  scanUi = applyScanProgress(scanUi, event.payload);
  scanProgress.set(scanUi.progress);
  scanStatus.set(scanUi.statusText);
});
```

Remove the old simple `scan-progress` listener.

- [ ] **Step 4: Update progress markup and style**

Change progress fill class:

```svelte
<div class="scan-progress" class:indeterminate={scanUi.progressMode === 'indeterminate'}>
  <div
    class="scan-progress-fill"
    style="width: {$scanProgress && $scanProgress.total > 0 ? Math.min(100, ($scanProgress.done / $scanProgress.total) * 100) : 100}%"
  ></div>
</div>
```

Add CSS:

```css
.scan-progress.indeterminate .scan-progress-fill {
  width: 45%;
  animation: scan-progress-pulse 1.1s var(--ease-expo) infinite;
}

@keyframes scan-progress-pulse {
  0% { transform: translateX(-110%); }
  100% { transform: translateX(230%); }
}
```

- [ ] **Step 5: Delegate LibraryPanel refresh**

In `LibraryPanel.svelte`, remove `scanDirectory`, `getLibraryFiles`, and `getFolderFiles` imports. Add prop:

```ts
let { onRefreshFolder = async (_folderId: number) => {} } = $props();
```

Change `handleRefreshFolder` to:

```ts
async function handleRefreshFolder(folderId: number) {
  pending = true;
  try {
    await onRefreshFolder(folderId);
  } catch (e) {
    status = `刷新失败: ${e}`;
  } finally {
    pending = false;
  }
}
```

Change `openAddFolder` to call `await onRefreshFolder(folderId)` after adding the folder.

Pass the prop in `+page.svelte`:

```svelte
<LibraryPanel onRefreshFolder={refreshFolder} />
```

- [ ] **Step 6: Add TreeView refresh context menu**

In `TreeView.svelte`, add props:

```ts
onRefreshFolder = async (_folderId: number) => {},
```

Add state:

```ts
let contextMenu = $state<{ x: number; y: number; folderId: number } | null>(null);
```

On folder row:

```svelte
oncontextmenu={(e) => {
  e.preventDefault();
  contextMenu = { x: e.clientX, y: e.clientY, folderId: Number(node.key.split(':')[1]) };
}}
```

Render menu:

```svelte
{#if contextMenu}
  <div class="context-overlay" onclick={() => contextMenu = null} onkeydown={(e) => e.key === 'Escape' && (contextMenu = null)}>
    <div class="context-menu" style="left: {contextMenu.x}px; top: {contextMenu.y}px">
      <button onclick={() => { const menu = contextMenu; contextMenu = null; if (menu) onRefreshFolder(menu.folderId); }}>
        刷新所在文件夹缓存
      </button>
    </div>
  </div>
{/if}
```

Pass prop from `+page.svelte`:

```svelte
<TreeView ... onRefreshFolder={refreshFolder} />
```

- [ ] **Step 7: Verify frontend compiles**

Run:

```powershell
pnpm check
node --test src/lib/*.test.mjs
```

Expected: no new TypeScript or reducer test failures. If `pnpm check` reports pre-existing warnings, record them with exact output.

---

### Task 5: Brooks Review Feedback Hardening

**Files:**
- Modify: `src/lib/scanProgress.js`
- Modify: `src/lib/scanProgress.test.mjs`
- Create: `src/lib/treeNodes.js`
- Create: `src/lib/treeNodes.test.mjs`
- Modify: `src/lib/stores/files.ts`
- Modify: `src/routes/+page.svelte`
- Modify: `src/lib/components/LibraryPanel.svelte`
- Modify: `src/lib/components/TreeView.svelte`

- [ ] **Step 1: Write failing tests for status propagation**

Add these tests to `src/lib/scanProgress.test.mjs`:

```javascript
test('library scan status reports folder failures instead of masking them', () => {
  assert.equal(
    formatLibraryScanStatus({ totalFiles: 8, totalOk: 6, failedCount: 2 }),
    '扫描结束: 8 文件, 6 成功，2 个文件夹失败',
  );
});

test('add folder status preserves initial scan failure', () => {
  assert.equal(
    formatAddFolderStatus('D:\\Media', { ok: false, error: 'ffprobe not found' }),
    '已添加 D:\\Media，但初次扫描失败: ffprobe not found',
  );
});
```

- [ ] **Step 2: Write failing test for explicit tree folder id**

Create `src/lib/treeNodes.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { getFolderNodeRefreshId } from './treeNodes.js';

test('folder refresh id comes from explicit folderId instead of encoded key shape', () => {
  const node = { key: 'folder:not-a-number:Movies', folderId: 42, isFolder: true };
  assert.equal(getFolderNodeRefreshId(node), 42);
});

test('folder refresh id is unavailable when node has no folderId', () => {
  const node = { key: 'folder:42:Movies', isFolder: true };
  assert.equal(getFolderNodeRefreshId(node), null);
});
```

- [ ] **Step 3: Verify RED**

Run:

```powershell
node --test src/lib/*.test.mjs
```

Expected: failure because `formatLibraryScanStatus`, `formatAddFolderStatus`, and `treeNodes.js` are missing.

- [ ] **Step 4: Add status helpers**

Add to `src/lib/scanProgress.js`:

```javascript
export function formatLibraryScanStatus({ totalFiles, totalOk, failedCount = 0 }) {
  if (failedCount > 0) {
    return `扫描结束: ${totalFiles} 文件, ${totalOk} 成功，${failedCount} 个文件夹失败`;
  }
  return `扫描完成: ${totalFiles} 文件, ${totalOk} 成功`;
}

export function formatAddFolderStatus(path, refreshResult) {
  if (!refreshResult.ok) {
    return `已添加 ${path}，但初次扫描失败: ${refreshResult.error || '未知错误'}`;
  }
  return `已添加 ${path}`;
}

export function scanErrorMessage(error) {
  if (error instanceof Error) return error.message;
  return String(error);
}
```

- [ ] **Step 5: Add explicit tree-node helper**

Create `src/lib/treeNodes.js`:

```javascript
export function getFolderNodeRefreshId(node) {
  return typeof node.folderId === 'number' ? node.folderId : null;
}
```

- [ ] **Step 6: Return discriminated refresh results**

In `src/routes/+page.svelte`, add:

```ts
type FolderRefreshResult =
  | { ok: true; result: ScanResult }
  | { ok: false; error: string };
```

Change `refreshFolder` to return `Promise<FolderRefreshResult>`. Missing paths and caught exceptions return `{ ok: false, error }`; successful scans return `{ ok: true, result }`.

In library-level scanning, aggregate failed folders:

```ts
let totalFiles = 0, totalOk = 0, failedCount = 0;
const refresh = await refreshFolder(folder.id);
if (!refresh.ok) {
  failedCount += 1;
  continue;
}
totalFiles += refresh.result.total_files;
totalOk += refresh.result.probe_ok;
scanStatus.set(formatLibraryScanStatus({ totalFiles, totalOk, failedCount }));
```

- [ ] **Step 7: Preserve add-folder partial failure status**

In `src/lib/components/LibraryPanel.svelte`, type `onRefreshFolder` as returning `RefreshFolderResult` and set:

```ts
const refreshResult = await onRefreshFolder(folderId);
status = formatAddFolderStatus(selected, refreshResult);
scanStatus.set(status);
```

In `handleRefreshFolder`, if `!result.ok`, set both local status and global `scanStatus` to `刷新失败: ${result.error}`.

- [ ] **Step 8: Stop parsing folder id from tree keys**

In `src/lib/components/TreeView.svelte`, add `folderId?: number` to `TreeNode`, set `folderId: f.folder_id` when creating folder nodes, and replace `Number(node.key.split(':')[1])` with:

```ts
const folderId = getFolderNodeRefreshId(node);
if (folderId !== null) contextMenu = { x: e.clientX, y: e.clientY, folderId };
```

- [ ] **Step 9: Verify GREEN**

Run:

```powershell
node --test src/lib/*.test.mjs
pnpm check
```

Expected: frontend tests pass and Svelte/TypeScript reports no errors.

---

### Task 6: Final Verification

**Files:**
- Review all modified files

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
cargo test --test filesystem_tests --test scanner_tests --test commands_tests -- --nocapture
```

Expected: all focused backend tests pass.

- [ ] **Step 2: Run frontend tests**

Run:

```powershell
node --test src/lib/*.test.mjs
pnpm check
```

Expected: frontend unit tests pass; `pnpm check` has no new errors.

- [ ] **Step 3: Run formatting and full backend tests**

Run:

```powershell
cargo fmt --check
cargo test
git diff --check
```

Expected: Rust formatting passes, Rust tests pass, and diff has no whitespace errors.

- [ ] **Step 4: Review diff**

Run:

```powershell
git status --short --branch
git diff --stat
git diff -- src-tauri src docs/superpowers
```

Expected: only scan progress feedback files are changed.
