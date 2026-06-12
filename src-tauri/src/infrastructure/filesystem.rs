use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const SUPPORTED_EXTENSIONS: &[&str] = &[
    "mkv", "mp4", "avi", "ts", "mov", "wmv", "m2ts", "mts", "webm",
];
const DISCOVERY_PROGRESS_ENTRY_INTERVAL: usize = 50;
const DISCOVERY_PROGRESS_TIME_INTERVAL: Duration = Duration::from_millis(200);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FileDiscoveryProgress {
    pub visited_entries: usize,
    pub video_files_found: usize,
}

/// Recursively find video files with supported extensions (case-insensitive).
/// Returns (files, warnings) where files is a list of (relative_path, absolute_path)
/// tuples and warnings contain permission/IO error descriptions.
pub fn find_video_files(
    root: &Path,
    on_progress: Option<&dyn Fn(FileDiscoveryProgress) -> bool>,
) -> (Vec<(String, PathBuf)>, Vec<String>) {
    if !root.exists() || !root.is_dir() {
        return (
            Vec::new(),
            vec![format!("无法访问媒体目录: {}", root.display())],
        );
    }
    let mut files = Vec::new();
    let mut warnings = Vec::new();
    let mut visited_entries = 0usize;
    let mut video_files_found = 0usize;
    let mut last_reported_entries = 0usize;
    let mut last_reported_videos = 0usize;
    let mut last_reported_at = Instant::now();
    let mut stopped = false;

    for entry in walkdir::WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_map(|e| match e {
            Ok(entry) => Some(entry),
            Err(err) => {
                // Capture IO/permission errors as warnings instead of silently skipping
                if let Some(path) = err.path() {
                    warnings.push(format!("无法访问路径 {}: {}", path.display(), err));
                } else {
                    warnings.push(format!("目录遍历错误: {}", err));
                }
                None
            }
        })
    {
        visited_entries += 1;
        let now = Instant::now();
        if let Some(cb) = on_progress {
            let first_entry = visited_entries == 1;
            let enough_entries = visited_entries.saturating_sub(last_reported_entries)
                >= DISCOVERY_PROGRESS_ENTRY_INTERVAL;
            let enough_time =
                now.duration_since(last_reported_at) >= DISCOVERY_PROGRESS_TIME_INTERVAL;
            if first_entry || enough_entries || enough_time {
                last_reported_entries = visited_entries;
                last_reported_videos = video_files_found;
                last_reported_at = now;
                if !cb(FileDiscoveryProgress {
                    visited_entries,
                    video_files_found,
                }) {
                    stopped = true;
                    break;
                }
            }
        }

        if !entry.file_type().is_file() {
            continue;
        }
        if let Some(ext) = entry.path().extension().and_then(|e| e.to_str()) {
            if SUPPORTED_EXTENSIONS.contains(&ext.to_lowercase().as_str()) {
                let abs = entry.path().to_path_buf();
                let rel = abs
                    .strip_prefix(root)
                    .unwrap_or(&abs)
                    .to_string_lossy()
                    .to_string()
                    .replace('\\', "/");
                files.push((rel, abs));
                video_files_found += 1;
            }
        }
    }

    if !stopped {
        if let Some(cb) = on_progress {
            let should_report_final = visited_entries != last_reported_entries
                || video_files_found != last_reported_videos;
            if should_report_final {
                let _ = cb(FileDiscoveryProgress {
                    visited_entries,
                    video_files_found,
                });
            }
        }
    }

    (files, warnings)
}
