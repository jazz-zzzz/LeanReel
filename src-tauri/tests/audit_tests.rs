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
    assert!(restored.success);
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

struct SnapshotFixtureParams<'a> {
    path: &'a str,
    size: i64,
    codec: &'a str,
    width: i32,
    height: i32,
    hdr: HdrType,
    duration: f64,
    bitrate: i64,
    audio: Vec<AudioTrack>,
    subs: Vec<SubtitleTrack>,
}

fn make_snapshot(params: SnapshotFixtureParams<'_>) -> FileSnapshot {
    let SnapshotFixtureParams {
        path,
        size,
        codec,
        width,
        height,
        hdr,
        duration,
        bitrate,
        audio,
        subs,
    } = params;
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

struct StrategyFixtureParams<'a> {
    name: &'a str,
    encoder: &'a str,
    cq: i32,
    crf: i32,
    preset: &'a str,
    pix_fmt: &'a str,
    audio_mode: &'a str,
    sub_mode: &'a str,
    dv_handling: &'a str,
}

fn make_strategy(params: StrategyFixtureParams<'_>) -> Strategy {
    let StrategyFixtureParams {
        name,
        encoder,
        cq,
        crf,
        preset,
        pix_fmt,
        audio_mode,
        sub_mode,
        dv_handling,
    } = params;
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
    let snapshot = make_snapshot(SnapshotFixtureParams {
        path: "/movies/test.mkv",
        size: 2_000_000_000,
        codec: "h264",
        width: 1920,
        height: 1080,
        hdr: HdrType::Sdr,
        duration: 3600.0,
        bitrate: 4_000_000,
        audio: vec![AudioTrack {
            codec: "aac".into(),
            channels: 6,
            language: "eng".into(),
            title: "Surround".into(),
            is_commentary: false,
        }],
        subs: vec![SubtitleTrack {
            codec: "srt".into(),
            language: "eng".into(),
            title: "English".into(),
            is_forced: false,
        }],
    });
    let strategy = make_strategy(StrategyFixtureParams {
        name: "AV1 NVENC CQ28",
        encoder: "av1_nvenc",
        cq: 28,
        crf: 0,
        preset: "p7",
        pix_fmt: "p010le",
        audio_mode: "copy_all",
        sub_mode: "keep_all",
        dv_handling: "passthrough",
    });

    let audit = build_audit(BuildAuditParams {
        snapshot: &snapshot,
        output_path: Path::new("/movies/test_leanreel.mkv"),
        output_size: 800_000_000,
        output_codec: "av1",
        strategy: &strategy,
        duration_ms: 120_000,
        success: true,
        error: "",
        ffmpeg_command: "ffmpeg -i test.mkv -c:v av1_nvenc -cq 28 -preset p7 out.mkv",
    });

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
    let snapshot = make_snapshot(SnapshotFixtureParams {
        path: "/movies/bad.mkv",
        size: 1_000_000_000,
        codec: "h264",
        width: 3840,
        height: 2160,
        hdr: HdrType::Hdr10,
        duration: 5400.0,
        bitrate: 1_500_000,
        audio: vec![],
        subs: vec![],
    });
    let strategy = make_strategy(StrategyFixtureParams {
        name: "HEVC CRF22",
        encoder: "libx265",
        cq: 0,
        crf: 22,
        preset: "medium",
        pix_fmt: "yuv420p10le",
        audio_mode: "copy_all",
        sub_mode: "no_subs",
        dv_handling: "strip_dv",
    });

    let audit = build_audit(BuildAuditParams {
        snapshot: &snapshot,
        output_path: Path::new("/movies/bad_leanreel.mkv"),
        output_size: 0,
        output_codec: "",
        strategy: &strategy,
        duration_ms: 5000,
        success: false,
        error: "ffmpeg crashed",
        ffmpeg_command: "ffmpeg -i bad.mkv -c:v libx265 -crf 22 out.mkv",
    });

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
    let snapshot = make_snapshot(SnapshotFixtureParams {
        path: "/movies/dv.mkv",
        size: 5_000_000_000,
        codec: "hevc",
        width: 3840,
        height: 2160,
        hdr: HdrType::DolbyVision {
            profile: DvProfile::Profile5,
        },
        duration: 7200.0,
        bitrate: 5_500_000,
        audio: vec![
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
        subs: vec![
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
    });
    let strategy = make_strategy(StrategyFixtureParams {
        name: "AV1 DV Passthrough",
        encoder: "av1_nvenc",
        cq: 30,
        crf: 0,
        preset: "p7",
        pix_fmt: "p010le",
        audio_mode: "copy_all",
        sub_mode: "keep_all",
        dv_handling: "passthrough",
    });

    let audit = build_audit(BuildAuditParams {
        snapshot: &snapshot,
        output_path: Path::new("/movies/dv_leanreel.mkv"),
        output_size: 2_000_000_000,
        output_codec: "av1",
        strategy: &strategy,
        duration_ms: 300_000,
        success: true,
        error: "",
        ffmpeg_command: "ffmpeg -i dv.mkv -c:v av1_nvenc -cq 30 -preset p7 out.mkv",
    });

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

    let snapshot = make_snapshot(SnapshotFixtureParams {
        path: "/src.mkv",
        size: 2_000_000_000,
        codec: "h264",
        width: 1920,
        height: 1080,
        hdr: HdrType::Sdr,
        duration: 3600.0,
        bitrate: 4_000_000,
        audio: vec![],
        subs: vec![],
    });
    let strategy = make_strategy(StrategyFixtureParams {
        name: "AV1 CQ28",
        encoder: "av1_nvenc",
        cq: 28,
        crf: 0,
        preset: "p7",
        pix_fmt: "p010le",
        audio_mode: "copy_all",
        sub_mode: "keep_all",
        dv_handling: "",
    });

    let audit = build_audit(BuildAuditParams {
        snapshot: &snapshot,
        output_path: Path::new("/out.mkv"),
        output_size: 800_000_000,
        output_codec: "av1",
        strategy: &strategy,
        duration_ms: 100_000,
        success: true,
        error: "",
        ffmpeg_command: "ffmpeg -i src.mkv -c:v av1_nvenc -cq 28 out.mkv",
    });

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
    let snapshot = make_snapshot(SnapshotFixtureParams {
        path: "/movies/empty.mkv",
        size: 0,
        codec: "unknown",
        width: 0,
        height: 0,
        hdr: HdrType::Sdr,
        duration: 0.0,
        bitrate: 0,
        audio: vec![],
        subs: vec![],
    });
    let strategy = make_strategy(StrategyFixtureParams {
        name: "Default",
        encoder: "libx265",
        cq: 0,
        crf: 23,
        preset: "fast",
        pix_fmt: "yuv420p",
        audio_mode: "copy_all",
        sub_mode: "keep_all",
        dv_handling: "",
    });

    let audit = build_audit(BuildAuditParams {
        snapshot: &snapshot,
        output_path: Path::new("/movies/empty_out.mkv"),
        output_size: 0,
        output_codec: "",
        strategy: &strategy,
        duration_ms: 0,
        success: false,
        error: "no data",
        ffmpeg_command: "",
    });

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
    let strategy = make_strategy(StrategyFixtureParams {
        name: "HEVC CRF18",
        encoder: "libx265",
        cq: 0,
        crf: 18,
        preset: "slow",
        pix_fmt: "yuv420p10le",
        audio_mode: "copy_all",
        sub_mode: "keep_all",
        dv_handling: "",
    });

    let audit = build_audit(BuildAuditParams {
        snapshot: &snapshot,
        output_path: Path::new("/movies/rich_out.mkv"),
        output_size: 2_000_000_000,
        output_codec: "hevc",
        strategy: &strategy,
        duration_ms: 300_000,
        success: true,
        error: "",
        ffmpeg_command: "ffmpeg -i in.mkv -c:v libx265 -crf 18 out.mkv",
    });

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
    let snapshot = make_snapshot(SnapshotFixtureParams {
        path: "/p.mkv",
        size: 1_000_000,
        codec: "h264",
        width: 1920,
        height: 1080,
        hdr: HdrType::Sdr,
        duration: 60.0,
        bitrate: 2_000_000,
        audio: vec![],
        subs: vec![],
    });
    let strategy = make_strategy(StrategyFixtureParams {
        name: "Fast",
        encoder: "av1_nvenc",
        cq: 28,
        crf: 0,
        preset: "p7",
        pix_fmt: "p010le",
        audio_mode: "copy_all",
        sub_mode: "keep_all",
        dv_handling: "",
    });

    let audit = build_audit(BuildAuditParams {
        snapshot: &snapshot,
        output_path: Path::new("/p_out.mkv"),
        output_size: 500_000,
        output_codec: "av1",
        strategy: &strategy,
        duration_ms: 30_000,
        success: true,
        error: "",
        ffmpeg_command: "",
    });

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
    let strategy = make_strategy(StrategyFixtureParams {
        name: "D",
        encoder: "libx265",
        cq: 0,
        crf: 23,
        preset: "fast",
        pix_fmt: "yuv420p",
        audio_mode: "copy_all",
        sub_mode: "keep_all",
        dv_handling: "",
    });

    let audit = build_audit(BuildAuditParams {
        snapshot: &snapshot,
        output_path: Path::new("/e.mkv"),
        output_size: 0,
        output_codec: "",
        strategy: &strategy,
        duration_ms: 0,
        success: false,
        error: "error",
        ffmpeg_command: "",
    });

    // Even with zero-size failure, extended fields should still be populated
    assert_eq!(audit.source_pix_fmt, "yuv420p");
    assert_eq!(audit.source_frame_rate, "30000/1001");
    assert_eq!(audit.source_color_primaries, "bt709");
    assert_eq!(audit.source_color_transfer, "bt709");
    assert_eq!(audit.source_color_space, "bt709");
    assert!(!audit.platform.is_empty());
}
