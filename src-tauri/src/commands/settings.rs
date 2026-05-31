use crate::AppState;
use serde::Serialize;
use tauri::State;

#[derive(Debug, Clone, Serialize)]
pub struct AppSettings {
    pub ffprobe_custom: String,
    pub ffmpeg_custom: String,
    pub ffprobe_path: String,
    pub ffmpeg_path: String,
    pub ffprobe_ok: bool,
    pub ffmpeg_ok: bool,
    pub gpu_ok: bool,
    pub gpu_info: String,
}

#[tauri::command]
pub fn get_settings(state: State<AppState>) -> Result<AppSettings, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;
    let ffprobe_custom = store.get_config("ffprobe_path").unwrap_or_default();
    let ffmpeg_custom = store.get_config("ffmpeg_path").unwrap_or_default();

    let ffprobe_path = state
        .prober
        .has_ffprobe()
        .ok()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default();
    let ffmpeg_path = state
        .ffmpeg
        .has_ffmpeg()
        .ok()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default();
    let ffprobe_ok = !ffprobe_path.is_empty();
    let ffmpeg_ok = !ffmpeg_path.is_empty();

    let gpu_info = if ffmpeg_ok {
        let path = std::path::PathBuf::from(&ffmpeg_path);
        std::process::Command::new(&path)
            .args(["-hide_banner", "-encoders"])
            .output()
            .ok()
            .and_then(|out| {
                let s = String::from_utf8_lossy(&out.stdout);
                if s.contains("hevc_nvenc") {
                    Some("NVIDIA NVENC".to_string())
                } else {
                    None
                }
            })
            .unwrap_or_default()
    } else {
        String::new()
    };
    let gpu_ok = !gpu_info.is_empty();

    Ok(AppSettings {
        ffprobe_custom,
        ffmpeg_custom,
        ffprobe_path,
        ffmpeg_path,
        ffprobe_ok,
        ffmpeg_ok,
        gpu_ok,
        gpu_info,
    })
}

#[tauri::command]
pub fn test_tool(path: String) -> Result<bool, String> {
    let p = std::path::PathBuf::from(&path);
    Ok(p.is_file())
}

#[tauri::command]
pub fn save_settings(
    ffprobe_path: Option<String>,
    ffmpeg_path: Option<String>,
    state: State<AppState>,
) -> Result<AppSettings, String> {
    let store = state.store.lock().map_err(|_| "lock failed".to_string())?;

    if let Some(ref p) = ffprobe_path {
        let trimmed = p.trim();
        if !trimmed.is_empty() {
            store.set_config("ffprobe_path", trimmed)?;
            state.prober.load_from_config(&store);
        }
    }
    if let Some(ref p) = ffmpeg_path {
        let trimmed = p.trim();
        if !trimmed.is_empty() {
            store.set_config("ffmpeg_path", trimmed)?;
            state.ffmpeg.load_from_config(&store);
        }
    }
    drop(store);
    get_settings(state)
}
