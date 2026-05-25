# LeanReel FFmpeg Builder Contract

Date: 2026-05-26

## Purpose

`FFmpegBuilder` has one job: turn a `FileSnapshot` and a `Strategy` into a command line that is syntactically valid, conservative with streams, and safe for both built-in presets and custom strategies.

The builder does not promise that every run will encode successfully on every machine. Runtime success still depends on the selected FFmpeg binary, NVIDIA driver, hardware support, source corruption, disk space, and container quirks. What it must guarantee is stricter and testable:

- It rejects unknown video encoders before FFmpeg is launched.
- It never emits options that are known to belong to another encoder family.
- It uses optional stream mapping for resources that may not exist.
- It preserves non-video resources by default unless the strategy explicitly removes or filters them.
- Built-in presets and custom strategies share the same command construction path.

## Authoritative Inputs

- FFmpeg stream selection and `-map` semantics: `https://ffmpeg.org/ffmpeg.html`
- FFmpeg encoder option reference: `https://ffmpeg.org/ffmpeg-codecs.html`
- NVIDIA Video Codec SDK NVENC guide: `https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html`
- NVIDIA FFmpeg with GPU guide: `https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/ffmpeg-with-nvidia-gpu/index.html`
- x265 preset documentation: `https://x265.readthedocs.io/en/stable/presets.html`
- Local bundled FFmpeg help:
  - `leanreel/resources/ffmpeg/ffmpeg.exe -hide_banner -h encoder=av1_nvenc`
  - `leanreel/resources/ffmpeg/ffmpeg.exe -hide_banner -h encoder=hevc_nvenc`
  - `leanreel/resources/ffmpeg/ffmpeg.exe -hide_banner -h encoder=h264_nvenc`
  - `leanreel/resources/ffmpeg/ffmpeg.exe -hide_banner -h encoder=libx265`

## Encoder Specification Table

All video encoder behavior is anchored in `ENCODER_SPECS` in `leanreel/executor/ffmpeg_builder.py`.

| Encoder | Kind | Quality option | Valid range | Default preset | HDR10+ flag |
| --- | --- | --- | --- | --- | --- |
| `copy` | Copy | None | None | None | No |
| `libx265` | x265 | `-crf` | `0..51` | `slow` | Yes |
| `av1_nvenc` | NVENC | `-cq` | `0..63` | `p4` | No |
| `hevc_nvenc` | NVENC | `-cq` | `0..51` | `p4` | Yes |
| `h264_nvenc` | NVENC | `-cq` | `0..51` | `p4` | No |

This is the extension point for future encoders. Adding a new encoder should mean adding one spec and then adding tests for its command family. Call sites should not grow isolated encoder-specific patches.

## Stream Mapping Rules

Concrete track indexes are used only when the snapshot confirms a specific stream exists:

- `0:a:0`, `0:a:1`, etc. for selected audio tracks.
- `0:s:0`, `0:s:1`, etc. for selected subtitle tracks.

Fallback or whole-resource mappings must be optional:

- Audio fallback: `-map 0:a? -c:a copy`
- Subtitle fallback: `-map 0:s? -c:s copy`
- Attachment fallback: `-map 0:t? -c:t copy`
- Data fallback: `-map 0:d? -c:d copy`

This protects video-only inputs, no-subtitle inputs, filtered-to-empty audio sets, missing attachments, and formats that simply do not contain data streams.

## Encoder Family Rules

NVENC encoders use:

- `-c:V <encoder>`
- `-preset p1..p7`
- `-rc vbr|cbr|constqp`
- `-cq <clamped range>`
- `-spatial-aq 1`
- `-temporal-aq 1`
- `-aq-strength 8`

`libx265` uses:

- `-c:V libx265`
- `-crf <0..51>`
- `-preset <x265 preset>`
- `-pix_fmt <format or default>`
- optional `-x265-params <value>`

`copy` uses:

- `-c:V copy`

No branch should emit `-crf` for NVENC or `-cq`/AQ flags for x265.

## Guard Rails

- Unknown encoder names raise `ValueError`.
- Invalid NVENC presets fall back to the encoder spec default.
- Invalid NVENC rate-control values fall back to `vbr`.
- CQ and CRF values are clamped to the local FFmpeg encoder range.
- HDR color metadata is centralized.
- HDR10+ signaling is only added for encoders that declare support in `ENCODER_SPECS`.
- `-copy_unknown`, metadata mapping, chapter mapping, attachments, and data streams remain part of the default command.

## Current Test Gate

`tests/test_ffmpeg.py` covers:

- All supported encoder specs as the single source of truth.
- All built-in presets on a video-only source.
- All custom encoder choices on a video-only source.
- Audio fallback when probe data is absent.
- Audio fallback when filtering removes every known audio track.
- Commentary and language filtering by explicit stream index.
- AV1 NVENC CQ command shape.
- NVENC CQ clamping per encoder range.
- Invalid NVENC RC and preset fallback.
- x265 CRF clamping and preset fallback.
- Unknown encoder rejection.

Required local gate:

```powershell
py -m pytest tests/test_ffmpeg.py -q
py -m pytest -q
```

