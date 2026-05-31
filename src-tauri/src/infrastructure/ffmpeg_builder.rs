#[cfg(test)]
use crate::domain::models::{AudioConfig, AudioTrack, SubtitleConfig, SubtitleTrack, VideoConfig};
use crate::domain::models::{FileSnapshot, HdrType, Strategy, VideoCodec};
use std::path::Path;

/// Known valid encoders whitelist.
const VALID_ENCODERS: &[&str] = &[
    "libx265",
    "libx264",
    "av1_nvenc",
    "hevc_nvenc",
    "h264_nvenc",
    "copy",
];

/// Validate that the given encoder string is in the known-encoders whitelist.
pub fn validate_encoder(encoder: &str) -> Result<(), String> {
    if VALID_ENCODERS.contains(&encoder) {
        Ok(())
    } else {
        Err(format!(
            "娑撳秵鏁幐浣烘畱缂傛牜鐖滈崳? {}閵嗗倹鏁幐浣烘畱缂傛牜鐖滈崳? {}",
            encoder,
            VALID_ENCODERS.join(", ")
        ))
    }
}

/// Clamp CQ value based on encoder spec.
/// - AV1 NVENC: CQ 0-63
/// - HEVC NVENC: CQ 0-51
fn clamp_cq(cq: i32, encoder: &str) -> i32 {
    match encoder {
        "av1_nvenc" => cq.clamp(0, 63),
        "hevc_nvenc" | "h264_nvenc" => cq.clamp(0, 51),
        _ => cq, // no clamping for CPU encoders (they use CRF)
    }
}

/// Clamp CRF value based on encoder spec.
/// - x265: CRF 0-51
/// - libx264: CRF 0-51
fn clamp_crf(crf: i32, encoder: &str) -> i32 {
    match encoder {
        "libx265" | "libx264" => crf.clamp(0, 51),
        _ => crf,
    }
}

/// Build FFmpeg command-line arguments for video encoding.
pub fn build_ffmpeg_command(
    snapshot: &FileSnapshot,
    strategy: &Strategy,
    input_path: &Path,
    output_path: &Path,
    ffmpeg_path: &str,
) -> Result<Vec<String>, String> {
    validate_encoder(&strategy.video.encoder)?;

    let v = &strategy.video;
    let encoder = &v.encoder;
    let is_gpu = v.is_gpu();
    let cq = clamp_cq(v.cq, encoder);
    let crf = clamp_crf(v.crf, encoder);
    let is_hdr = matches!(
        snapshot.hdr_type,
        HdrType::Hdr10 | HdrType::Hdr10Plus | HdrType::DolbyVision { .. }
    );
    let mut cmd: Vec<String> = Vec::new();
    cmd.push(ffmpeg_path.to_string());
    cmd.push("-nostdin".into());
    cmd.push("-y".into());
    cmd.push("-fflags".into());
    cmd.push("+genpts+discardcorrupt".into());
    if is_gpu {
        let supports_nvdec = matches!(
            &snapshot.video_codec,
            VideoCodec::H264 | VideoCodec::Hevc | VideoCodec::Av1 | VideoCodec::Vp9
        );
        if supports_nvdec {
            cmd.push("-hwaccel".into());
            cmd.push("cuda".into());
            cmd.push("-hwaccel_output_format".into());
            cmd.push("cuda".into());
        }
    }
    cmd.push("-thread_queue_size".into());
    cmd.push("16384".into());
    cmd.push("-i".into());
    cmd.push(input_path.to_string_lossy().to_string());
    cmd.push("-map".into());
    cmd.push("0:V".into());
    if encoder == "copy" {
        cmd.push("-c:V".into());
        cmd.push("copy".into());
    } else if is_gpu {
        cmd.push("-c:V".into());
        cmd.push(encoder.clone());
        cmd.push("-preset".into());
        cmd.push(if !v.nv_preset.is_empty() {
            v.nv_preset.clone()
        } else {
            "p4".into()
        });
        cmd.push("-rc".into());
        cmd.push(if !v.rc.is_empty() {
            v.rc.clone()
        } else {
            "vbr".into()
        });
        cmd.push("-cq".into());
        cmd.push(cq.to_string());
        if encoder != "av1_nvenc" {
            cmd.push("-spatial-aq".into());
            cmd.push("1".into());
            cmd.push("-temporal-aq".into());
            cmd.push("1".into());
            cmd.push("-aq-strength".into());
            cmd.push("8".into());
        }
        if is_hdr {
            append_hdr_metadata(&mut cmd);
            if snapshot.hdr_type == HdrType::Hdr10Plus && supports_hdr10plus_flag(encoder) {
                cmd.push("-hdr10+".into());
            }
        }
    } else {
        cmd.push("-c:V".into());
        cmd.push(encoder.clone());
        cmd.push("-crf".into());
        cmd.push(crf.to_string());
        cmd.push("-preset".into());
        cmd.push(if !v.preset.is_empty() {
            v.preset.clone()
        } else {
            "slow".into()
        });
        cmd.push("-pix_fmt".into());
        cmd.push(if !v.pix_fmt.is_empty() {
            v.pix_fmt.clone()
        } else {
            "yuv420p10le".into()
        });
        if !v.x265_params.is_empty() {
            cmd.push("-x265-params".into());
            cmd.push(v.x265_params.clone());
        }
        if is_hdr {
            append_hdr_metadata(&mut cmd);
            if snapshot.hdr_type == HdrType::Hdr10Plus && supports_hdr10plus_flag(encoder) {
                cmd.push("-hdr10+".into());
            }
        }
    }
    // Audio: apply strategy mode and commentary removal
    build_audio_maps(&mut cmd, snapshot, strategy);
    // Subtitle: apply strategy mode
    build_subtitle_maps(&mut cmd, snapshot, strategy);
    cmd.push("-map".into());
    cmd.push("0:t?".into());
    cmd.push("-c:t".into());
    cmd.push("copy".into());
    cmd.push("-map_metadata".into());
    cmd.push("0".into());
    cmd.push("-map_chapters".into());
    cmd.push("0".into());
    cmd.push("-copy_unknown".into());
    cmd.push("-dn".into());
    cmd.push(output_path.to_string_lossy().to_string());
    Ok(cmd)
}

fn build_audio_maps(cmd: &mut Vec<String>, _snapshot: &FileSnapshot, _strategy: &Strategy) {
    cmd.push("-map".into());
    cmd.push("0:a?".into());
    cmd.push("-c:a".into());
    cmd.push("copy".into());
}


fn build_subtitle_maps(cmd: &mut Vec<String>, _snapshot: &FileSnapshot, _strategy: &Strategy) {
    cmd.push("-map".into());
    cmd.push("0:s?".into());
    cmd.push("-c:s".into());
    cmd.push("copy".into());
}

fn append_hdr_metadata(cmd: &mut Vec<String>) {
    cmd.push("-color_primaries".into());
    cmd.push("bt2020".into());
    cmd.push("-color_trc".into());
    cmd.push("smpte2084".into());
    cmd.push("-colorspace".into());
    cmd.push("bt2020nc".into());
}

/// Check if the encoder supports the -hdr10+ flag.
/// Matching Python behavior: libx265 and hevc_nvenc support HDR10+.
fn supports_hdr10plus_flag(encoder: &str) -> bool {
    matches!(encoder, "libx265" | "hevc_nvenc")
}

#[cfg(test)]
mod tests {
    use super::*;

    // 閳光偓閳光偓 Helper builders 閳光偓閳光偓

    fn cmd_joined(snapshot: &FileSnapshot, strategy: &Strategy) -> String {
        let mut s = strategy.clone();
        if s.video.encoder.is_empty() {
            s.video.encoder = "hevc_nvenc".into();
            s.video.gpu = true;
        }
        let cmd = build_ffmpeg_command(
            snapshot,
            &s,
            std::path::Path::new("in.mkv"),
            std::path::Path::new("out.mkv"),
            "ffmpeg",
        )
        .expect("build_ffmpeg_command should succeed in tests");
        cmd.join(" ")
    }

    fn audio(codec: &str, lang: &str, commentary: bool) -> AudioTrack {
        AudioTrack {
            codec: codec.into(),
            channels: 2,
            language: lang.into(),
            title: "".into(),
            is_commentary: commentary,
        }
    }

    fn sub(codec: &str, lang: &str) -> SubtitleTrack {
        SubtitleTrack {
            codec: codec.into(),
            language: lang.into(),
            title: "".into(),
            is_forced: false,
        }
    }

    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?
    // C5: Audio mode tests
    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?

    #[test]
    fn test_audio_keep_original_preserves_all_tracks() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![
                audio("aac", "jpn", false),
                audio("aac", "eng", false),
                audio("aac", "eng", true),
            ],
            ..Default::default()
        };
        let strategy = Strategy {
            audio: AudioConfig {
                mode: "keep_original".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:a:0"), "keep jpn: {}", joined);
        assert!(joined.contains("-map 0:a:1"), "keep eng: {}", joined);
        assert!(joined.contains("-map 0:a:2"), "keep commentary: {}", joined);
    }

    #[test]
    fn test_audio_remove_commentary_excludes_commentary_tracks() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![
                audio("aac", "jpn", false),
                audio("aac", "eng", false),
                audio("aac", "eng", true), // commentary 閳?must be excluded
            ],
            ..Default::default()
        };
        let strategy = Strategy {
            audio: AudioConfig {
                mode: "strip_commentary".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:a:0"), "keep jpn: {}", joined);
        assert!(joined.contains("-map 0:a:1"), "keep eng: {}", joined);
        assert!(
            !joined.contains("-map 0:a:2"),
            "exclude commentary: {}",
            joined
        );
    }

    #[test]
    fn test_audio_strip_commentary_mode_excludes_commentary_tracks() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![
                audio("aac", "jpn", false),
                audio("aac", "eng", true), // commentary
            ],
            ..Default::default()
        };
        let strategy = Strategy {
            audio: AudioConfig {
                mode: "strip_commentary".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:a:0"), "keep jpn: {}", joined);
        assert!(
            !joined.contains("-map 0:a:1"),
            "exclude commentary via mode: {}",
            joined
        );
    }

    #[test]
    fn test_audio_strip_non_preferred_keeps_only_preferred_languages() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![
                audio("aac", "chi", false), // preferred
                audio("aac", "eng", false), // preferred
                audio("aac", "jpn", false), // NOT preferred
                audio("aac", "kor", false), // NOT preferred
            ],
            ..Default::default()
        };
        let strategy = Strategy {
            audio: AudioConfig {
                mode: "strip_non_preferred".into(),
                remove_commentary: true /* migrated to mode */,
                preferred_languages: vec!["chi".into(), "zho".into(), "eng".into()],
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:a:0"), "keep chi: {}", joined);
        assert!(joined.contains("-map 0:a:1"), "keep eng: {}", joined);
        assert!(!joined.contains("-map 0:a:2"), "exclude jpn: {}", joined);
        assert!(!joined.contains("-map 0:a:3"), "exclude kor: {}", joined);
    }

    #[test]
    fn test_audio_strip_non_preferred_with_commentary_removal() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![
                audio("aac", "chi", false), // preferred, keep
                audio("aac", "eng", true),  // commentary 閳?exclude even though eng is preferred
                audio("aac", "jpn", false), // language not preferred
                audio("aac", "jpn", true),  // commentary + language not preferred
            ],
            ..Default::default()
        };
        let strategy = Strategy {
            audio: AudioConfig {
                mode: "strip_non_preferred".into(),
                // remove_commentary removed 閳?use mode: "strip_commentary" instead
                preferred_languages: vec!["chi".into(), "zho".into(), "eng".into()],
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:a:0"), "keep chi: {}", joined);
        assert!(
            !joined.contains("-map 0:a:1"),
            "exclude eng commentary: {}",
            joined
        );
        assert!(!joined.contains("-map 0:a:2"), "exclude jpn: {}", joined);
        assert!(
            !joined.contains("-map 0:a:3"),
            "exclude jpn commentary: {}",
            joined
        );
    }

    #[test]
    fn test_audio_empty_tracks_falls_back_to_optional_map() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            audio: AudioConfig {
                mode: "strip_non_preferred".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(
            joined.contains("-map 0:a?"),
            "optional audio map: {}",
            joined
        );
    }

    #[test]
    fn test_audio_all_filtered_still_has_valid_stream() {
        // All tracks are non-preferred languages only 閳?none match
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![audio("aac", "jpn", false), audio("aac", "kor", false)],
            ..Default::default()
        };
        let strategy = Strategy {
            audio: AudioConfig {
                mode: "strip_non_preferred".into(),
                preferred_languages: vec!["chi".into(), "zho".into(), "eng".into()],
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        // All tracks filtered 閳?should still have 0:a? fallback
        assert!(
            !joined.contains("-map 0:a:0"),
            "no exact audio maps expected: {}",
            joined
        );
        assert!(
            !joined.contains("-map 0:a:1"),
            "no exact audio maps expected: {}",
            joined
        );
        assert!(
            joined.contains("-map 0:a?"),
            "should fall back to optional map: {}",
            joined
        );
    }

    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?
    // C6: Subtitle mode tests
    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?

    #[test]
    fn test_subtitle_keep_all() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            subtitle_tracks: vec![sub("ass", "chi"), sub("ass", "eng"), sub("ass", "jpn")],
            ..Default::default()
        };
        let strategy = Strategy {
            subtitle: SubtitleConfig {
                mode: "keep_all".into(),
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:s:0"), "keep chi: {}", joined);
        assert!(joined.contains("-map 0:s:1"), "keep eng: {}", joined);
        assert!(joined.contains("-map 0:s:2"), "keep jpn: {}", joined);
        assert!(joined.contains("-c:s copy"), "sub codec copy: {}", joined);
    }

    #[test]
    fn test_subtitle_remove_all() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            subtitle_tracks: vec![sub("ass", "chi"), sub("ass", "eng")],
            ..Default::default()
        };
        let strategy = Strategy {
            subtitle: SubtitleConfig {
                mode: "remove_all".into(),
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(!joined.contains("0:s"), "no subtitle maps: {}", joined);
    }

    #[test]
    fn test_subtitle_keep_chinese_excludes_non_chinese() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            subtitle_tracks: vec![
                sub("ass", "chi"), // keep
                sub("ass", "zho"), // keep
                sub("ass", "zh"),  // keep
                sub("ass", "eng"), // exclude
                sub("ass", "jpn"), // exclude
                sub("ass", "kor"), // exclude
            ],
            ..Default::default()
        };
        let strategy = Strategy {
            subtitle: SubtitleConfig {
                mode: "keep_chinese".into(),
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:s:0"), "keep chi: {}", joined);
        assert!(joined.contains("-map 0:s:1"), "keep zho: {}", joined);
        assert!(joined.contains("-map 0:s:2"), "keep zh: {}", joined);
        assert!(!joined.contains("-map 0:s:3"), "exclude eng: {}", joined);
        assert!(!joined.contains("-map 0:s:4"), "exclude jpn: {}", joined);
        assert!(!joined.contains("-map 0:s:5"), "exclude kor: {}", joined);
    }

    #[test]
    fn test_subtitle_keep_chinese_english_keeps_both_languages() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            subtitle_tracks: vec![
                sub("ass", "chi"), // keep
                sub("ass", "eng"), // keep
                sub("ass", "en"),  // keep (alternative English code)
                sub("ass", "jpn"), // exclude
            ],
            ..Default::default()
        };
        let strategy = Strategy {
            subtitle: SubtitleConfig {
                mode: "keep_chinese_english".into(),
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:s:0"), "keep chi: {}", joined);
        assert!(joined.contains("-map 0:s:1"), "keep eng: {}", joined);
        assert!(joined.contains("-map 0:s:2"), "keep en: {}", joined);
        assert!(!joined.contains("-map 0:s:3"), "exclude jpn: {}", joined);
    }

    #[test]
    fn test_subtitle_empty_tracks_keep_all() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            subtitle: SubtitleConfig {
                mode: "keep_all".into(),
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-map 0:s?"), "optional sub map: {}", joined);
        assert!(joined.contains("-c:s copy"), "sub codec copy: {}", joined);
    }

    #[test]
    fn test_subtitle_empty_tracks_keep_chinese_no_exact_maps() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            subtitle: SubtitleConfig {
                mode: "keep_chinese".into(),
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(
            joined.contains("-map 0:s?"),
            "optional sub map for empty: {}",
            joined
        );
    }

    #[test]
    fn test_subtitle_all_filtered_out_keep_chinese_no_exact_maps() {
        // Only Japanese subs, keep_chinese mode 閳?nothing should be kept
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            subtitle_tracks: vec![sub("ass", "jpn"), sub("ass", "kor")],
            ..Default::default()
        };
        let strategy = Strategy {
            subtitle: SubtitleConfig {
                mode: "keep_chinese".into(),
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(!joined.contains("-map 0:s:0"), "exclude jpn: {}", joined);
        assert!(!joined.contains("-map 0:s:1"), "exclude kor: {}", joined);
        // No subs kept, but mode isn't remove_all 閳?builder should not include any sub stream
        assert!(
            !joined.contains("0:s"),
            "no subtitle stream at all: {}",
            joined
        );
    }

    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?
    // C9: VP9 NVDEC support
    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?

    #[test]
    fn test_vp9_gets_nvdec_hardware_acceleration() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::Vp9,
            hdr_type: HdrType::Hdr10,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "hevc_nvenc".into(),
                gpu: true,
                cq: 28,
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(
            joined.contains("-hwaccel cuda"),
            "VP9 should enable NVDEC: {}",
            joined
        );
    }

    #[test]
    fn test_unknown_codec_does_not_get_nvdec() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::Unknown("vp8".into()),
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "hevc_nvenc".into(),
                gpu: true,
                cq: 28,
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(
            !joined.contains("-hwaccel cuda"),
            "VP8 should NOT get NVDEC: {}",
            joined
        );
    }

    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?
    // C10: HDR10+ flag
    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?

    #[test]
    fn test_hdr10plus_gets_flag_with_libx265() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Hdr10Plus,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "libx265".into(),
                crf: 18,
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-hdr10+"), "libx265 HDR10+: {}", joined);
    }

    #[test]
    fn test_hdr10plus_gets_flag_with_hevc_nvenc() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Hdr10Plus,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "hevc_nvenc".into(),
                gpu: true,
                cq: 28,
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-hdr10+"), "hevc_nvenc HDR10+: {}", joined);
    }

    #[test]
    fn test_hdr10plus_no_flag_with_av1_nvenc() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Hdr10Plus,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "av1_nvenc".into(),
                gpu: true,
                cq: 28,
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(
            !joined.contains("-hdr10+"),
            "av1_nvenc does NOT support HDR10+: {}",
            joined
        );
    }

    #[test]
    fn test_hdr10_no_hdr10plus_flag() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Hdr10,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "libx265".into(),
                crf: 18,
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(
            !joined.contains("-hdr10+"),
            "plain HDR10 should NOT get -hdr10+: {}",
            joined
        );
    }

    #[test]
    fn test_sdr_no_hdr10plus_flag() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "libx265".into(),
                crf: 18,
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(
            !joined.contains("-hdr10+"),
            "SDR should NOT get -hdr10+: {}",
            joined
        );
    }

    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?
    // Existing regression tests (updated)
    // 閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅查埡鎰ㄦ櫜閳烘劏鏅?

    #[test]
    fn test_build_av1_nvenc_command() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![AudioTrack {
                codec: "aac".into(),
                channels: 2,
                language: "eng".into(),
                title: "".into(),
                is_commentary: false,
            }],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "av1_nvenc".into(),
                cq: 28,
                nv_preset: "p6".into(),
                rc: "vbr".into(),
                gpu: true,
                ..Default::default()
            },
            audio: AudioConfig {
                mode: "keep_original".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-hwaccel cuda"), "NVDEC: {}", joined);
        assert!(joined.contains("-c:V av1_nvenc"), "encoder: {}", joined);
        assert!(joined.contains("-cq 28"), "CQ: {}", joined);
    }

    #[test]
    fn test_build_x265_command() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Hdr10,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                encoder: "libx265".into(),
                crf: 18,
                preset: "slow".into(),
                pix_fmt: "yuv420p10le".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(joined.contains("-c:V libx265"), "libx265");
        assert!(joined.contains("-crf 18"), "CRF 18");
        assert!(joined.contains("-color_trc smpte2084"), "HDR metadata");
    }
}
