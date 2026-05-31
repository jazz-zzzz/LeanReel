use crate::domain::models::*;
use crate::domain::traits::MediaProber;
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};

/// Parse FFprobe JSON output into VideoMetadata.
pub fn parse_ffprobe_output(json: &str) -> Result<VideoMetadata, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("无效 JSON: {}", e))?;

    let streams = root["streams"].as_array().ok_or("缺少 streams 数组")?;

    let video = streams
        .iter()
        .find(|s| s["codec_type"].as_str() == Some("video"))
        .ok_or("未找到视频流")?;

    let codec_str = video["codec_name"].as_str().unwrap_or("unknown");
    let codec = VideoCodec::from_codec(codec_str);

    let width = video["width"].as_i64().unwrap_or(0) as i32;
    let height = video["height"].as_i64().unwrap_or(0) as i32;

    let hdr_type = detect_hdr(video);

    // Duration and bitrate from format level (matching Python)
    let duration: f64 = root["format"]["duration"]
        .as_str()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0.0);

    // NaN/Inf guard matching Python
    let duration = if duration.is_finite() { duration } else { 0.0 };

    let bitrate: i64 = root["format"]["bit_rate"]
        .as_str()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let bitrate = if bitrate >= 0 { bitrate } else { 0 };

    let audio_tracks: Vec<AudioTrack> = streams
        .iter()
        .filter(|s| s["codec_type"].as_str() == Some("audio"))
        .map(|s| AudioTrack {
            codec: s["codec_name"].as_str().unwrap_or("").to_string(),
            channels: s["channels"].as_i64().unwrap_or(0) as i32,
            language: s["tags"]["language"].as_str().unwrap_or("und").to_string(),
            title: s["tags"]["title"].as_str().unwrap_or("").to_string(),
            is_commentary: s["disposition"]["comment"].as_i64().unwrap_or(0) != 0,
        })
        .collect();

    let subtitle_tracks: Vec<SubtitleTrack> = streams
        .iter()
        .filter(|s| s["codec_type"].as_str() == Some("subtitle"))
        .map(|s| SubtitleTrack {
            codec: s["codec_name"].as_str().unwrap_or("").to_string(),
            language: s["tags"]["language"].as_str().unwrap_or("und").to_string(),
            title: s["tags"]["title"].as_str().unwrap_or("").to_string(),
            is_forced: s["disposition"]["forced"].as_i64().unwrap_or(0) != 0,
        })
        .collect();

    let pix_fmt = video["pix_fmt"].as_str().unwrap_or("").to_string();
    let frame_rate = video["r_frame_rate"].as_str().unwrap_or("").to_string();
    let color_primaries = video["color_primaries"].as_str().unwrap_or("").to_string();
    let color_transfer = video["color_transfer"].as_str().unwrap_or("").to_string();
    let color_space = video["color_space"].as_str().unwrap_or("").to_string();

    Ok(VideoMetadata {
        codec,
        width,
        height,
        hdr_type,
        audio_tracks,
        subtitle_tracks,
        duration_seconds: duration,
        bitrate_bps: bitrate,
        pix_fmt,
        frame_rate,
        color_primaries,
        color_transfer,
        color_space,
    })
}

fn detect_hdr(video: &Value) -> HdrType {
    // Detect Dolby Vision via side_data_type starting with "Dolby Vision" (matching Python)
    let has_dv = video["side_data_list"]
        .as_array()
        .map(|sides| {
            sides.iter().any(|s| {
                s["side_data_type"]
                    .as_str()
                    .map(|t| t.starts_with("Dolby Vision"))
                    .unwrap_or(false)
            })
        })
        .unwrap_or(false);

    if has_dv {
        let profile = video["side_data_list"]
            .as_array()
            .and_then(|sides| {
                sides.iter().find_map(|s| {
                    if s["side_data_type"].as_str()?.starts_with("Dolby Vision") {
                        Some(s["dv_profile"].as_i64().unwrap_or(7))
                    } else {
                        None
                    }
                })
            })
            .unwrap_or(7);

        let dv_profile = match profile {
            5 => DvProfile::Profile5,
            7 => DvProfile::Profile7,
            8 => DvProfile::Profile8_1, // Could be 8.1 or 8.4
            _ => DvProfile::Profile8_1,
        };
        return HdrType::DolbyVision {
            profile: dv_profile,
        };
    }

    let color_transfer = video["color_transfer"].as_str().unwrap_or("");
    let color_primaries = video["color_primaries"].as_str().unwrap_or("");

    // HDR10/HDR10+: must be BOTH smpte2084 AND bt2020 (matching Python)
    if color_transfer == "smpte2084" && color_primaries == "bt2020" {
        let has_hdr10plus = video["side_data_list"]
            .as_array()
            .map(|sides| {
                sides.iter().any(|s| {
                    s["side_data_type"]
                        .as_str()
                        .map(|t| t == "HDR Dynamic Metadata")
                        .unwrap_or(false)
                })
            })
            .unwrap_or(false);

        if has_hdr10plus {
            return HdrType::Hdr10Plus;
        }
        return HdrType::Hdr10;
    }

    // Codec tag fallback: dvhe/dvh1/dav1 indicate Dolby Vision (matching Python)
    let codec_tag = video["codec_tag_string"]
        .as_str()
        .unwrap_or("")
        .to_lowercase();
    if !codec_tag.is_empty() {
        let is_dv_tag =
            codec_tag.contains("dvh") || codec_tag.contains("dvhe") || codec_tag.contains("dav1");
        if is_dv_tag {
            return HdrType::DolbyVision {
                profile: DvProfile::Profile8_1,
            };
        }
    }

    // Python fallback: 10-bit HEVC without explicit color metadata is likely HDR
    let pix_fmt = video["pix_fmt"].as_str().unwrap_or("");
    let profile_str = video["profile"].as_str().unwrap_or("");
    let codec_name = video["codec_name"].as_str().unwrap_or("");
    if (profile_str.contains("10") || pix_fmt.contains("10"))
        && (codec_name == "hevc" || codec_name == "h265")
    {
        if color_transfer.is_empty() && color_primaries.is_empty() {
            return HdrType::Hdr10;
        }
    }

    HdrType::Sdr
}

#[derive(Clone)]
pub struct FfprobeRunner {
    ffprobe_path: Arc<Mutex<PathBuf>>,
}

impl FfprobeRunner {
    /// Reload from config — called after user changes settings at runtime
    pub fn load_from_config(&self, store: &crate::infrastructure::db::SqliteSnapshotStore) {
        if let Some(p) = store.get_config("ffprobe_path") {
            let path = PathBuf::from(&p);
            if path.exists() {
                *self.ffprobe_path.lock().unwrap() = path;
            }
        }
    }

    pub fn new(path: Option<PathBuf>) -> Self {
        let ffprobe_path = path.unwrap_or_else(|| {
            if let Ok(p) = std::env::var("FFPROBE_PATH") {
                return PathBuf::from(p);
            }
            let exe_dir = std::env::current_exe()
                .ok()
                .and_then(|p| p.parent().map(|d| d.to_path_buf()))
                .unwrap_or_default();

            // Check bundled next to exe, then walk up to find resources/ffmpeg/
            let mut search = exe_dir.clone();
            for _ in 0..5 {
                let candidate = search.join("ffprobe.exe");
                if candidate.exists() {
                    return candidate;
                }
                let candidate2 = search.join("resources").join("ffmpeg").join("ffprobe.exe");
                if candidate2.exists() {
                    return candidate2;
                }
                let candidate3 = search
                    .join("leanreel")
                    .join("resources")
                    .join("ffmpeg")
                    .join("ffprobe.exe");
                if candidate3.exists() {
                    return candidate3;
                }
                match search.parent() {
                    Some(p) => search = p.to_path_buf(),
                    None => break,
                }
            }
            PathBuf::from("ffprobe")
        });
        Self {
            ffprobe_path: Arc::new(Mutex::new(ffprobe_path)),
        }
    }

    pub fn has_ffprobe(&self) -> Result<PathBuf, String> {
        let path = self.ffprobe_path.lock().unwrap().clone();
        if path.is_absolute() && path.exists() {
            return Ok(path);
        }
        which::which(&path).map_err(|e| format!("ffprobe 未找到: {}", e))
    }

    fn run_probe(&self, path: &Path) -> Result<String, String> {
        let ffprobe = self.has_ffprobe()?;

        // First attempt: with -show_side_data (needed for Dolby Vision detection)
        let result = self.try_probe_with_flags(&ffprobe, path, true);
        if result.is_ok() {
            return result;
        }

        // Fallback: without -show_side_data (older ffprobe versions may not support it)
        self.try_probe_with_flags(&ffprobe, path, false)
    }

    fn try_probe_with_flags(
        &self,
        ffprobe: &Path,
        path: &Path,
        with_side_data: bool,
    ) -> Result<String, String> {
        use std::sync::mpsc;
        use std::time::Duration;

        let mut cmd = Command::new(ffprobe);
        cmd.args([
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
        ]);
        if with_side_data {
            cmd.arg("-show_side_data");
        }
        cmd.args(["-probesize", "2M", "-analyzeduration", "500000"]);
        cmd.arg(path);

        // Spawn with timeout (matching Python's timeout=30)
        // Use spawn + channel with recv_timeout instead of wait_timeout (not stable)
        let child = cmd
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|e| format!("启动 ffprobe 失败: {}", e))?;

        let child_id = child.id();
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            tx.send(child.wait_with_output()).ok();
        });

        match rx.recv_timeout(Duration::from_secs(30)) {
            Ok(Ok(output)) => {
                if !output.status.success() {
                    return Err("ffprobe 执行异常".to_string());
                }
                String::from_utf8(output.stdout).map_err(|e| format!("无效 UTF-8 编码: {}", e))
            }
            Ok(Err(e)) => Err(format!("ffprobe 进程异常: {}", e)),
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // Kill the orphan ffprobe process on timeout
                let _ = std::process::Command::new("taskkill")
                    .args(["/F", "/PID", &child_id.to_string()])
                    .output();
                Err("ffprobe 超时（30秒）".to_string())
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => Err("ffprobe 进程异常终止".to_string()),
        }
    }

    /// Probe a file with retry logic (matching Python max_attempts=2).
    fn probe_with_retry(&self, path: &Path) -> Result<VideoMetadata, String> {
        let mut last_err = String::new();
        for attempt in 1..=2 {
            match self.probe(path) {
                Ok(meta) => return Ok(meta),
                Err(e) => {
                    last_err = e;
                    if attempt < 2 {
                        std::thread::sleep(std::time::Duration::from_millis(100));
                    }
                }
            }
        }
        Err(last_err)
    }
}

impl MediaProber for FfprobeRunner {
    fn probe(&self, path: &Path) -> Result<crate::domain::models::VideoMetadata, String> {
        let json = self.run_probe(path)?;
        parse_ffprobe_output(&json)
    }

    fn probe_batch(&self, paths: &[PathBuf]) -> Result<Vec<ProbeResult>, String> {
        if paths.is_empty() {
            return Ok(Vec::new());
        }

        // Match Python's default 4 workers in ProbeBatch ThreadPoolExecutor
        let num_workers = 4.min(paths.len());
        let chunk_size = (paths.len() + num_workers - 1) / num_workers;

        let results: Arc<Mutex<Vec<ProbeResult>>> =
            Arc::new(Mutex::new(Vec::with_capacity(paths.len())));
        let mut handles = Vec::with_capacity(num_workers);

        for chunk in paths.chunks(chunk_size) {
            let chunk_paths: Vec<PathBuf> = chunk.to_vec();
            let results = Arc::clone(&results);
            let ffprobe_path = Arc::clone(&self.ffprobe_path);

            let handle = std::thread::spawn(move || {
                let runner = FfprobeRunner { ffprobe_path };
                for path in &chunk_paths {
                    let metadata = runner.probe_with_retry(path);
                    results.lock().unwrap().push(ProbeResult {
                        path: path.clone(),
                        metadata,
                    });
                }
            });
            handles.push(handle);
        }

        for handle in handles {
            handle.join().map_err(|_| "探测线程异常终止".to_string())?;
        }

        let mut results = Arc::try_unwrap(results)
            .map_err(|_| "无法释放共享结果".to_string())?
            .into_inner()
            .unwrap();

        // Sort results to preserve input order (important for scanner)
        results.sort_by(|a, b| {
            paths
                .iter()
                .position(|p| p == &a.path)
                .cmp(&paths.iter().position(|p| p == &b.path))
        });

        Ok(results)
    }
}
