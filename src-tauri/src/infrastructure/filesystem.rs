use std::path::{Path, PathBuf};

const SUPPORTED_EXTENSIONS: &[&str] = &[
    "mkv", "mp4", "avi", "ts", "mov", "wmv", "m2ts", "mts", "webm",
];

/// Recursively find video files with supported extensions (case-insensitive).
/// Returns (files, warnings) where files is a list of (relative_path, absolute_path)
/// tuples and warnings contain permission/IO error descriptions.
pub fn find_video_files(root: &Path) -> (Vec<(String, PathBuf)>, Vec<String>) {
    if !root.exists() || !root.is_dir() {
        return (
            Vec::new(),
            vec![format!("无法访问媒体目录: {}", root.display())],
        );
    }
    let mut files = Vec::new();
    let mut warnings = Vec::new();
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
            }
        }
    }
    (files, warnings)
}
