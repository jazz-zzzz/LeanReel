"""FFprobe 封装测试"""
import pytest
from leanreel.executor.probe import FFprobeRunner, parse_ffprobe_output

SAMPLE_FFPROBE_JSON = """
{
  "format": {
    "filename": "test.mkv",
    "duration": "6420.5",
    "size": "50000000000",
    "bit_rate": "50000000"
  },
  "streams": [
    {
      "index": 0,
      "codec_type": "video",
      "codec_name": "hevc",
      "width": 3840,
      "height": 2160,
      "color_primaries": "bt2020",
      "color_transfer": "smpte2084",
      "pix_fmt": "yuv420p10le",
      "side_data_list": [
        { "side_data_type": "Dolby Vision configuration", "dv_profile": "7" }
      ]
    },
    {
      "index": 1,
      "codec_type": "audio",
      "codec_name": "truehd",
      "channels": 8,
      "tags": {"language": "eng", "title": "Atmos"},
      "disposition": {"comment": 0}
    },
    {
      "index": 2,
      "codec_type": "subtitle",
      "codec_name": "hdmv_pgs",
      "tags": {"language": "chi"}
    }
  ]
}
"""

def test_parse_basic_metadata():
    import json
    data = json.loads(SAMPLE_FFPROBE_JSON)
    snap = parse_ffprobe_output(data, 1)
    assert snap.file_name == "test.mkv"
    assert snap.size_bytes == 50000000000
    assert snap.video_codec == "hevc"
    assert snap.video_width == 3840
    assert snap.video_height == 2160
    assert snap.hdr_type == "DV_P7"
    assert snap.duration_seconds == pytest.approx(6420.5)
    assert snap.bitrate_bps == 50000000

def test_parse_audio_tracks():
    import json
    data = json.loads(SAMPLE_FFPROBE_JSON)
    snap = parse_ffprobe_output(data, 1)
    assert len(snap.audio_tracks) == 1
    assert snap.audio_tracks[0].codec == "truehd"
    assert snap.audio_tracks[0].channels == 8
    assert snap.audio_tracks[0].language == "eng"

def test_parse_subtitle_tracks():
    import json
    data = json.loads(SAMPLE_FFPROBE_JSON)
    snap = parse_ffprobe_output(data, 1)
    assert len(snap.subtitle_tracks) == 1
    assert snap.subtitle_tracks[0].language == "chi"

def test_detect_dv_profile_7():
    import json
    data = json.loads(SAMPLE_FFPROBE_JSON)
    snap = parse_ffprobe_output(data, 1)
    assert snap.hdr_type == "DV_P7"

def test_detect_hdr10():
    import json
    data = json.loads(SAMPLE_FFPROBE_JSON)
    # Remove DV side_data
    stream = data["streams"][0]
    stream.pop("side_data_list", None)
    snap = parse_ffprobe_output(data, 1)
    assert snap.hdr_type == "HDR10"

def test_detect_sdr():
    import json
    data = json.loads(SAMPLE_FFPROBE_JSON)
    data["streams"][0]["color_primaries"] = "bt709"
    data["streams"][0]["color_transfer"] = "bt709"
    data["streams"][0].pop("side_data_list", None)
    snap = parse_ffprobe_output(data, 1)
    assert snap.hdr_type == "SDR"
