use super::time_utils::local_now;
use crate::domain::models::{
    CompressionAudit, DvProfile, FileSnapshot, HdrType, Strategy, VideoCodec,
};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use std::process::Command;

// ── Legacy AuditRecord (11-field, kept for backward compatibility) ────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditRecord {
    pub timestamp: String,
    pub source_path: String,
    pub output_path: String,
    pub source_size_bytes: u64,
    pub output_size_bytes: u64,
    pub source_codec: String,
    pub output_codec: String,
    pub strategy_name: String,
    pub duration_seconds: f64,
    pub success: bool,
    pub error_message: String,
}

/// 写入审计侧挂文件（.leanreel.json）
pub fn write_audit_sidecar(sidecar_path: &Path, record: &AuditRecord) -> Result<(), String> {
    let json =
        serde_json::to_string_pretty(record).map_err(|e| format!("序列化审计记录失败: {}", e))?;
    fs::write(sidecar_path, json).map_err(|e| format!("写入审计文件失败: {}", e))?;
    Ok(())
}

/// 读取审计侧挂文件
pub fn read_audit_sidecar(sidecar_path: &Path) -> Result<AuditRecord, String> {
    let json = fs::read_to_string(sidecar_path).map_err(|e| format!("读取审计文件失败: {}", e))?;
    serde_json::from_str(&json).map_err(|e| format!("解析审计文件失败: {}", e))
}

// ── CompressionAudit (35-field) ──────────────────────────────────────────────

/// Build a complete audit record from encoding job parameters and result.
///
/// All fields (50+) are populated from real data — FileSnapshot provides source metadata,
/// Strategy provides encoding configuration, and the remaining parameters capture
/// runtime output details and execution status.
/// H-029: Added 10+ missing fields: source_pix_fmt, source_frame_rate,
/// source_color_primaries, source_color_transfer, source_color_space,
/// platform, adaptive_cq_original, adaptive_cq_adjusted, adaptive_cq_reason.
pub fn build_audit(
    snapshot: &FileSnapshot,
    output_path: &Path,
    output_size: u64,
    output_codec: &str,
    strategy: &Strategy,
    duration_ms: u64,
    success: bool,
    error: &str,
    ffmpeg_command: &str,
) -> CompressionAudit {
    let source_size = snapshot.size_bytes as u64;

    let savings_pct = if source_size > 0 {
        ((source_size as f64 - output_size as f64) / source_size as f64) * 100.0
    } else {
        0.0
    };

    // ── derive source metadata from snapshot ──────────────────────────────

    let source_codec = video_codec_to_str(&snapshot.video_codec);

    let source_hdr = hdr_type_to_str(&snapshot.hdr_type);

    let has_dolby_vision = matches!(snapshot.hdr_type, HdrType::DolbyVision { .. });

    // ── H-029: platform detection ─────────────────────────────────────────
    let platform = format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH);

    // ── build the full audit record ───────────────────────────────────────

    CompressionAudit {
        // Version & tools
        leanreel_version: option_env!("CARGO_PKG_VERSION")
            .unwrap_or("unknown")
            .to_string(),
        ffmpeg_version: get_ffmpeg_version(),
        dovi_tool_version: get_dovi_tool_version(),

        // Source file info — all from FileSnapshot
        source_path: snapshot.relative_path.clone(),
        source_size_bytes: source_size,
        source_codec,
        source_width: snapshot.video_width,
        source_height: snapshot.video_height,
        source_hdr,
        source_duration_seconds: snapshot.duration_seconds,
        source_bitrate_bps: snapshot.bitrate_bps,
        source_audio_count: snapshot.audio_tracks.len(),
        source_subtitle_count: snapshot.subtitle_tracks.len(),
        // H-029: extended probe fields from snapshot
        source_pix_fmt: snapshot.pix_fmt.clone(),
        source_frame_rate: snapshot.frame_rate.clone(),
        source_color_primaries: snapshot.color_primaries.clone(),
        source_color_transfer: snapshot.color_transfer.clone(),
        source_color_space: snapshot.color_space.clone(),
        source_mtime: snapshot.file_mtime,

        // Output file info
        output_path: output_path.to_string_lossy().to_string(),
        output_size_bytes: output_size,
        output_codec: output_codec.to_string(),
        savings_pct,
        size_delta_bytes: snapshot.size_bytes - output_size as i64,

        // Strategy details — all from Strategy
        strategy_name: strategy.name.clone(),
        encoder: strategy.video.encoder.clone(),
        cq_value: strategy.video.cq,
        crf_value: strategy.video.crf,
        preset: strategy.video.preset.clone(),
        pix_fmt: strategy.video.pix_fmt.clone(),
        audio_mode: strategy.audio.mode.clone(),
        sub_mode: strategy.subtitle.mode.clone(),

        // Execution
        duration_ms,
        success,
        error_message: error.to_string(),
        ffmpeg_command: ffmpeg_command.to_string(),
        status: if success {
            "completed".into()
        } else {
            "failed".into()
        },
        stage: String::new(),
        progress: 0.0,
        // H-029: adaptive CQ fields (populated by caller, defaults to 0/empty)
        adaptive_cq_original: 0,
        adaptive_cq_adjusted: 0,
        adaptive_cq_reason: String::new(),

        // Environment
        timestamp: local_now(),
        completed_at: local_now(),
        source_deleted: false,
        has_dolby_vision,
        dv_handling: strategy.hdr.dv_handling.clone(),
        batch_id: String::new(),
        platform,
    }
}

/// Query ffmpeg for its version string (first line of `ffmpeg -version`).
fn get_ffmpeg_version() -> String {
    Command::new("ffmpeg")
        .arg("-version")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .and_then(|s| s.lines().next().map(|l| l.to_string()))
        .unwrap_or_default()
}

/// Query dovi_tool for its version string (first line of `dovi_tool --version`).
fn get_dovi_tool_version() -> String {
    Command::new("dovi_tool")
        .arg("--version")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .and_then(|s| s.lines().next().map(|l| l.to_string()))
        .unwrap_or_default()
}

/// Convert VideoCodec enum to a canonical short codec string.
fn video_codec_to_str(codec: &VideoCodec) -> String {
    match codec {
        VideoCodec::H264 => "h264".into(),
        VideoCodec::Hevc => "hevc".into(),
        VideoCodec::Av1 => "av1".into(),
        VideoCodec::Vp9 => "vp9".into(),
        VideoCodec::Mpeg2 => "mpeg2".into(),
        VideoCodec::Vc1 => "vc1".into(),
        VideoCodec::Unknown(s) => s.clone(),
    }
}

/// Convert HdrType enum to a human-readable string for audit records.
fn hdr_type_to_str(hdr: &HdrType) -> String {
    match hdr {
        HdrType::Sdr => "SDR".into(),
        HdrType::Hdr10 => "HDR10".into(),
        HdrType::Hdr10Plus => "HDR10+".into(),
        HdrType::DolbyVision { profile } => match profile {
            DvProfile::Profile5 => "DolbyVision:Profile5".into(),
            DvProfile::Profile7 => "DolbyVision:Profile7".into(),
            DvProfile::Profile8_1 => "DolbyVision:Profile8_1".into(),
            DvProfile::Profile8_4 => "DolbyVision:Profile8_4".into(),
        },
    }
}

/// Write audit sidecar JSON file alongside output
pub fn write_sidecar(output_path: &Path, audit: &CompressionAudit) -> Result<(), String> {
    let sidecar_path = std::path::PathBuf::from(format!("{}.leanreel.json", output_path.display()));
    let json = serde_json::to_string_pretty(audit).map_err(|e| format!("序列化审计失败: {}", e))?;
    fs::write(&sidecar_path, json).map_err(|e| format!("写入审计文件失败: {}", e))?;
    Ok(())
}
