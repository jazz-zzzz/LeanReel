# AV1/CPU Preset Implementation Plan

> **For groun:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan step-by-step.

**Goal:** Replace LeanReel's main transcode presets with two AV1 NVENC presets and one CPU x265 preset, with tests and code hardening so unsupported encoders and unsafe output containers are handled predictably.

**Architecture:** Keep `Strategy` as the preset contract. Update bundled strategy JSON resources, then harden the two places that turn strategies into behavior: GPU prioritization and FFmpeg/output-path construction.

**Tech Stack:** Python, PySide6 UI, pytest, bundled FFmpeg.

---

### Task 1: Add boundary tests before production changes

**Files:**
- `tests/test_strategy.py`
- `tests/test_ffmpeg.py`
- `tests/test_main.py`
- `tests/test_encoding_controller.py`

**Steps:**

1. Add a resource test that loads `leanreel/resources/strategies` and asserts the preset names and order are exactly:
   - `AV1 NVENC CQ34 均衡快速`
   - `AV1 NVENC CQ32 保画质`
   - `CPU x265 CRF18 慢速保画质`
2. Assert the two AV1 presets use `encoder=av1_nvenc`, `gpu=true`, `rc=vbr`, CQ values `34` and `32`, and NV presets `p5` and `p6`.
3. Assert the CPU preset uses `encoder=libx265`, `crf=18`, `preset=slow`, and `pix_fmt=yuv420p10le`.
4. Add an FFmpeg builder test for AV1 NVENC that asserts the command includes `-c:V av1_nvenc`, `-rc vbr`, `-cq 34`, AQ flags, and no `-crf`.
5. Add a builder test for AV1 plus `HDR10+` asserting the command does not emit `-hdr10+`.
6. Add an output path test asserting an AV1 strategy converts `Movie.ts` to `Movie_zcompressed.mkv`.
7. Add a prioritization test asserting exact encoder availability filters GPU presets:
   - If only `hevc_nvenc` is available, AV1 presets are not selected.
   - If `av1_nvenc` is available, AV1 presets are selected.

**Verification:** Run the targeted tests and confirm they fail before implementation:

```powershell
python -m pytest tests/test_strategy.py tests/test_ffmpeg.py tests/test_main.py tests/test_encoding_controller.py -q
```

---

### Task 2: Update bundled strategy resources

**Files:**
- `leanreel/resources/strategies/*.json`

**Steps:**

1. Replace the current eight strategy JSON files with exactly three bundled preset JSON files:
   - `av1_balanced.json`
   - `av1_quality.json`
   - `x265_quality.json`
2. Use UTF-8 Chinese text without mojibake.
3. Remove HEVC NVENC and copy-stream entries from the main preset resources.
4. Keep audio/subtitle behavior conservative:
   - Audio: `keep_original`, `remove_commentary=false`
   - Subtitle: `keep_all`
5. Keep `filters.skip_x265=true` to preserve HEVC source skip behavior.

---

### Task 3: Harden GPU encoder detection

**Files:**
- `leanreel/utils/gpu.py`
- `leanreel/services/strategy_utils.py`
- `tests/test_main.py`

**Steps:**

1. Add `available_nvenc_encoders()` returning a set of exact encoder names from `ffmpeg -encoders`.
2. Keep `has_nvenc()` as a compatibility wrapper returning true when the set is non-empty.
3. Update `_prioritize_strategies()` to filter GPU strategies by `strategy.video.encoder in available_nvenc_encoders()`.
4. Preserve CPU fallback behavior when no compatible GPU strategy is available.

---

### Task 4: Harden FFmpeg builder and output path behavior

**Files:**
- `leanreel/executor/ffmpeg_builder.py`
- `leanreel/controllers/encoding_controller.py`
- `tests/test_ffmpeg.py`
- `tests/test_encoding_controller.py`

**Steps:**

1. Add a small helper in `ffmpeg_builder.py` for HDR color metadata to avoid duplicate logic.
2. Add a small helper for HDR10+ dynamic metadata support:
   - allow `-hdr10+` for `libx265`
   - allow `-hdr10+` for `hevc_nvenc`
   - do not emit it for `av1_nvenc`
3. Update `make_output_path(source, strategy=None)`:
   - default behavior remains same suffix.
   - for `av1_nvenc`, output suffix becomes `.mkv`.
4. Update `build_encode_tasks()` to pass the selected strategy into `make_output_path()`.

---

### Task 5: Update custom UI encoder list

**Files:**
- `leanreel/gui/strategy_panel.py`

**Steps:**

1. Add `av1_nvenc` to `_GPU_ENCODERS`.
2. Increase custom CQ spin range to `0..63`, matching local FFmpeg `av1_nvenc`.
3. Adjust GPU savings text so AV1 CQ values above 28 do not imply HEVC-era assumptions too strongly.

---

### Task 6: Run verification

**Commands:**

```powershell
python -m pytest tests/test_strategy.py tests/test_ffmpeg.py tests/test_main.py tests/test_encoding_controller.py -q
python -m pytest -q
```

**Expected:** Targeted tests pass. Full suite passes or any unrelated pre-existing failures are documented precisely.
