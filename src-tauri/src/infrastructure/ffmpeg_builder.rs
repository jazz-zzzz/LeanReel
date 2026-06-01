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
    let mut cmd: Vec<String> = vec![
        ffmpeg_path.to_string(),
        "-nostdin".into(),
        "-y".into(),
        "-fflags".into(),
        "+genpts+discardcorrupt".into(),
    ];
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
    cmd.push("-map".into());
    cmd.push("0:a?".into());
    cmd.push("-c:a".into());
    cmd.push("copy".into());
    cmd.push("-map".into());
    cmd.push("0:s?".into());
    cmd.push("-c:s".into());
    cmd.push("copy".into());
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

    #[test]
    fn test_audio_and_subtitle_streams_are_always_copied() {
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![AudioTrack {
                codec: "aac".into(),
                channels: 2,
                language: "jpn".into(),
                title: "commentary".into(),
                is_commentary: true,
            }],
            subtitle_tracks: vec![SubtitleTrack {
                codec: "ass".into(),
                language: "jpn".into(),
                title: "".into(),
                is_forced: false,
            }],
            ..Default::default()
        };
        let strategy = Strategy {
            audio: AudioConfig {
                mode: "strip_commentary".into(),
                ..Default::default()
            },
            subtitle: SubtitleConfig {
                mode: "remove_all".into(),
            },
            ..Default::default()
        };
        let joined = cmd_joined(&snap, &strategy);
        assert!(
            joined.contains("-map 0:a? -c:a copy"),
            "audio copy: {}",
            joined
        );
        assert!(
            joined.contains("-map 0:s? -c:s copy"),
            "subtitle copy: {}",
            joined
        );
        assert!(
            !joined.contains("-map 0:a:"),
            "no exact audio maps: {}",
            joined
        );
        assert!(
            !joined.contains("-map 0:s:"),
            "no exact subtitle maps: {}",
            joined
        );
    }
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
