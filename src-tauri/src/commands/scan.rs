use crate::domain::traits::SnapshotStore;
use crate::services::matcher::StrategyMatcher;
use crate::AppState;
use serde::Serialize;
use tauri::State;

#[derive(Debug, Clone, Serialize)]
pub struct FileEntry {
    pub key: String,
    pub folder_id: i64,
    pub path: String,
    pub name: String,
    pub size: u64,
    pub codec: String,
    pub hdr: String,
    pub size_display: String,
    pub width: i32,
    pub height: i32,
    pub bitrate_bps: i64,
    /// Status key for frontend filtering: "processable" | "protected" |
    /// "probe_failed" | "pending" | "unmatched"
    pub decision_status: String,
    /// Human-readable decision: "可处理: 平衡 HEVC 节省 1.2-2.4 GB (45-55%)"
    pub decision_text: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ScanCommandResult {
    pub total_files: usize,
    pub probe_ok: usize,
    pub probe_failed: usize,
    pub files: Vec<FileEntry>,
}

/// Resolve folder_id for scanning.  When the frontend passes folder_id=0
/// (manual toolbar scan), auto-create a default library + folder so the
/// foreign-key constraint on file_snapshot.library_folder_id is satisfied.
fn resolve_folder_id(
    store: &std::sync::MutexGuard<crate::infrastructure::db::SqliteSnapshotStore>,
    path: &str,
    folder_id: i64,
) -> Result<i64, String> {
    if folder_id > 0 {
        // Verify the folder exists
        if store.get_folder_path_by_id(folder_id).is_ok() {
            return Ok(folder_id);
        }
    }
    // folder_id == 0 or invalid → find or create a default library + folder
    let libs = store.get_libraries()?;
    let default_lib = if let Some(lib) = libs.iter().find(|l| l.name == "默认") {
        lib.id
    } else {
        store.create_library("默认")?
    };
    // Check if path already exists as a folder in this library
    let existing = store.get_folders(default_lib)?;
    if let Some(folder) = existing.iter().find(|f| f.path == path) {
        return Ok(folder.id);
    }
    store.add_folder(default_lib, path)
}

/// Query cached files across all folders in a library (or all files if library_id=0).
#[tauri::command]
pub fn get_library_files(
    library_id: i64,
    state: State<AppState>,
) -> Result<ScanCommandResult, String> {
    let filter = crate::domain::models::FileFilter {
        library_id: if library_id > 0 {
            Some(library_id)
        } else {
            None
        },
        folder_id: None,
        probe_ok_only: None,
    };
    let snapshots = state
        .store
        .lock()
        .map_err(|_| "store lock failed".to_string())?
        .query(&filter)?;
    let matcher = state
        .matcher
        .lock()
        .map_err(|_| "matcher lock failed".to_string())?;
    Ok(build_result(&snapshots, &matcher))
}

/// Query cached file list for a folder — no scanning, instant.
#[tauri::command]
pub fn get_folder_files(
    folder_id: i64,
    state: State<AppState>,
) -> Result<ScanCommandResult, String> {
    let filter = crate::domain::models::FileFilter {
        library_id: None,
        folder_id: Some(folder_id),
        probe_ok_only: None,
    };
    let snapshots = state
        .store
        .lock()
        .map_err(|_| "store lock failed".to_string())?
        .query(&filter)?;
    let matcher = state
        .matcher
        .lock()
        .map_err(|_| "matcher lock failed".to_string())?;
    Ok(build_result(&snapshots, &matcher))
}

#[tauri::command]
pub async fn scan_directory(
    path: String,
    folder_id: i64,
    state: State<'_, AppState>,
) -> Result<ScanCommandResult, String> {
    let store = state.store.clone();
    let scanner = state.scanner.clone();
    let matcher = state.matcher.clone();

    tauri::async_runtime::spawn_blocking(move || {
        let actual_folder_id = {
            let store = store.lock().map_err(|_| "store lock failed".to_string())?;
            resolve_folder_id(&store, &path, folder_id)?
        };

        let scanner = scanner.lock().map_err(|e| format!("锁获取失败: {}", e))?;
        scanner.scan_directory(std::path::Path::new(&path), actual_folder_id)?;
        drop(scanner);

        let filter = crate::domain::models::FileFilter {
            library_id: None,
            folder_id: Some(actual_folder_id),
            probe_ok_only: None,
        };
        let snapshots = store
            .lock()
            .map_err(|_| "store lock failed".to_string())?
            .query(&filter)?;
        let matcher = matcher
            .lock()
            .map_err(|_| "matcher lock failed".to_string())?;
        Ok(build_result(&snapshots, &matcher))
    })
    .await
    .map_err(|e| format!("扫描任务执行失败: {}", e))?
}

fn build_result(
    snapshots: &[crate::domain::models::FileSnapshot],
    matcher: &StrategyMatcher,
) -> ScanCommandResult {
    let files: Vec<FileEntry> = snapshots.iter().map(|s| build_entry(s, matcher)).collect();

    let total = files.len();
    let ok = snapshots.iter().filter(|s| s.probe_ok).count();
    ScanCommandResult {
        total_files: total,
        probe_ok: ok,
        probe_failed: total - ok,
        files,
    }
}

pub fn build_entry(
    s: &crate::domain::models::FileSnapshot,
    matcher: &StrategyMatcher,
) -> FileEntry {
    let codec = format_codec(s);
    let hdr = format_hdr(&s.hdr_type);
    let size_display = if s.size_bytes >= 1_000_000_000 {
        format!("{:.1} GB", s.size_bytes as f64 / 1_000_000_000.0)
    } else if s.size_bytes >= 1_000_000 {
        format!("{:.1} MB", s.size_bytes as f64 / 1_000_000.0)
    } else if s.size_bytes >= 1_000 {
        format!("{:.1} KB", s.size_bytes as f64 / 1_000.0)
    } else {
        format!("{} B", s.size_bytes)
    };
    let (decision_status, decision_text) = compute_decision(s, matcher);
    FileEntry {
        key: format!("{}:{}", s.library_folder_id, s.relative_path),
        folder_id: s.library_folder_id,
        path: s.relative_path.clone(),
        name: s.file_name.clone(),
        size: s.size_bytes as u64,
        codec,
        hdr,
        size_display,
        width: s.video_width,
        height: s.video_height,
        bitrate_bps: s.bitrate_bps,
        decision_status,
        decision_text,
    }
}

fn format_codec(s: &crate::domain::models::FileSnapshot) -> String {
    // Probe pending
    if !s.probe_ok && s.video_codec.is_empty_or_unknown() && s.probe_error.is_empty() {
        return "探测中...".into();
    }
    // Probe failed
    if !s.probe_ok && s.video_codec.is_empty_or_unknown() && !s.probe_error.is_empty() {
        return "探测失败".into();
    }
    // Unrecognized
    if s.video_codec.is_empty_or_unknown() {
        return "未识别".into();
    }

    let codec_str = match &s.video_codec {
        crate::domain::models::VideoCodec::H264 => "H.264",
        crate::domain::models::VideoCodec::Hevc => "HEVC",
        crate::domain::models::VideoCodec::Av1 => "AV1",
        crate::domain::models::VideoCodec::Vp9 => "VP9",
        crate::domain::models::VideoCodec::Mpeg2 => "MPEG-2",
        crate::domain::models::VideoCodec::Vc1 => "VC-1",
        crate::domain::models::VideoCodec::Unknown(s) => s.as_str(),
    };

    codec_str.to_string()
}

fn compute_decision(
    s: &crate::domain::models::FileSnapshot,
    matcher: &StrategyMatcher,
) -> (String, String) {
    // Pending probe
    if !s.probe_ok && s.video_codec.is_empty_or_unknown() && s.probe_error.is_empty() {
        return ("pending".into(), "探测中...".into());
    }
    // Probe failed
    if !s.probe_ok && s.video_codec.is_empty_or_unknown() && !s.probe_error.is_empty() {
        return (
            "probe_failed".into(),
            format!("探测失败: {}", s.probe_error),
        );
    }

    // Protected source: run matcher
    let m = matcher.match_for(s);
    match m {
        crate::domain::models::StrategyResult::SkipProtected { reason } => {
            ("protected".into(), reason.display().to_string())
        }
        crate::domain::models::StrategyResult::SkipNoMatch { .. } => {
            ("unmatched".into(), "无匹配策略".into())
        }
        crate::domain::models::StrategyResult::Encode {
            strategy_name,
            estimated_saving,
        } => {
            let text = format!(
                "可处理: {} 节省 {:.1}-{:.1} GB",
                strategy_name,
                estimated_saving.estimated_min_bytes as f64 / 1_000_000_000.0,
                estimated_saving.estimated_max_bytes as f64 / 1_000_000_000.0,
            );
            let full = format!("{} ({})", text, estimated_saving.percentage);
            ("processable".into(), full)
        }
    }
}

fn format_hdr(hdr: &crate::domain::models::HdrType) -> String {
    match hdr {
        crate::domain::models::HdrType::Sdr => "SDR".into(),
        crate::domain::models::HdrType::Hdr10 => "HDR10".into(),
        crate::domain::models::HdrType::Hdr10Plus => "HDR10+".into(),
        crate::domain::models::HdrType::DolbyVision { profile } => {
            format!("Dolby Vision ({:?})", profile)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::future::Future;

    fn assert_async_scan_command<Fut>(_command: fn(String, i64, State<'static, AppState>) -> Fut)
    where
        Fut: Future<Output = Result<ScanCommandResult, String>>,
    {
    }

    #[test]
    fn scan_directory_command_is_async() {
        assert_async_scan_command(scan_directory);
    }
}
