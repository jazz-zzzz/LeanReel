# Per-Task I/O Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace share-level SMB sampling with per-ffmpeg-process I/O throughput metrics and display `IO类型 / IO读 / IO写` for local, SMB, and mixed tasks.

**Architecture:** Add a focused `process_io` infrastructure module that snapshots Windows process I/O counters through `GetProcessIoCounters` and calculates average throughput from counter deltas. The ffmpeg runner owns measurement because it owns the child process handle. The worker persists the resulting metrics in the existing JSON column, and the history panel uses a small compatibility helper to display both new records and old SMB records.

**Tech Stack:** Rust, Windows `GetProcessIoCounters`, `windows-sys`, serde JSON, Svelte 5, Node built-in test runner.

---

## File Map

- Create `src-tauri/src/infrastructure/process_io.rs`: classify path topology, snapshot child-process counters, and summarize per-task throughput.
- Modify `src-tauri/src/infrastructure/ffmpeg.rs`: capture snapshots around each ffmpeg child lifecycle and return `IoMetrics`.
- Modify `src-tauri/src/domain/traits.rs`: replace `SmbMetrics` with process-level `IoMetrics`.
- Modify `src-tauri/src/services/worker.rs`: remove the background SMB sampler and serialize new `io_*` JSON fields.
- Modify `src-tauri/src/infrastructure/mod.rs`: export `process_io`, stop exporting `smb_metrics`.
- Delete `src-tauri/src/infrastructure/smb_metrics.rs`: remove the replaced share-level `typeperf` implementation, including the current uncommitted repair.
- Modify `src-tauri/Cargo.toml`: add the Windows API dependency.
- Modify `src-tauri/tests/encode_lifecycle_tests.rs` and `src-tauri/tests/worker_tests.rs`: update `EncodeOutput` fixtures.
- Create `src/lib/ioMetrics.js`: normalize new and legacy history JSON for display.
- Create `src/lib/ioMetrics.test.mjs`: lock down frontend compatibility behavior.
- Modify `src/lib/components/HistoryPanel.svelte`: render the three unified I/O columns.

### Task 1: Add Process I/O Domain Types and Pure Calculations

**Files:**
- Modify: `src-tauri/src/domain/traits.rs`
- Create: `src-tauri/src/infrastructure/process_io.rs`
- Modify: `src-tauri/src/infrastructure/mod.rs`

- [ ] **Step 1: Write failing tests for path classification and throughput calculation**

Add tests in `src-tauri/src/infrastructure/process_io.rs` that expect:

```rust
#[test]
fn classifies_local_smb_and_mixed_paths() {
    assert_eq!(io_type_for_paths(Path::new(r"C:\input.mkv"), Path::new(r"D:\out.mkv")), "local");
    assert_eq!(io_type_for_paths(Path::new(r"\\nas\share\input.mkv"), Path::new(r"\\nas\share\out.mkv")), "smb");
    assert_eq!(io_type_for_paths(Path::new(r"C:\input.mkv"), Path::new(r"\\nas\share\out.mkv")), "mixed");
    assert_eq!(io_type_for_paths(Path::new(r"\\nas\share\input.mkv"), Path::new(r"D:\out.mkv")), "mixed");
}

#[test]
fn summarizes_counter_delta_as_average_bytes_per_second() {
    let start = ProcessIoSnapshot { read_bytes: 100, write_bytes: 200 };
    let end = ProcessIoSnapshot { read_bytes: 2_100, write_bytes: 1_200 };
    assert_eq!(
        summarize_io(start, end, Duration::from_secs(2), "mixed"),
        Some(IoMetrics {
            io_type: "mixed".into(),
            read_bytes_per_sec: 1_000.0,
            write_bytes_per_sec: 500.0,
        })
    );
}

#[test]
fn refuses_zero_duration_measurement() {
    let counters = ProcessIoSnapshot { read_bytes: 1, write_bytes: 1 };
    assert_eq!(summarize_io(counters, counters, Duration::ZERO, "local"), None);
}
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
cargo test --lib process_io -- --nocapture
```

Expected: compilation fails because `ProcessIoSnapshot`, `io_type_for_paths`, and `summarize_io` do not exist.

- [ ] **Step 3: Add the minimal domain type and pure implementation**

Replace `SmbMetrics` in `src-tauri/src/domain/traits.rs` with:

```rust
#[derive(Debug, Clone, PartialEq, Default, serde::Serialize)]
pub struct IoMetrics {
    pub io_type: String,
    pub read_bytes_per_sec: f64,
    pub write_bytes_per_sec: f64,
}
```

Create `src-tauri/src/infrastructure/process_io.rs` with `ProcessIoSnapshot`, `is_smb_path`, `io_type_for_paths`, and `summarize_io`. Use `saturating_sub` for counter deltas and return `None` for a zero duration.

Export it from `src-tauri/src/infrastructure/mod.rs`:

```rust
pub mod process_io;
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run:

```powershell
cargo test --lib process_io -- --nocapture
```

Expected: the three new pure-function tests pass.

### Task 2: Read Windows Child-Process I/O Counters

**Files:**
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/src/infrastructure/process_io.rs`

- [ ] **Step 1: Add a Windows-only failing integration-style unit test**

Add:

```rust
#[cfg(windows)]
#[test]
fn snapshots_a_running_child_process() {
    let mut child = Command::new("cmd")
        .args(["/C", "ping -n 3 127.0.0.1 >NUL"])
        .spawn()
        .unwrap();
    let sample = snapshot_process_io(&child);
    let _ = child.kill();
    let _ = child.wait();
    assert!(sample.is_some());
}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
cargo test --lib process_io::tests::snapshots_a_running_child_process -- --nocapture
```

Expected: compilation fails because `snapshot_process_io` does not exist.

- [ ] **Step 3: Add the Windows API dependency and implementation**

Add to `src-tauri/Cargo.toml`:

```toml
[target.'cfg(windows)'.dependencies]
windows-sys = { version = "0.61", features = ["Win32_System_Threading"] }
```

In `process_io.rs`, add a Windows implementation using:

```rust
use std::os::windows::io::AsRawHandle;
use windows_sys::Win32::System::Threading::{GetProcessIoCounters, IO_COUNTERS};
```

Call `GetProcessIoCounters(child.as_raw_handle() as _, &mut counters)`. Return `Some(ProcessIoSnapshot { read_bytes: counters.ReadTransferCount, write_bytes: counters.WriteTransferCount })` on success and `None` on failure. Add a non-Windows implementation that always returns `None`.

- [ ] **Step 4: Run the test and verify GREEN**

Run:

```powershell
cargo test --lib process_io -- --nocapture
```

Expected: all process I/O module tests pass.

### Task 3: Measure Each ffmpeg Child

**Files:**
- Modify: `src-tauri/src/infrastructure/ffmpeg.rs`
- Modify: `src-tauri/tests/encode_lifecycle_tests.rs`
- Modify: `src-tauri/tests/worker_tests.rs`

- [ ] **Step 1: Update fixtures first and verify the compile failure**

Change each test fixture from:

```rust
smb_metrics: None,
```

to:

```rust
io_metrics: None,
```

Run:

```powershell
cargo test --tests --no-run
```

Expected: compilation fails because `EncodeOutput` still exposes `smb_metrics`.

- [ ] **Step 2: Change the output contract**

In `src-tauri/src/domain/traits.rs`, change `EncodeOutput` to:

```rust
pub io_metrics: Option<IoMetrics>,
```

In `src-tauri/src/infrastructure/ffmpeg.rs`, import:

```rust
use crate::infrastructure::process_io::{io_type_for_paths, snapshot_process_io, summarize_io};
```

Capture the initial snapshot immediately after spawning ffmpeg. After waiting for a successful child exit, capture the final snapshot while the child handle is still alive. Summarize the two snapshots with `encode_start.elapsed()` and `io_type_for_paths(&job.input_path, &job.output_path)`. Return the result as `io_metrics`.

- [ ] **Step 3: Verify compilation and existing lifecycle tests**

Run:

```powershell
cargo test --tests --no-run
cargo test --test encode_lifecycle_tests -- --nocapture
cargo test --test worker_tests -- --nocapture
```

Expected: compilation succeeds and both lifecycle suites pass.

### Task 4: Persist New Metrics and Remove Shared SMB Sampling

**Files:**
- Modify: `src-tauri/src/services/worker.rs`
- Modify: `src-tauri/src/infrastructure/mod.rs`
- Delete: `src-tauri/src/infrastructure/smb_metrics.rs`

- [ ] **Step 1: Write a failing JSON persistence test**

Extract a helper in the worker module and first add a test expecting:

```rust
#[test]
fn performance_metrics_json_contains_per_task_io_fields() {
    let json = performance_metrics_json(120.0, 4_000, Some(&IoMetrics {
        io_type: "mixed".into(),
        read_bytes_per_sec: 100.0,
        write_bytes_per_sec: 50.0,
    }));
    let value: serde_json::Value = serde_json::from_str(&json).unwrap();
    assert_eq!(value["io_type"], "mixed");
    assert_eq!(value["io_read_bytes_sec"], 100.0);
    assert_eq!(value["io_write_bytes_sec"], 50.0);
    assert!(value.get("smb_avg_bytes_per_request").is_none());
}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
cargo test --lib services::worker::tests::performance_metrics_json_contains_per_task_io_fields -- --nocapture
```

Expected: compilation fails because `performance_metrics_json` does not exist.

- [ ] **Step 3: Replace worker sampling and persistence**

Remove `SmbMetrics`, `spawn_smb_sampler`, and the background sampler lifecycle from `worker.rs`. Add:

```rust
fn performance_metrics_json(max_fps: f32, avg_bitrate_kbps: u32, io: Option<&IoMetrics>) -> String {
    serde_json::json!({
        "max_fps": max_fps,
        "avg_bitrate_kbps": avg_bitrate_kbps,
        "io_type": io.map(|m| m.io_type.as_str()),
        "io_read_bytes_sec": io.map(|m| m.read_bytes_per_sec),
        "io_write_bytes_sec": io.map(|m| m.write_bytes_per_sec),
    })
    .to_string()
}
```

Use it when completing a history record. Stop exporting `smb_metrics` from `infrastructure/mod.rs`, then delete `src-tauri/src/infrastructure/smb_metrics.rs`.

- [ ] **Step 4: Run backend tests and verify GREEN**

Run:

```powershell
cargo test --lib services::worker::tests::performance_metrics_json_contains_per_task_io_fields -- --nocapture
cargo test
```

Expected: the JSON test and the complete Rust suite pass.

### Task 5: Normalize New and Legacy Metrics in the History Panel

**Files:**
- Create: `src/lib/ioMetrics.js`
- Create: `src/lib/ioMetrics.test.mjs`
- Modify: `src/lib/components/HistoryPanel.svelte`

- [ ] **Step 1: Write failing frontend compatibility tests**

Create `src/lib/ioMetrics.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeIoMetrics } from './ioMetrics.js';

test('normalizes process-level io metrics', () => {
  assert.deepEqual(normalizeIoMetrics('{"io_type":"mixed","io_read_bytes_sec":100,"io_write_bytes_sec":50}'), {
    type: '混合',
    readBytesSec: 100,
    writeBytesSec: 50,
  });
});

test('falls back to old smb throughput fields', () => {
  assert.deepEqual(normalizeIoMetrics('{"smb_read_bytes_sec":100,"smb_write_bytes_sec":50}'), {
    type: 'SMB',
    readBytesSec: 100,
    writeBytesSec: 50,
  });
});

test('returns null for records without io metrics', () => {
  assert.equal(normalizeIoMetrics('{"max_fps":120}'), null);
});
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
node --test src/lib/ioMetrics.test.mjs
```

Expected: failure because `src/lib/ioMetrics.js` does not exist.

- [ ] **Step 3: Implement the normalizer and update the table**

Create `src/lib/ioMetrics.js` with `normalizeIoMetrics(json)`. Parse defensively, map `local / smb / mixed` to `本地 / SMB / 混合`, prefer `io_*` fields, and fall back to old `smb_*` throughput fields.

In `HistoryPanel.svelte`, import the helper and replace the columns:

```svelte
<th class="mono-col">IO类型</th>
<th class="mono-col">IO读</th>
<th class="mono-col">IO写</th>
```

For each row, derive `io = normalizeIoMetrics(rec.performance_metrics)` and render:

```svelte
<td class="mono-col">{io?.type || '—'}</td>
<td class="mono-col">{fmtBytesSec(io?.readBytesSec)}</td>
<td class="mono-col">{fmtBytesSec(io?.writeBytesSec)}</td>
```

- [ ] **Step 4: Run the frontend tests and verify GREEN**

Run:

```powershell
node --test src/lib/ioMetrics.test.mjs
```

Expected: all three frontend tests pass.

### Task 6: Verify the Full Change

**Files:**
- Review all modified files

- [ ] **Step 1: Run focused formatting and diff checks**

Run:

```powershell
rustfmt src/infrastructure/process_io.rs src/infrastructure/ffmpeg.rs src/domain/traits.rs src/services/worker.rs src/infrastructure/mod.rs
git diff --check
```

Expected: no whitespace errors. Do not format unrelated committed files.

- [ ] **Step 2: Run full tests**

Run:

```powershell
cargo test
node --test src/lib/*.test.mjs
```

Expected: all Rust and Node tests pass.

- [ ] **Step 3: Run project checks and report pre-existing failures accurately**

Run:

```powershell
pnpm check
cargo fmt --check
cargo clippy --all-targets -- -D warnings
```

Expected baseline before this feature:

- `pnpm check` already fails with two queue status typing errors and existing Svelte accessibility warnings.
- repository-wide `cargo fmt --check` already reports formatting drift in `src-tauri/src/domain/traits.rs` and `src-tauri/src/services/worker.rs`; formatting touched lines may resolve those diffs.
- Clippy already reports `manual_checked_ops` in `src-tauri/src/infrastructure/ffmpeg.rs` and `redundant_closure` in `src-tauri/src/services/worker.rs`; touched code should not add new warnings.

- [ ] **Step 4: Review version control state**

Run:

```powershell
git status --short --branch
git diff --stat
git diff -- src-tauri src/lib
```

Expected: only the planned process I/O implementation, the replacement of the earlier uncommitted SMB repair, and the history-panel compatibility files appear.
