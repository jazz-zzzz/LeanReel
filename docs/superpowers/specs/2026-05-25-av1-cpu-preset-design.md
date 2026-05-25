# LeanReel AV1/CPU Preset Design

Date: 2026-05-25

## Goal

Replace the current broad preset set with three real transcode presets:

1. AV1 NVENC balanced fast
2. AV1 NVENC quality fast
3. CPU x265 quality-first compression

`HEVC/H.265` GPU presets are removed from the main preset set. The intent is to match the user's device reality:

- RTX 4070 Ti SUPER supports AV1 NVENC encoding.
- iPhone Air and future M4+ MacBook support AV1 playback.
- Xiaomi TV direct playback is a secondary compatibility concern and should be tested separately if direct-play matters.

## Sources Used

- Local FFmpeg bundled with LeanReel:
  - `ffmpeg -hide_banner -h encoder=av1_nvenc`
  - `ffmpeg -hide_banner -h encoder=hevc_nvenc`
  - `ffmpeg -hide_banner -encoders`
- User PDF in project root:
  - `视频压缩大测试结果报告：CPU编码、显卡编码、H264、H265、AV1 - 知乎.pdf`
- NVIDIA Video Codec SDK documentation:
  - NVENC supports H.264, HEVC, and AV1 bitstream generation.
  - Presets move from high performance to high quality as P1 through P7.
  - https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html
- x265 official documentation:
  - Slower presets spend more CPU to improve compression efficiency at the selected quality.
  - CRF is quality-targeted rate control; final size depends on source complexity.
  - https://x265.readthedocs.io/en/stable/presets.html
- Apple iPhone Air technical specifications:
  - AV1 playback is listed as a supported format.
  - https://www.apple.com/iphone-air/specs/

## Parameter Basis

The PDF gives a comparable-quality range of:

- `libx265 -crf 25`
- `av1_nvenc -cq 34~36`

The user requirement is not merely "similar quality to x265 CRF 25"; it is personal archive compression where output should avoid visible degradation. Therefore LeanReel should use the PDF range as a scale reference, then bias the chosen AV1 values toward quality:

- `CQ34` as balanced AV1: inside the PDF's comparable range, at the quality side of `34~36`.
- `CQ32` as quality AV1: two CQ steps more conservative than the PDF comparable range.
- `CRF18 slow` as CPU quality-first: substantially more conservative than common x265 CRF 20-25 compression settings.

Local FFmpeg confirms:

- `av1_nvenc -preset p5`: slow, good quality.
- `av1_nvenc -preset p6`: slower, better quality.
- `av1_nvenc -rc vbr -cq <value>` is supported, and `-cq` is valid from `0` to `63`.
- `-spatial-aq`, `-temporal-aq`, and `-aq-strength 1..15` are supported for AV1 NVENC.

## Final Presets

| Preset | Encoder | Rate control | Preset | Expected use |
| --- | --- | --- | --- | --- |
| AV1 NVENC CQ34 Balanced | `av1_nvenc` | `-rc vbr -cq 34` | `p5` | Default batch compression for SDR H.264 sources. Fast, usually meaningfully smaller than source. |
| AV1 NVENC CQ32 Quality | `av1_nvenc` | `-rc vbr -cq 32` | `p6` | GPU path when quality has priority over maximum saving. Still much faster than CPU. |
| CPU x265 CRF18 Slow | `libx265` | `-crf 18` | `slow` | Slow archival fallback for near-transparent quality with strong compression efficiency. |

## Expected Effects

These are estimates, not guarantees. CRF/CQ modes target quality, not file size.

| Preset | Time | Visual quality | Size tendency |
| --- | --- | --- | --- |
| AV1 CQ34 p5 | Fastest | Good to near-transparent on typical SDR H.264 | Best practical speed/size balance |
| AV1 CQ32 p6 | Fast | Better than CQ34, less aggressive | Larger than CQ34, still often smaller than source |
| CPU x265 CRF18 slow | Slowest | Highest confidence near-transparent result | Often smaller than CQ32 at similar perceived quality, but costs much more time |

For the user's BONY-024 sample:

- Source: H.264 1080p SDR, about 4.46 GB, about 2h40m, about 3.7 Mbps.
- This is already not a very high bitrate source.
- GPU output can still become larger if CQ is too conservative or the source is already bitrate-starved.
- LeanReel must continue deleting/discarding outputs that are not smaller than source.

## Compatibility

AV1 should be the main path for this user because the primary playback devices support AV1:

- iPhone Air: AV1 playback support.
- M4+ MacBook target: AV1 decode support.
- RTX 4070 Ti SUPER: AV1 NVENC encode support.

Unknown Xiaomi TV compatibility remains a watch item. If direct playback on that TV becomes important, add a one-file AV1 direct-play test before committing the whole library.

## Hardening Requirements

- Do not show AV1 presets when the active FFmpeg build does not expose `av1_nvenc`.
- Do not rely on generic "has NVENC"; filter GPU presets by exact encoder availability.
- AV1 outputs should use `.mkv` to avoid writing AV1 video into weak or unsuitable source containers such as `.ts`.
- Do not emit encoder-specific flags that the selected encoder does not support.
- Preserve existing skip behavior for HEVC, HDR10, HDR10+, and Dolby Vision sources.
- Keep post-encode discard behavior when output size is greater than or equal to source size.
