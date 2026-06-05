use super::time_utils::local_now;
use crate::domain::models::*;
use crate::domain::traits::{MediaProber, SnapshotStore};
use crate::infrastructure::filesystem::find_video_files;
use std::collections::{HashMap, HashSet};
use std::path::Path;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

type ResultCallback = Box<dyn Fn(&FileSnapshot) + Send>;

pub struct Scanner {
    prober: Box<dyn MediaProber + Send>,
    store: Box<dyn SnapshotStore + Send>,
    /// Optional cancellation token — when set and true, scan stops early.
    pub cancelled: Option<Arc<AtomicBool>>,
    /// Optional progress callback — called with (current, total) during scan.
    pub on_progress: Option<Box<dyn Fn(usize, usize) + Send>>,
    /// Optional per-file result callback — called for each file (cached or newly probed).
    /// Mirrors Python's `on_result` callback in `ProbeBatch`.
    pub on_result: Option<ResultCallback>,
}

impl Scanner {
    pub fn new(prober: Box<dyn MediaProber + Send>, store: Box<dyn SnapshotStore + Send>) -> Self {
        Self {
            prober,
            store,
            cancelled: None,
            on_progress: None,
            on_result: None,
        }
    }

    /// Attach a shared cancellation token so external code can signal stop.
    pub fn with_cancel_token(mut self, token: Arc<AtomicBool>) -> Self {
        self.cancelled = Some(token);
        self
    }

    /// Attach a per-file result callback (H-004).
    pub fn with_on_result(mut self, cb: Box<dyn Fn(&FileSnapshot) + Send>) -> Self {
        self.on_result = Some(cb);
        self
    }

    /// Check whether cancellation has been requested.
    fn is_cancelled(&self) -> bool {
        self.cancelled
            .as_ref()
            .map(|t| t.load(Ordering::Relaxed))
            .unwrap_or(false)
    }

    /// For testing: expose upserted data via store query
    pub fn store_borrow(&self) -> Result<Vec<FileSnapshot>, String> {
        let filter = FileFilter {
            library_id: None,
            folder_id: None,
            probe_ok_only: None,
        };
        self.store.query(&filter)
    }

    pub fn scan_directory(&self, root: &Path, folder_id: i64) -> Result<ScanResult, String> {
        // 1. Discover files: returns (files, warnings)
        let (discovered, warnings) = find_video_files(root);
        if !warnings.is_empty() {
            return Err(warnings.join("\n"));
        }
        if let Some(ref cb) = self.on_progress {
            cb(0, discovered.len());
        }
        if self.is_cancelled() {
            return Ok(ScanResult {
                total_files: 0,
                probe_ok: 0,
                probe_failed: 0,
            });
        }
        let discovered_set: HashSet<String> = discovered.iter().map(|(r, _)| r.clone()).collect();
        let total_discovered = discovered.len();

        // 2. Load cached snapshots for this folder
        let cache_filter = FileFilter {
            library_id: None,
            folder_id: Some(folder_id),
            probe_ok_only: None,
        };
        let cached = self.store.query(&cache_filter)?;

        if self.is_cancelled() {
            return Ok(ScanResult {
                total_files: 0,
                probe_ok: 0,
                probe_failed: 0,
            });
        }

        let cache_map: HashMap<String, &FileSnapshot> = cached
            .iter()
            .map(|s| (s.relative_path.clone(), s))
            .collect();

        // 3. Separate files: known-good (skip), new/changed (probe)
        let total = discovered.len();
        let mut to_probe: Vec<(String, std::path::PathBuf)> = Vec::new();
        let mut probed_count = 0usize;
        for (rel_path, abs_path) in &discovered {
            if let Some(cached_snap) = cache_map.get(rel_path) {
                if let Ok(meta) = std::fs::metadata(abs_path) {
                    let size = meta.len() as i64;
                    let mtime = meta
                        .modified()
                        .ok()
                        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                        .map(|d| d.as_secs_f64())
                        .unwrap_or(0.0);
                    if cached_snap.size_bytes == size
                        && (cached_snap.file_mtime - mtime).abs() < 0.01
                        && cached_snap.probe_complete()
                    {
                        // File unchanged and previously probed successfully — skip probing
                        // H-004: Fire per-file result callback for cached files
                        probed_count += 1;
                        if let Some(ref cb) = self.on_progress {
                            cb(probed_count, total);
                        }
                        if let Some(ref cb) = self.on_result {
                            cb(cached_snap);
                        }
                        continue;
                    }
                }
            }
            to_probe.push((rel_path.clone(), abs_path.clone()));
        }

        // 4. Probe new/changed files (check cancel before expensive work)
        let scanned = total.saturating_sub(to_probe.len());
        if let Some(ref cb) = self.on_progress {
            cb(scanned, total);
        }
        if self.is_cancelled() {
            return Ok(ScanResult {
                total_files: total_discovered,
                probe_ok: total_discovered.saturating_sub(to_probe.len()),
                probe_failed: 0,
            });
        }
        if let Some(ref cb) = self.on_result {
            for (relative_path, absolute_path) in &to_probe {
                let metadata = std::fs::metadata(absolute_path).ok();
                let size_bytes = metadata.as_ref().map(|m| m.len() as i64).unwrap_or(0);
                let file_mtime = metadata
                    .and_then(|m| m.modified().ok())
                    .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                    .map(|d| d.as_secs_f64())
                    .unwrap_or(0.0);
                cb(&FileSnapshot {
                    library_folder_id: folder_id,
                    relative_path: relative_path.clone(),
                    file_name: absolute_path
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("unknown")
                        .to_string(),
                    size_bytes,
                    file_mtime,
                    probe_ok: false,
                    ..Default::default()
                });
            }
        }
        let probe_paths: Vec<std::path::PathBuf> =
            to_probe.iter().map(|(_, p)| p.clone()).collect();
        let probe_results = self.prober.probe_batch(&probe_paths)?;

        // 5. Build snapshots for probed files, fire per-file callbacks
        let mut new_snapshots: Vec<FileSnapshot> = Vec::new();
        for result in &probe_results {
            // Find matching relative path
            let rel = to_probe
                .iter()
                .find(|(_, p)| *p == result.path)
                .map(|(r, _)| r.clone())
                .unwrap_or_else(|| {
                    // Fallback: use absolute path string
                    result.path.to_string_lossy().to_string().replace('\\', "/")
                });

            let file_name = result
                .path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("unknown")
                .to_string();

            let meta = std::fs::metadata(&result.path).ok();
            let size = meta.as_ref().map(|m| m.len() as i64).unwrap_or(0);
            let mtime = meta
                .and_then(|m| m.modified().ok())
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0);

            match &result.metadata {
                Ok(meta) => {
                    let snap = FileSnapshot {
                        id: None,
                        library_folder_id: folder_id,
                        relative_path: rel,
                        file_name,
                        size_bytes: size,
                        video_codec: meta.codec.clone(),
                        video_width: meta.width,
                        video_height: meta.height,
                        hdr_type: meta.hdr_type.clone(),
                        audio_tracks: meta.audio_tracks.clone(),
                        subtitle_tracks: meta.subtitle_tracks.clone(),
                        duration_seconds: meta.duration_seconds,
                        bitrate_bps: meta.bitrate_bps,
                        file_mtime: mtime,
                        probe_ok: true,
                        probe_error: String::new(),
                        scanned_at: local_now(),
                        pix_fmt: meta.pix_fmt.clone(),
                        frame_rate: meta.frame_rate.clone(),
                        color_primaries: meta.color_primaries.clone(),
                        color_transfer: meta.color_transfer.clone(),
                        color_space: meta.color_space.clone(),
                    };
                    // H-004: Fire per-file result callback
                    probed_count += 1;
                    if let Some(ref cb) = self.on_progress {
                        cb(probed_count, total);
                    }
                    if let Some(ref cb) = self.on_result {
                        cb(&snap);
                    }
                    new_snapshots.push(snap);
                }
                Err(e) => {
                    let snap = FileSnapshot {
                        id: None,
                        library_folder_id: folder_id,
                        relative_path: rel,
                        file_name,
                        size_bytes: size,
                        video_codec: VideoCodec::Unknown("unknown".into()),
                        video_width: 0,
                        video_height: 0,
                        hdr_type: HdrType::Sdr,
                        audio_tracks: vec![],
                        subtitle_tracks: vec![],
                        duration_seconds: 0.0,
                        bitrate_bps: 0,
                        file_mtime: 0.0,
                        probe_ok: false,
                        probe_error: e.clone(),
                        scanned_at: local_now(),
                        pix_fmt: String::new(),
                        frame_rate: String::new(),
                        color_primaries: String::new(),
                        color_transfer: String::new(),
                        color_space: String::new(),
                    };
                    // H-004: Fire per-file result callback even for failures
                    probed_count += 1;
                    if let Some(ref cb) = self.on_progress {
                        cb(probed_count, total);
                    }
                    if let Some(ref cb) = self.on_result {
                        cb(&snap);
                    }
                    new_snapshots.push(snap);
                }
            }
        }

        // 6. Upsert only new/changed snapshots
        if !new_snapshots.is_empty() {
            self.store.upsert(&new_snapshots)?;
        }

        // Signal scan complete
        if let Some(ref cb) = self.on_progress {
            cb(total, total);
        }

        // 7. Clean orphans: files in cache but no longer on disk
        let cached_paths: HashSet<String> = cache_map.keys().cloned().collect();
        let orphan_paths: Vec<&String> = cached_paths.difference(&discovered_set).collect();
        for orphan_path in &orphan_paths {
            let _ = self.store.mark_deleted(folder_id, Path::new(orphan_path));
        }

        Ok(ScanResult {
            total_files: total_discovered,
            probe_ok: new_snapshots.iter().filter(|s| s.probe_ok).count()
                + total_discovered.saturating_sub(to_probe.len()),
            probe_failed: new_snapshots.iter().filter(|s| !s.probe_ok).count(),
        })
    }
}

#[derive(Debug, Clone)]
pub struct ScanResult {
    pub total_files: usize,
    pub probe_ok: usize,
    pub probe_failed: usize,
}
