use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::services::matcher::StrategyMatcher;

fn make_snap(codec: VideoCodec, hdr: HdrType, size: i64, bitrate: i64) -> FileSnapshot {
    FileSnapshot {
        id: None,
        library_folder_id: 1,
        relative_path: "test.mkv".into(),
        file_name: "test.mkv".into(),
        size_bytes: size,
        video_codec: codec,
        video_width: 1920,
        video_height: 1080,
        hdr_type: hdr,
        audio_tracks: vec![],
        subtitle_tracks: vec![],
        duration_seconds: 3600.0,
        bitrate_bps: bitrate,
        file_mtime: 0.0,
        probe_ok: true,
        probe_error: String::new(),
        scanned_at: "2026-05-30".into(),
        ..Default::default()
    }
}

fn make_strategy(name: &str, encoder: &str, cq: i32) -> Strategy {
    Strategy {
        name: name.into(),
        description: String::new(),
        is_preset: true,
        video: VideoConfig {
            encoder: encoder.into(),
            crf: 0,
            preset: String::new(),
            pix_fmt: "yuv420p10le".into(),
            x265_params: String::new(),
            gpu: true,
            nv_preset: "p5".into(),
            rc: "vbr".into(),
            cq,
        },
        hdr: HdrConfig {
            mode: "preserve_hdr10".into(),
            dv_handling: "reinject_rpu".into(),
        },
        audio: AudioConfig {
            mode: "keep_original".into(),
            preferred_languages: vec![],
        },
        subtitle: SubtitleConfig {
            mode: "keep_all".into(),
        },
        filters: FilterConfig {
            skip_x265: true,
            min_size_gb: None,
            only_remux: false,
        },
        estimated_savings: "30-50%".into(),
        quality_impact: String::new(),
    }
}

#[test]
fn test_match_h264_sdr() {
    let strategies = vec![make_strategy("AV1 CQ28", "av1_nvenc", 28)];
    let matcher = StrategyMatcher::new(strategies);
    let snap = make_snap(VideoCodec::H264, HdrType::Sdr, 2_000_000_000, 5_000_000);
    let result = matcher.match_for(&snap);
    assert!(matches!(result, StrategyResult::Encode { .. }));
}

#[test]
fn test_match_hevc_skipped() {
    let strategies = vec![make_strategy("AV1 CQ28", "av1_nvenc", 28)];
    let matcher = StrategyMatcher::new(strategies);
    let snap = make_snap(VideoCodec::Hevc, HdrType::Sdr, 2_000_000_000, 5_000_000);
    assert!(matches!(
        matcher.match_for(&snap),
        StrategyResult::SkipProtected {
            reason: SkipReason::HevcSource
        }
    ));
}

#[test]
fn test_match_av1_skipped() {
    let matcher = StrategyMatcher::new(vec![make_strategy("AV1 CQ28", "av1_nvenc", 28)]);
    let snap = make_snap(VideoCodec::Av1, HdrType::Sdr, 2_000_000_000, 5_000_000);
    assert!(matches!(
        matcher.match_for(&snap),
        StrategyResult::SkipProtected {
            reason: SkipReason::Av1Source
        }
    ));
}

#[test]
fn test_match_hdr10_skipped() {
    let matcher = StrategyMatcher::new(vec![make_strategy("AV1 CQ28", "av1_nvenc", 28)]);
    let snap = make_snap(VideoCodec::H264, HdrType::Hdr10, 2_000_000_000, 5_000_000);
    assert!(matches!(
        matcher.match_for(&snap),
        StrategyResult::SkipProtected {
            reason: SkipReason::Hdr10
        }
    ));
}

#[test]
fn test_match_hdr10plus_skipped() {
    let matcher = StrategyMatcher::new(vec![make_strategy("AV1 CQ28", "av1_nvenc", 28)]);
    let snap = make_snap(
        VideoCodec::H264,
        HdrType::Hdr10Plus,
        2_000_000_000,
        5_000_000,
    );
    assert!(matches!(
        matcher.match_for(&snap),
        StrategyResult::SkipProtected {
            reason: SkipReason::Hdr10PlusSource
        }
    ));
}

#[test]
fn test_match_dolby_vision_skipped() {
    let matcher = StrategyMatcher::new(vec![make_strategy("AV1 CQ28", "av1_nvenc", 28)]);
    let snap = make_snap(
        VideoCodec::H264,
        HdrType::DolbyVision {
            profile: DvProfile::Profile8_1,
        },
        2_000_000_000,
        5_000_000,
    );
    assert!(matches!(
        matcher.match_for(&snap),
        StrategyResult::SkipProtected {
            reason: SkipReason::DolbyVision
        }
    ));
}

#[test]
fn test_match_vc1_no_strategy_fits() {
    let matcher = StrategyMatcher::new(vec![make_strategy("AV1 CQ28", "av1_nvenc", 28)]);
    let snap = make_snap(VideoCodec::Vc1, HdrType::Sdr, 2_000_000_000, 5_000_000);
    assert!(matches!(
        matcher.match_for(&snap),
        StrategyResult::SkipNoMatch { .. }
    ));
}

#[test]
fn test_match_batch() {
    let matcher = StrategyMatcher::new(vec![make_strategy("AV1 CQ28", "av1_nvenc", 28)]);
    let snapshots = vec![
        make_snap(VideoCodec::H264, HdrType::Sdr, 2_000_000_000, 5_000_000),
        make_snap(VideoCodec::Hevc, HdrType::Sdr, 3_000_000_000, 8_000_000),
        make_snap(VideoCodec::Av1, HdrType::Sdr, 1_000_000_000, 2_000_000),
    ];
    let results = matcher.match_batch(&snapshots);
    assert_eq!(results.len(), 3);
    assert!(matches!(results[0], StrategyResult::Encode { .. }));
    assert!(matches!(results[1], StrategyResult::SkipProtected { .. }));
    assert!(matches!(results[2], StrategyResult::SkipProtected { .. }));
}

#[test]
fn test_empty_strategies() {
    let matcher = StrategyMatcher::new(vec![]);
    let snap = make_snap(VideoCodec::H264, HdrType::Sdr, 2_000_000_000, 5_000_000);
    assert!(matches!(
        matcher.match_for(&snap),
        StrategyResult::SkipNoMatch { .. }
    ));
}
