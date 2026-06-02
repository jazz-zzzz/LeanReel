# Per-Task I/O Metrics Design

## Goal

Replace shared SMB counter sampling with per-task ffmpeg process I/O metrics. The history panel should show useful read and write throughput for local disks, SMB shares, and mixed local/network paths without mixing concurrent tasks together.

## User-Facing Behavior

The history table replaces `SMB读`, `SMB写`, and `B/Req` with:

- `IO类型`: `本地`, `SMB`, or `混合`
- `IO读`: average bytes read per second by the task's ffmpeg process
- `IO写`: average bytes written per second by the task's ffmpeg process

`B/Req` is removed because Windows exposes it as an SMB share-level metric, not a per-process metric.

The I/O type is derived from the task paths:

| Input path | Output path | Label |
| --- | --- | --- |
| Local | Local | `本地` |
| SMB | SMB | `SMB` |
| Local | SMB | `混合` |
| SMB | Local | `混合` |

## Architecture

The ffmpeg runner owns the process and therefore owns I/O measurement. Immediately after spawning ffmpeg, it reads the child process I/O counters. After ffmpeg exits, while the child handle is still available, it reads them again. The delta is divided by the elapsed encode duration.

On Windows, the runner uses `GetProcessIoCounters` against the existing child process handle. On platforms where process I/O counters are unavailable, encoding continues normally and the metrics remain absent.

The worker no longer starts a share-level `typeperf` background sampler. It persists the process-level metrics returned by the ffmpeg runner.

## Data Shape

Completed records write these fields into the existing `performance_metrics` JSON:

```json
{
  "max_fps": 123.0,
  "avg_bitrate_kbps": 4567,
  "io_type": "local",
  "io_read_bytes_sec": 104857600.0,
  "io_write_bytes_sec": 52428800.0
}
```

The database schema does not change.

For existing history records, the frontend keeps backward-compatible fallback support:

- If new `io_*` fields exist, display them.
- Otherwise, display old `smb_*` throughput fields and label the record `SMB`.
- Old local records without I/O fields display `—`.

## Scope

Included:

- Windows per-ffmpeg-process I/O measurement
- Local, SMB, and mixed path labels
- History JSON persistence
- History panel column replacement
- Backward-compatible display of old SMB history records
- Regression tests for label classification, metric calculation, persistence shape, and frontend fallback helpers where practical

Excluded:

- Per-stage I/O metrics
- Live I/O display during encoding
- Device-level disk utilization or queue length
- SMB request size and SMB queue length
- Database backfill for existing records

## Error Handling

I/O measurement is observational. Failure to read process counters must never fail an encode. The runner records no I/O metrics and the history panel displays `—`.

## Accuracy Notes

The metrics are scoped to the ffmpeg process, so concurrent LeanReel tasks no longer contaminate one another. Windows process counters may include small amounts of ffmpeg process overhead in addition to media file traffic. This is acceptable for task-level throughput diagnostics and is substantially more accurate than device- or share-level sampling.

