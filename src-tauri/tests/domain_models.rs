use leanreel_rs_lib::domain::models::*;

#[test]
fn test_hdr_type_equality() {
    assert_ne!(HdrType::Sdr, HdrType::Hdr10);
    assert_ne!(HdrType::Hdr10, HdrType::Hdr10Plus);
    let dv5 = HdrType::DolbyVision {
        profile: DvProfile::Profile5,
    };
    let dv7 = HdrType::DolbyVision {
        profile: DvProfile::Profile7,
    };
    assert_ne!(dv5, dv7);
}

#[test]
fn test_video_codec_from_string() {
    assert_eq!(VideoCodec::from_codec("hevc"), VideoCodec::Hevc);
    assert_eq!(VideoCodec::from_codec("h264"), VideoCodec::H264);
    assert_eq!(VideoCodec::from_codec("av1"), VideoCodec::Av1);
    assert_eq!(VideoCodec::from_codec("mpeg2video"), VideoCodec::Mpeg2);
    assert_eq!(VideoCodec::from_codec("vp9"), VideoCodec::Vp9);
    assert_eq!(VideoCodec::from_codec("vp09"), VideoCodec::Vp9);

    // Alias variants
    assert_eq!(VideoCodec::from_codec("avc"), VideoCodec::H264);
    assert_eq!(VideoCodec::from_codec("h.264"), VideoCodec::H264);
    assert_eq!(VideoCodec::from_codec("h265"), VideoCodec::Hevc);
    assert_eq!(VideoCodec::from_codec("h.265"), VideoCodec::Hevc);
    assert_eq!(VideoCodec::from_codec("mpeg2"), VideoCodec::Mpeg2);
    assert_eq!(VideoCodec::from_codec("mpeg-2"), VideoCodec::Mpeg2);
    assert_eq!(VideoCodec::from_codec("vc1"), VideoCodec::Vc1);
    assert_eq!(VideoCodec::from_codec("vc-1"), VideoCodec::Vc1);
}

#[test]
fn test_strategy_result_variants() {
    let encode = StrategyResult::Encode {
        strategy_name: "x265 HEVC CRF 20".into(),
        estimated_saving: SavingsEstimate {
            percentage: "40-60%".into(),
            estimated_min_bytes: 400_000_000,
            estimated_max_bytes: 600_000_000,
        },
    };
    let skip = StrategyResult::SkipProtected {
        reason: SkipReason::HevcSource,
    };

    let no_match = StrategyResult::SkipNoMatch {
        reason: "无匹配策略".into(),
    };

    assert!(matches!(encode, StrategyResult::Encode { .. }));
    assert!(matches!(skip, StrategyResult::SkipProtected { .. }));
    assert!(matches!(no_match, StrategyResult::SkipNoMatch { .. }));
}

#[test]
fn test_file_snapshot_serde_roundtrip() {
    let snap = FileSnapshot {
        id: None,
        library_folder_id: 1,
        relative_path: "movies/example.mkv".into(),
        file_name: "example.mkv".into(),
        size_bytes: 2_147_483_648,
        video_codec: VideoCodec::H264,
        video_width: 1920,
        video_height: 1080,
        hdr_type: HdrType::Sdr,
        audio_tracks: vec![
            AudioTrack {
                codec: "aac".into(),
                channels: 2,
                language: "eng".into(),
                title: "".into(),
                is_commentary: false,
            },
            AudioTrack {
                codec: "ac3".into(),
                channels: 6,
                language: "eng".into(),
                title: "".into(),
                is_commentary: false,
            },
        ],
        subtitle_tracks: vec![
            SubtitleTrack {
                codec: "subrip".into(),
                language: "eng".into(),
                title: "".into(),
                is_forced: false,
            },
            SubtitleTrack {
                codec: "subrip".into(),
                language: "chs".into(),
                title: "".into(),
                is_forced: false,
            },
        ],
        duration_seconds: 5400.0,
        bitrate_bps: 3_200_000,
        file_mtime: 1716500000.0,
        probe_ok: true,
        probe_error: String::new(),
        scanned_at: "2026-05-30 12:00:00".into(),
        ..Default::default()
    };

    let json = serde_json::to_string(&snap).unwrap();
    let restored: FileSnapshot = serde_json::from_str(&json).unwrap();
    assert_eq!(snap.file_name, restored.file_name);
    assert_eq!(snap.video_codec, restored.video_codec);
}

#[test]
fn test_strategy_deserialize_from_real_json() {
    let json = r#"{
        "name": "AV1 NVENC CQ28",
        "description": "test",
        "is_preset": true,
        "video": {"encoder": "av1_nvenc", "crf": 0, "preset": "", "pix_fmt": "yuv420p10le", "x265_params": "", "gpu": true, "nv_preset": "p6", "rc": "vbr", "cq": 28},
        "hdr": {"mode": "preserve_hdr10", "dv_handling": "reinject_rpu"},
        "audio": {"mode": "keep_original", "remove_commentary": false},
        "subtitle": {"mode": "keep_all"},
        "filters": {"skip_x265": true, "min_size_gb": null, "only_remux": false},
        "estimated_savings": "35-55%",
        "quality_impact": "test"
    }"#;
    let strategy: Strategy = serde_json::from_str(json).unwrap();
    assert_eq!(strategy.name, "AV1 NVENC CQ28");
    assert_eq!(strategy.video.encoder, "av1_nvenc");
    assert_eq!(strategy.video.cq, 28);
    assert!(strategy.video.gpu);
    assert_eq!(strategy.hdr.mode, "preserve_hdr10");
    assert!(strategy.filters.skip_x265);
    assert!(strategy.filters.min_size_gb.is_none());
}
