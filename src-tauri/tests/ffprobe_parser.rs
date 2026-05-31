use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::infrastructure::ffprobe::parse_ffprobe_output;

const SAMPLE_SDR_H264: &str = r#"{
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "tags": {"language": "eng"}
        },
        {
            "codec_type": "subtitle",
            "codec_name": "subrip",
            "tags": {"language": "chs"}
        }
    ],
    "format": {
        "size": "2147483648",
        "duration": "5400.000000",
        "bit_rate": "3400000"
    }
}"#;

const SAMPLE_HDR10_HEVC: &str = r#"{
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 3840,
            "height": 2160,
            "color_space": "bt2020nc",
            "color_transfer": "smpte2084",
            "color_primaries": "bt2020"
        }
    ],
    "format": {
        "size": "45000000000",
        "duration": "7200.000000",
        "bit_rate": "26000000"
    }
}"#;

const SAMPLE_DOLBY_VISION: &str = r#"{
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 3840,
            "height": 2160,
            "color_space": "bt2020nc",
            "color_transfer": "smpte2084",
            "color_primaries": "bt2020",
            "side_data_list": [
                {
                    "side_data_type": "Dolby Vision",
                    "dv_profile": 8,
                    "dv_level": 6
                }
            ]
        }
    ],
    "format": {
        "size": "22000000000",
        "duration": "6000.000000",
        "bit_rate": "31000000"
    }
}"#;

#[test]
fn test_parse_sdr_h264() {
    let meta = parse_ffprobe_output(SAMPLE_SDR_H264).unwrap();
    assert_eq!(meta.codec, VideoCodec::H264);
    assert_eq!(meta.width, 1920);
    assert_eq!(meta.height, 1080);
    assert_eq!(meta.hdr_type, HdrType::Sdr);
    assert_eq!(meta.duration_seconds, 5400.0);
    assert_eq!(meta.bitrate_bps, 3400000);
    assert_eq!(meta.audio_tracks.len(), 1);
    assert_eq!(meta.subtitle_tracks.len(), 1);
    assert_eq!(meta.audio_tracks[0].language, "eng");
    assert_eq!(meta.subtitle_tracks[0].language, "chs");
}

#[test]
fn test_parse_hdr10_hevc() {
    let meta = parse_ffprobe_output(SAMPLE_HDR10_HEVC).unwrap();
    assert_eq!(meta.codec, VideoCodec::Hevc);
    assert_eq!(meta.width, 3840);
    assert_eq!(meta.height, 2160);
    assert_eq!(meta.hdr_type, HdrType::Hdr10);
    assert_eq!(meta.bitrate_bps, 26000000);
}

#[test]
fn test_parse_dolby_vision() {
    let meta = parse_ffprobe_output(SAMPLE_DOLBY_VISION).unwrap();
    assert_eq!(meta.codec, VideoCodec::Hevc);
    match meta.hdr_type {
        HdrType::DolbyVision { profile } => {
            assert_eq!(profile, DvProfile::Profile8_1);
        }
        _ => panic!("Expected DolbyVision"),
    }
}

#[test]
fn test_parse_broken_json_returns_err() {
    let result = parse_ffprobe_output("not valid json");
    assert!(result.is_err());
}

#[test]
fn test_parse_no_video_stream() {
    let json = r#"{"streams": [{"codec_type": "audio", "codec_name": "aac"}], "format": {"size": "1000", "bit_rate": "128000"}}"#;
    let result = parse_ffprobe_output(json);
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("未找到视频流"));
}

#[test]
fn test_hdr_detect_10bit_hevc_fallback() {
    // 10-bit HEVC with no color metadata — Python marks as HDR10
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p10le"
            }
        ],
        "format": {
            "size": "10000000",
            "duration": "600.000000",
            "bit_rate": "5000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    assert_eq!(
        meta.hdr_type,
        HdrType::Hdr10,
        "10-bit HEVC without color metadata should be HDR10"
    );
}

#[test]
fn test_hdr_detect_8bit_hevc_no_fallback() {
    // 8-bit HEVC with no color metadata — should stay SDR
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p"
            }
        ],
        "format": {
            "size": "10000000",
            "duration": "600.000000",
            "bit_rate": "5000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    assert_eq!(
        meta.hdr_type,
        HdrType::Sdr,
        "8-bit HEVC without color metadata should be SDR"
    );
}

// === C1: DV profile default = 7 (matching Python) ===

#[test]
fn test_dv_profile_defaults_to_7() {
    // DV detected via side_data but dv_profile field is missing —
    // should default to Profile7 matching Python int(dv_info.get("dv_profile", 7))
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "side_data_list": [
                    {
                        "side_data_type": "Dolby Vision"
                    }
                ]
            }
        ],
        "format": {
            "size": "10000000",
            "duration": "3600.000000",
            "bit_rate": "20000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    match meta.hdr_type {
        HdrType::DolbyVision { profile } => {
            assert_eq!(
                profile,
                DvProfile::Profile7,
                "Missing dv_profile should default to 7, not 8"
            );
        }
        _ => panic!("Expected DolbyVision, got {:?}", meta.hdr_type),
    }
}

// === C2: DV codec tag detection uses codec_tag_string (not codec_name) ===

#[test]
fn test_dv_detected_via_codec_tag_string_dvh1() {
    // DV via codec_tag_string "dvh1" — codec_name="hevc" would NOT start with "dvh"
    // This test proves C2 fix: codec_tag_string is read instead of codec_name
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "codec_tag_string": "dvh1",
                "width": 3840,
                "height": 2160
            }
        ],
        "format": {
            "size": "25000000000",
            "duration": "7200.000000",
            "bit_rate": "28000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    match meta.hdr_type {
        HdrType::DolbyVision { profile } => {
            assert_eq!(profile, DvProfile::Profile8_1);
        }
        _ => panic!(
            "Expected DolbyVision via codec_tag_string, got {:?}",
            meta.hdr_type
        ),
    }
}

#[test]
fn test_dv_detected_via_codec_tag_string_dav1() {
    // DV via codec_tag_string "dav1" (AV1-based Dolby Vision)
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "av1",
                "codec_tag_string": "dav1",
                "width": 3840,
                "height": 2160
            }
        ],
        "format": {
            "size": "20000000000",
            "duration": "5400.000000",
            "bit_rate": "30000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    match meta.hdr_type {
        HdrType::DolbyVision { profile } => {
            assert_eq!(profile, DvProfile::Profile8_1);
        }
        _ => panic!(
            "Expected DolbyVision via dav1 codec_tag, got {:?}",
            meta.hdr_type
        ),
    }
}

#[test]
fn test_hdr10_takes_priority_over_codec_tag() {
    // When BOTH HDR10 (smpte2084+bt2020) AND DV codec_tag are present,
    // HDR10 should win (matching Python: HDR10 check happens before codec_tag)
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "codec_tag_string": "dvh1",
                "width": 3840,
                "height": 2160,
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020"
            }
        ],
        "format": {
            "size": "30000000000",
            "duration": "6000.000000",
            "bit_rate": "40000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    assert_eq!(
        meta.hdr_type,
        HdrType::Hdr10,
        "HDR10 should take priority over DV codec_tag fallback"
    );
}

// === H13: HDR10+ uses exact match "HDR Dynamic Metadata" ===

#[test]
fn test_hdr10plus_exact_match() {
    // Exact "HDR Dynamic Metadata" side_data_type triggers HDR10+
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
                "side_data_list": [
                    {
                        "side_data_type": "HDR Dynamic Metadata"
                    }
                ]
            }
        ],
        "format": {
            "size": "35000000000",
            "duration": "7200.000000",
            "bit_rate": "45000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    assert_eq!(
        meta.hdr_type,
        HdrType::Hdr10Plus,
        "Exact 'HDR Dynamic Metadata' should be HDR10+"
    );
}

#[test]
fn test_hdr10plus_rejects_fuzzy_match() {
    // Similar-looking side_data_type that is NOT exactly "HDR Dynamic Metadata"
    // should NOT be detected as HDR10+ (must be HDR10 instead)
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
                "side_data_list": [
                    {
                        "side_data_type": "HDR dynamic metadata V1"
                    }
                ]
            }
        ],
        "format": {
            "size": "35000000000",
            "duration": "7200.000000",
            "bit_rate": "45000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    assert_eq!(
        meta.hdr_type,
        HdrType::Hdr10,
        "Non-exact 'HDR dynamic metadata V1' should NOT be HDR10+"
    );
}

// === H14: 10-bit fallback checks profile field alongside pix_fmt ===

#[test]
fn test_hdr10_fallback_via_profile_main10() {
    // Profile "Main 10" with 8-bit pix_fmt — should detect as HDR10 fallback
    // because Python checks "10" in profile_str OR "10" in pix_fmt
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "profile": "Main 10",
                "pix_fmt": "yuv420p",
                "width": 1920,
                "height": 1080
            }
        ],
        "format": {
            "size": "10000000",
            "duration": "600.000000",
            "bit_rate": "5000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    assert_eq!(
        meta.hdr_type,
        HdrType::Hdr10,
        "Main 10 profile without 10-bit pix_fmt should be HDR10"
    );
}

// === M9: Color metadata extraction ===

#[test]
fn test_color_metadata_extracted() {
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "pix_fmt": "yuv420p10le",
                "r_frame_rate": "24000/1001",
                "color_primaries": "bt2020",
                "color_transfer": "smpte2084",
                "color_space": "bt2020nc"
            }
        ],
        "format": {
            "size": "45000000000",
            "duration": "7200.000000",
            "bit_rate": "26000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    assert_eq!(meta.pix_fmt, "yuv420p10le");
    assert_eq!(meta.frame_rate, "24000/1001");
    assert_eq!(meta.color_primaries, "bt2020");
    assert_eq!(meta.color_transfer, "smpte2084");
    assert_eq!(meta.color_space, "bt2020nc");
    assert_eq!(
        meta.hdr_type,
        HdrType::Hdr10,
        "With full color metadata it should be HDR10, not fallback"
    );
}

#[test]
fn test_color_metadata_defaults_empty() {
    // When fields are absent, they should default to empty string
    let json = r#"{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080
            }
        ],
        "format": {
            "size": "1000000000",
            "duration": "3600.000000",
            "bit_rate": "2000000"
        }
    }"#;
    let meta = parse_ffprobe_output(json).unwrap();
    assert!(meta.pix_fmt.is_empty());
    assert!(meta.frame_rate.is_empty());
    assert!(meta.color_primaries.is_empty());
    assert!(meta.color_transfer.is_empty());
    assert!(meta.color_space.is_empty());
}
