use leanreel_rs_lib::domain::models::{
    AudioConfig, AudioTrack, DvProfile, FileSnapshot, HdrConfig, HdrType, Strategy, SubtitleConfig,
    SubtitleTrack, VideoCodec, VideoConfig,
};
use leanreel_rs_lib::services::audit::*;
use std::path::Path;

// ── Legacy AuditRecord tests ──────────────────────────────────────────────────

#[test]
fn test_write_and_read_sidecar() {
    let tmp = std::env::temp_dir().join("test_audit_sidecar_output.leanreel.json");
    let _ = std::fs::remove_file(&tmp);

    let record = AuditRecord {
        timestamp: "2026-05-30T12:00:00".into(),
        source_path: "/movies/test.mkv".into(),
        output_path: "/movies/test_compressed.mkv".into(),
        source_size_bytes: 2_000_000_000,
        output_size_bytes: 800_000_000,
        source_codec: "h264".into(),
        output_codec: "av1".into(),
        strategy_name: "AV1 CQ28".into(),
        duration_seconds: 120.5,
        success: true,
        error_message: String::new(),
    };

    write_audit_sidecar(&tmp, &record).unwrap();
    let restored = read_audit_sidecar(&tmp).unwrap();
    let _ = std::fs::remove_file(&tmp);

    assert_eq!(restored.source_path, record.source_path);
    assert_eq!(restored.strategy_name, record.strategy_name);
    assert_eq!(restored.success, true);
}

#[test]
fn test_sidecar_writes_json_file() {
    let tmp = std::env::temp_dir().join("test_sidecar_exists.leanreel.json");
    let _ = std::fs::remove_file(&tmp);

    let record = AuditRecord {
        timestamp: "2026-05-30".into(),
        source_path: "a.mkv".into(),
        output_path: "b.mkv".into(),
        source_size_bytes: 100,
        output_size_bytes: 50,
        source_codec: "h264".into(),
        output_codec: "av1".into(),
        strategy_name: "test".into(),
        duration_seconds: 1.0,
        success: true,
        error_message: String::new(),
    };
    write_audit_sidecar(&tmp, &record).unwrap();
    assert!(tmp.exists());
    let content = std::fs::read_to_string(&tmp).unwrap();
    assert!(content.contains("a.mkv"));
    let _ = std::fs::remove_file(&tmp);
}

#[test]
fn test_read_nonexistent_sidecar() {
    let result = read_audit_sidecar(Path::new("definitely_not_a_file.json"));
    assert!(result.is_err());
}

// ── Helpers for building test fixtures ────────────────────────────────────────

fn make_snapshot(
    path: &str,
    size: i64,
    codec: &str,
    width: i32,
    height: i32,
    hdr: HdrType,
    duration: f64,
    bitrate: i64,
    audio: Vec<AudioTrack>,
    subs: Vec<SubtitleTrack>,
) -> FileSnapshot {
    FileSnapshot {
        relative_path: path.to_string(),
        size_bytes: size,
        video_codec: VideoCodec::from_codec(codec),
        video_width: width,
        video_height: height,
        hdr_type: hdr,
        duration_seconds: duration,
        bitrate_bps: bitrate,
        audio_tracks: audio,
        subtitle_tracks: subs,
        ..Default::default()
    }
}

fn make_strategy(
    name: &str,
    encoder: &str,
    cq: i32,
    crf: i32,
    preset: &str,
    pix_fmt: &str,
    audio_mode: &str,
    sub_mode: &str,
    dv_handling: &str,
) -> Strategy {
    Strategy {
        name: name.to_string(),
        video: VideoConfig {
            encoder: encoder.to_string(),
            cq,
            crf,
            preset: preset.to_string(),
            pix_fmt: pix_fmt.to_string(),
            ..Default::default()
        },
        audio: AudioConfig {
            mode: audio_mode.to_string(),
            ..Default::default()
        },
        subtitle: SubtitleConfig {
            mode: sub_mode.to_string(),
        },
        hdr: HdrConfig {
            dv_handling: dv_handling.to_string(),
            ..Default::default()
        },
        ..Default::default()
    }
}

// ── CompressionAudit (build_audit + write_sidecar) tests ─────────────────────

#[test]
fn test_build_audit_success() {
    let snapshot = make_snapshot(
        "/movies/test.mkv",
        2_000_000_000,
        "h264",
        1920,
        1080,
        HdrType::Sdr,
        3600.0,
        4_000_000,
        vec![AudioTrack {
            codec: "aac".into(),
            channels: 6,
            language: "eng".into(),
            title: "Surround".into(),
            is_commentary: false,
        }],
        vec![SubtitleTrack {
            codec: "srt".into(),
            language: "eng".into(),
            title: "English".into(),
            is_forced: false,
        }],
    );
    let strategy = make_strategy(
        "AV1 NVENC CQ28",
        "av1_nvenc",
        28,
        0,
        "p7",
        "p010le",
        "copy_all",
        "keep_all",
        "passthrough",
    );

    let audit = build_audit(
        &snapshot,
        Path::new("/movies/test_leanreel.mkv"),
        800_000_000,
        "av1",
        &strategy,
        120_000,
        true,
        "",
        "ffmpeg -i test.mkv -c:v av1_nvenc -cq 28 -preset p7 out.mkv",
    );

    // legacy assertions
    assert_eq!(audit.strategy_name, "AV1 NVENC CQ28");
    assert_eq!(audit.encoder, "av1_nvenc");
    assert_eq!(audit.cq_value, 28);
    assert!(audit.success);
    assert!(audit.error_message.is_empty());
    assert!(audit.savings_pct > 0.0);
    assert_eq!(audit.size_delta_bytes, 1_200_000_000);
    assert_eq!(audit.status, "completed");

    // C8 fix assertions — verify fields now populated from snapshot/strategy
    assert_eq!(audit.source_width, 1920);
    assert_eq!(audit.source_height, 1080);
    assert_eq!(audit.source_hdr, "SDR");
    assert!(audit.source_duration_seconds > 0.0);
    assert!(audit.source_bitrate_bps > 0);
    assert_eq!(audit.source_audio_count, 1);
    assert_eq!(audit.source_subtitle_count, 1);
    assert_eq!(audit.preset, "p7");
    assert_eq!(audit.pix_fmt, "p010le");
    assert_eq!(audit.audio_mode, "copy_all");
    assert_eq!(audit.sub_mode, "keep_all");
    assert!(!audit.has_dolby_vision);
    assert_eq!(audit.dv_handling, "passthrough");
    assert!(!audit.ffmpeg_command.is_empty());
    assert!(audit.ffmpeg_command.contains("av1_nvenc"));
    assert_eq!(audit.crf_value, 0);
}

#[test]
fn test_build_audit_failure() {
    let snapshot = make_snapshot(
        "/movies/bad.mkv",
        1_000_000_000,
        "h264",
        3840,
        2160,
        HdrType::Hdr10,
        5400.0,
        1_500_000,
        vec![],
        vec![],
    );
    let strategy = make_strategy(
        "HEVC CRF22",
        "libx265",
        0,
        22,
        "medium",
        "yuv420p10le",
        "copy_all",
        "no_subs",
        "strip_dv",
    );

    let audit = build_audit(
        &snapshot,
        Path::new("/movies/bad_leanreel.mkv"),
        0,
        "",
        &strategy,
        5000,
        false,
        "ffmpeg crashed",
        "ffmpeg -i bad.mkv -c:v libx265 -crf 22 out.mkv",
    );

    assert!(!audit.success);
    assert_eq!(audit.error_message, "ffmpeg crashed");
    assert_eq!(audit.status, "failed");

    // C8: verify hdr is populated even on failure
    assert_eq!(audit.source_hdr, "HDR10");
    assert_eq!(audit.source_width, 3840);
    assert_eq!(audit.source_height, 2160);
    assert_eq!(audit.source_audio_count, 0);
    assert!(!audit.has_dolby_vision);
    assert_eq!(audit.crf_value, 22);
}

#[test]
fn test_build_audit_with_dolby_vision() {
    let snapshot = make_snapshot(
        "/movies/dv.mkv",
        5_000_000_000,
        "hevc",
        3840,
        2160,
        HdrType::DolbyVision {
            profile: DvProfile::Profile5,
        },
        7200.0,
        5_500_000,
        vec![
            AudioTrack {
                codec: "eac3".into(),
                channels: 8,
                language: "eng".into(),
                title: "Atmos".into(),
                is_commentary: false,
            },
            AudioTrack {
                codec: "eac3".into(),
                channels: 2,
                language: "eng".into(),
                title: "Commentary".into(),
                is_commentary: true,
            },
        ],
        vec![
            SubtitleTrack {
                codec: "pgssub".into(),
                language: "eng".into(),
                title: "English".into(),
                is_forced: false,
            },
            SubtitleTrack {
                codec: "pgssub".into(),
                language: "chi".into(),
                title: "Chinese".into(),
                is_forced: false,
            },
        ],
    );
    let strategy = make_strategy(
        "AV1 DV Passthrough",
        "av1_nvenc",
        30,
        0,
        "p7",
        "p010le",
        "copy_all",
        "keep_all",
        "passthrough",
    );

    let audit = build_audit(
        &snapshot,
        Path::new("/movies/dv_leanreel.mkv"),
        2_000_000_000,
        "av1",
        &strategy,
        300_000,
        true,
        "",
        "ffmpeg -i dv.mkv -c:v av1_nvenc -cq 30 -preset p7 out.mkv",
    );

    // C8: Dolby Vision specific assertions
    assert!(audit.has_dolby_vision);
    assert!(audit.source_hdr.contains("DolbyVision"));
    assert_eq!(audit.dv_handling, "passthrough");
    assert_eq!(audit.source_audio_count, 2);
    assert_eq!(audit.source_subtitle_count, 2);
    assert_eq!(audit.source_codec, "hevc");
}

#[test]
fn test_sidecar_roundtrip_with_full_audit() {
    let out_path = std::env::temp_dir().join("test_full_audit_output.mkv");
    let sidecar_path = std::env::temp_dir().join("test_full_audit_output.mkv.leanreel.json");
    let _ = std::fs::remove_file(&sidecar_path);

    let snapshot = make_snapshot(
        "/src.mkv",
        2_000_000_000,
        "h264",
        1920,
        1080,
        HdrType::Sdr,
        3600.0,
        4_000_000,
        vec![],
        vec![],
    );
    let strategy = make_strategy(
        "AV1 CQ28",
        "av1_nvenc",
        28,
        0,
        "p7",
        "p010le",
        "copy_all",
        "keep_all",
        "",
    );

    let audit = build_audit(
        &snapshot,
        Path::new("/out.mkv"),
        800_000_000,
        "av1",
        &strategy,
        100_000,
        true,
        "",
        "ffmpeg -i src.mkv -c:v av1_nvenc -cq 28 out.mkv",
    );

    write_sidecar(&out_path, &audit).unwrap();
    assert!(sidecar_path.exists());
    let content = std::fs::read_to_string(&sidecar_path).unwrap();
    assert!(content.contains("av1_nvenc"));
    assert!(content.contains("AV1 CQ28"));
    // C8: verify new fields are serialized into the sidecar
    assert!(content.contains("source_width"));
    assert!(content.contains("1920"));
    assert!(content.contains("pix_fmt"));
    assert!(content.contains("p010le"));
    assert!(content.contains("has_dolby_vision"));
    let _ = std::fs::remove_file(&sidecar_path);
}

#[test]
fn test_build_audit_zero_size_source() {
    // Edge case: empty source file should not cause division by zero
    let snapshot = make_snapshot(
        "/movies/empty.mkv",
        0,
        "unknown",
        0,
        0,
        HdrType::Sdr,
        0.0,
        0,
        vec![],
        vec![],
    );
    let strategy = make_strategy(
        "Default", "libx265", 0, 23, "fast", "yuv420p", "copy_all", "keep_all", "",
    );

    let audit = build_audit(
        &snapshot,
        Path::new("/movies/empty_out.mkv"),
        0,
        "",
        &strategy,
        0,
        false,
        "no data",
        "",
    );

    assert!(!audit.success);
    assert_eq!(audit.savings_pct, 0.0);
    assert_eq!(audit.source_size_bytes, 0);
    assert_eq!(audit.size_delta_bytes, 0);
}

// ── H-029: CompressionAudit extended fields tests ─────────────────────────

fn make_rich_snapshot() -> FileSnapshot {
    FileSnapshot {
        relative_path: "/movies/rich.mkv".into(),
        size_bytes: 5_000_000_000,
        video_codec: VideoCodec::Hevc,
        video_width: 3840,
        video_height: 2160,
        hdr_type: HdrType::Hdr10,
        duration_seconds: 7200.0,
        bitrate_bps: 5_500_000,
        audio_tracks: vec![],
        subtitle_tracks: vec![],
        pix_fmt: "yuv420p10le".into(),
        frame_rate: "24000/1001".into(),
        color_primaries: "bt2020".into(),
        color_transfer: "smpte2084".into(),
        color_space: "bt2020nc".into(),
        file_mtime: 1716500000.0,
        ..Default::default()
    }
}

#[test]
fn test_build_audit_includes_extended_source_fields() {
    let snapshot = make_rich_snapshot();
    let strategy = make_strategy(
        "HEVC CRF18",
        "libx265",
        0,
        18,
        "slow",
        "yuv420p10le",
        "copy_all",
        "keep_all",
        "",
    );

    let audit = build_audit(
        &snapshot,
        Path::new("/movies/rich_out.mkv"),
        2_000_000_000,
        "hevc",
        &strategy,
        300_000,
        true,
        "",
        "ffmpeg -i in.mkv -c:v libx265 -crf 18 out.mkv",
    );

    // H-029: Verify all 10 extended fields are populated
    assert_eq!(audit.source_pix_fmt, "yuv420p10le");
    assert_eq!(audit.source_frame_rate, "24000/1001");
    assert_eq!(audit.source_color_primaries, "bt2020");
    assert_eq!(audit.source_color_transfer, "smpte2084");
    assert_eq!(audit.source_color_space, "bt2020nc");
    assert!(audit.source_mtime > 0.0);
    assert!(!audit.platform.is_empty(), "platform should not be empty");
    // Adaptive CQ fields default to 0/empty
    assert_eq!(audit.adaptive_cq_original, 0);
    assert_eq!(audit.adaptive_cq_adjusted, 0);
    assert_eq!(audit.adaptive_cq_reason, "");
}

#[test]
fn test_build_audit_platform_is_detected() {
    let snapshot = make_snapshot(
        "/p.mkv",
        1_000_000,
        "h264",
        1920,
        1080,
        HdrType::Sdr,
        60.0,
        2_000_000,
        vec![],
        vec![],
    );
    let strategy = make_strategy(
        "Fast",
        "av1_nvenc",
        28,
        0,
        "p7",
        "p010le",
        "copy_all",
        "keep_all",
        "",
    );

    let audit = build_audit(
        &snapshot,
        Path::new("/p_out.mkv"),
        500_000,
        "av1",
        &strategy,
        30_000,
        true,
        "",
        "",
    );

    // Platform should contain the OS name
    let platform = &audit.platform;
    assert!(!platform.is_empty());
    // On Windows, "windows" should be in the platform string (case-insensitive)
    assert!(
        platform.to_lowercase().contains("windows")
            || platform.contains("linux")
            || platform.contains("macos"),
        "Platform should identify the OS, got: {}",
        platform
    );
}

#[test]
fn test_build_audit_zero_size_preserves_extended_fields() {
    // Edge case: snapshot with zero-size but rich probe metadata
    let snapshot = FileSnapshot {
        relative_path: "/empty_rich.mkv".into(),
        size_bytes: 0,
        video_codec: VideoCodec::Unknown("unknown".into()),
        video_width: 0,
        video_height: 0,
        hdr_type: HdrType::Sdr,
        duration_seconds: 0.0,
        bitrate_bps: 0,
        audio_tracks: vec![],
        subtitle_tracks: vec![],
        pix_fmt: "yuv420p".into(),
        frame_rate: "30000/1001".into(),
        color_primaries: "bt709".into(),
        color_transfer: "bt709".into(),
        color_space: "bt709".into(),
        file_mtime: 0.0,
        ..Default::default()
    };
    let strategy = make_strategy(
        "D", "libx265", 0, 23, "fast", "yuv420p", "copy_all", "keep_all", "",
    );

    let audit = build_audit(
        &snapshot,
        Path::new("/e.mkv"),
        0,
        "",
        &strategy,
        0,
        false,
        "error",
        "",
    );

    // Even with zero-size failure, extended fields should still be populated
    assert_eq!(audit.source_pix_fmt, "yuv420p");
    assert_eq!(audit.source_frame_rate, "30000/1001");
    assert_eq!(audit.source_color_primaries, "bt709");
    assert_eq!(audit.source_color_transfer, "bt709");
    assert_eq!(audit.source_color_space, "bt709");
    assert!(!audit.platform.is_empty());
}
