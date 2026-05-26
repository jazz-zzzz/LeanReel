"""Application wiring helpers."""
from pathlib import Path
import json

from leanreel.domain.models import Strategy
from leanreel.domain.models import FileSnapshot, HDRType
from leanreel.executor.worker import EncodeTask
from leanreel.domain.models import TaskStatus
from leanreel.controllers.encoding_controller import build_encode_tasks, make_output_path, compute_encode_summary


def test_make_output_path_adds_suffix_without_overwriting_original():
    source = Path("C:/media/Movie.mkv")

    assert make_output_path(source) == Path("C:/media/Movie_zcompressed.mkv")


def test_make_output_path_uses_mkv_for_av1_strategy():
    source = Path("C:/media/Movie.ts")
    strategy = Strategy.from_dict({
        "name": "AV1 NVENC CQ34 均衡快速",
        "video": {"encoder": "av1_nvenc", "gpu": True},
        "filters": {},
    })

    assert make_output_path(source, strategy) == Path("C:/media/Movie_zcompressed.mkv")


def test_prioritize_strategies_filters_gpu_by_exact_encoder(monkeypatch):
    import leanreel.services.strategy_utils as strategy_utils

    av1 = Strategy.from_dict({
        "name": "AV1",
        "video": {"encoder": "av1_nvenc", "gpu": True},
        "filters": {},
    })
    hevc = Strategy.from_dict({
        "name": "HEVC",
        "video": {"encoder": "hevc_nvenc", "gpu": True},
        "filters": {},
    })
    cpu = Strategy.from_dict({
        "name": "CPU",
        "video": {"encoder": "libx265"},
        "filters": {},
    })

    monkeypatch.setattr(strategy_utils, "available_nvenc_encoders", lambda: {"hevc_nvenc"})
    assert [s.name for s in strategy_utils._prioritize_strategies([av1, hevc, cpu])] == ["HEVC", "CPU"]

    monkeypatch.setattr(strategy_utils, "available_nvenc_encoders", lambda: {"av1_nvenc"})
    assert [s.name for s in strategy_utils._prioritize_strategies([av1, hevc, cpu])] == ["AV1", "CPU"]


def test_prioritize_strategies_hides_unsupported_gpu_but_keeps_cpu(monkeypatch):
    import leanreel.services.strategy_utils as strategy_utils

    av1 = Strategy.from_dict({
        "name": "AV1",
        "video": {"encoder": "av1_nvenc", "gpu": True},
        "filters": {},
    })
    cpu = Strategy.from_dict({
        "name": "CPU",
        "video": {"encoder": "libx265"},
        "filters": {},
    })

    monkeypatch.setattr(strategy_utils, "available_nvenc_encoders", lambda: {"hevc_nvenc"})

    assert [s.name for s in strategy_utils._prioritize_strategies([av1, cpu])] == ["CPU"]


def test_get_strategies_dir_refreshes_builtin_strategy_files(monkeypatch, tmp_path):
    from leanreel.utils import paths as paths_mod

    monkeypatch.setattr(paths_mod, "get_data_dir", lambda: tmp_path)
    user_dir = tmp_path / "strategies"
    user_dir.mkdir()
    (user_dir / "balanced.json").write_text(
        '{"name": "旧内置预设", "is_preset": true}',
        encoding="utf-8",
    )
    (user_dir / "av1_quality.json").write_text(
        '{"name": "AV1 NVENC CQ32 保画质", "is_preset": true}',
        encoding="utf-8",
    )
    (user_dir / "av1_balanced.json").write_text(
        '{"name": "AV1 NVENC CQ34 均衡快速", "is_preset": true}',
        encoding="utf-8",
    )
    (user_dir / "x265_quality.json").write_text(
        '{"name": "CPU x265 CRF18 慢速保画质", "is_preset": true}',
        encoding="utf-8",
    )
    (user_dir / "my_custom.json").write_text(
        '{"name": "我的自定义策略", "is_preset": false}',
        encoding="utf-8",
    )

    strategies_dir = paths_mod.get_strategies_dir()

    av1_quality = json.loads((strategies_dir / "01_av1_cq32_quality.json").read_text(encoding="utf-8"))
    custom = json.loads((strategies_dir / "my_custom.json").read_text(encoding="utf-8"))
    assert av1_quality["name"] == "AV1 NVENC CQ32 保画质"
    assert not (strategies_dir / "balanced.json").exists()
    assert not (strategies_dir / "av1_quality.json").exists()
    assert not (strategies_dir / "av1_balanced.json").exists()
    assert not (strategies_dir / "x265_quality.json").exists()
    assert custom["name"] == "我的自定义策略"

def test_init_services_does_not_run_nvenc_detection_synchronously(monkeypatch, tmp_path):
    import leanreel.main as main_mod
    from leanreel.utils import gpu as gpu_mod

    strategy_file = tmp_path / "balanced.json"
    strategy_file.write_text(
        '{"name": "CPU", "video": {"encoder": "libx265"}, "filters": {}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(main_mod, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(main_mod, "get_strategies_dir", lambda: tmp_path)
    monkeypatch.setattr(
        gpu_mod,
        "has_nvenc",
        lambda: (_ for _ in ()).throw(AssertionError("NVENC detection must be deferred")),
    )

    app_like = type("AppLike", (), {})()
    main_mod.Application._init_services(app_like)

    assert [s.name for s in app_like.services.strategies] == ["CPU"]


def test_build_encode_tasks_uses_strategy_and_reconstructs_input_path():
    strategy = Strategy.from_dict({
        "name": "均衡压缩",
        "video": {"encoder": "libx265"},
        "filters": {},
    })
    snapshots = [
        FileSnapshot(
            library_folder_id=7,
            relative_path="Season 1/Episode 1.mkv",
            file_name="Episode 1.mkv",
            video_codec="h264",
        )
    ]

    tasks = build_encode_tasks(snapshots, {7: "D:/TV"}, strategy)

    assert len(tasks) == 1
    assert tasks[0].input_path == str(Path("D:/TV") / "Season 1/Episode 1.mkv")
    assert tasks[0].output_path == str(Path("D:/TV") / "Season 1/Episode 1_zcompressed.mkv")
    assert tasks[0].strategy is strategy
    assert tasks[0].snapshot is snapshots[0]
    assert tasks[0].strategy_name == "均衡压缩"


def test_build_encode_tasks_supports_per_file_strategy_overrides():
    default_strategy = Strategy.from_dict({
        "name": "均衡压缩",
        "video": {"encoder": "libx265"},
        "filters": {},
    })
    custom_strategy = Strategy.from_dict({
        "name": "自定义",
        "video": {"encoder": "libx265", "crf": 22},
        "filters": {},
    })
    snapshots = [
        FileSnapshot(library_folder_id=7, relative_path="a.mkv", file_name="a.mkv"),
        FileSnapshot(library_folder_id=7, relative_path="b.mkv", file_name="b.mkv"),
    ]

    tasks = build_encode_tasks(
        snapshots,
        {7: "D:/Movies"},
        default_strategy,
        {(7, "b.mkv"): custom_strategy},
    )

    assert [task.strategy_name for task in tasks] == ["均衡压缩", "自定义"]
    assert tasks[1].strategy is custom_strategy


def test_build_encode_tasks_skips_snapshots_with_unknown_folder():
    strategy = Strategy.from_dict({
        "name": "均衡压缩",
        "video": {"encoder": "libx265"},
        "filters": {},
    })
    snapshots = [
        FileSnapshot(library_folder_id=7, relative_path="a.mkv", file_name="a.mkv"),
        FileSnapshot(library_folder_id=99, relative_path="orphan.mkv", file_name="orphan.mkv"),
    ]

    tasks = build_encode_tasks(snapshots, {7: "D:/TV"}, strategy)

    assert len(tasks) == 1
    assert tasks[0].file_name == "a.mkv"


def test_build_encode_tasks_skips_hevc_and_hdr_sources_even_when_checked():
    strategy = Strategy.from_dict({
        "name": "x265 HEVC CRF 20 标准转码",
        "video": {"encoder": "libx265"},
        "filters": {},
    })
    snapshots = [
        FileSnapshot(library_folder_id=7, relative_path="sdr-h264.mkv", file_name="sdr-h264.mkv", video_codec="h264"),
        FileSnapshot(library_folder_id=7, relative_path="hevc.mkv", file_name="hevc.mkv", video_codec="hevc"),
        FileSnapshot(library_folder_id=7, relative_path="hdr.mkv", file_name="hdr.mkv", video_codec="h264", hdr_type=HDRType.HDR10),
        FileSnapshot(library_folder_id=7, relative_path="dv.mkv", file_name="dv.mkv", video_codec="h264", hdr_type=HDRType.DV_P7),
    ]

    tasks = build_encode_tasks(snapshots, {7: "D:/Movies"}, strategy)

    assert [task.file_name for task in tasks] == ["sdr-h264.mkv"]


def test_build_encode_tasks_returns_empty_list_for_empty_snapshots():
    strategy = Strategy.from_dict({
        "name": "均衡压缩",
        "video": {"encoder": "libx265"},
        "filters": {},
    })

    tasks = build_encode_tasks([], {7: "D:/TV"}, strategy)

    assert tasks == []


def test_compute_encode_summary_counts_completed_and_failed():
    tasks = [
        EncodeTask(file_name="a.mkv", input_path="/in/a.mkv", output_path="/out/a.mkv"),
        EncodeTask(file_name="b.mkv", input_path="/in/b.mkv", output_path="/out/b.mkv"),
        EncodeTask(file_name="c.mkv", input_path="/in/c.mkv", output_path="/out/c.mkv"),
        EncodeTask(file_name="d.mkv", input_path="/in/d.mkv", output_path="/out/d.mkv"),
    ]
    tasks[0].status = TaskStatus.COMPLETED
    tasks[1].status = TaskStatus.COMPLETED
    tasks[2].status = TaskStatus.FAILED
    tasks[3].status = TaskStatus.SKIPPED

    done, failed, cancelled = compute_encode_summary(tasks)

    assert done == 2
    assert failed == 1
    assert cancelled == 0


def test_build_encode_tasks_sets_original_size_from_snapshot():
    from leanreel.controllers.encoding_controller import build_encode_tasks
    from leanreel.domain.models import Strategy
    from leanreel.domain.models import FileSnapshot

    snap = FileSnapshot(
        library_folder_id=1,
        relative_path="movie.mkv",
        file_name="movie.mkv",
        size_bytes=987654321,
    )
    strategy = Strategy(name="Balanced")

    tasks = build_encode_tasks([snap], {1: "C:/media"}, strategy)

    assert len(tasks) == 1
    assert tasks[0].original_size == 987654321


def test_compute_encode_summary_returns_zero_for_all_pending():
    tasks = [
        EncodeTask(file_name="a.mkv", input_path="/in/a.mkv", output_path="/out/a.mkv"),
        EncodeTask(file_name="b.mkv", input_path="/in/b.mkv", output_path="/out/b.mkv"),
    ]

    done, failed, cancelled = compute_encode_summary(tasks)

    assert done == 0
    assert failed == 0


def test_remove_folder_state_filters_snapshots_and_paths():
    from leanreel.main import remove_folder_from_current_state
    from leanreel.domain.models import FileSnapshot

    snapshots = [
        FileSnapshot(library_folder_id=1, relative_path="a.mkv"),
        FileSnapshot(library_folder_id=2, relative_path="b.mkv"),
    ]
    folder_paths = {1: "C:/one", 2: "C:/two"}
    overrides = {"a.mkv": object(), "b.mkv": object()}

    new_snapshots, new_paths, new_overrides = remove_folder_from_current_state(
        snapshots, folder_paths, overrides, folder_id=1
    )

    assert [s.relative_path for s in new_snapshots] == ["b.mkv"]
    assert new_paths == {2: "C:/two"}
    assert list(new_overrides) == ["b.mkv"]


def test_remove_folder_state_preserves_tuple_overrides_for_remaining_folders():
    from leanreel.main import remove_folder_from_current_state
    from leanreel.domain.models import FileSnapshot

    keep = object()
    drop = object()
    snapshots = [
        FileSnapshot(library_folder_id=1, relative_path="a.mkv"),
        FileSnapshot(library_folder_id=2, relative_path="b.mkv"),
    ]
    folder_paths = {1: "C:/one", 2: "C:/two"}
    overrides = {
        (1, "a.mkv"): drop,
        (2, "b.mkv"): keep,
    }

    _snapshots, _paths, new_overrides = remove_folder_from_current_state(
        snapshots, folder_paths, overrides, folder_id=1
    )

    assert new_overrides == {(2, "b.mkv"): keep}


def test_folder_removed_accepts_scan_populate_callback_signature():
    from types import SimpleNamespace

    from leanreel.controllers.library_controller import LibraryController
    from leanreel.domain.models import FileSnapshot

    refreshed = []
    removed = []
    state = SimpleNamespace(
        current_snapshots=[
            FileSnapshot(library_folder_id=1, relative_path="a.mkv"),
            FileSnapshot(library_folder_id=2, relative_path="b.mkv"),
        ],
        current_folder_paths={1: "C:/one", 2: "C:/two"},
        strategy_overrides={},
    )
    ctrl = LibraryController(
        state=state,
        services=SimpleNamespace(
            lib_mgr=SimpleNamespace(
                remove_folder=lambda folder_id: removed.append(folder_id),
                get_all_libraries=lambda: [],
                get_folders=lambda lib_id: [],
            )
        ),
        lib_panel=SimpleNamespace(populate=lambda libs, folders: None),
        file_panel=SimpleNamespace(),
        win=SimpleNamespace(set_status=lambda text: None),
        notifier=SimpleNamespace(),
        on_file_list_refresh=lambda snapshots: refreshed.append(list(snapshots)),
    )

    ctrl._on_folder_removed(1)

    assert removed == [1]
    assert [s.relative_path for s in refreshed[0]] == ["b.mkv"]


def test_folder_added_switches_current_state_to_target_library_and_triggers_probe():
    from types import SimpleNamespace

    from leanreel.controllers.library_controller import LibraryController
    from leanreel.domain.models import FileSnapshot, LibraryFolder

    probed = []
    old_snapshot = FileSnapshot(library_folder_id=1, relative_path="old.mkv")
    new_folder = LibraryFolder(id=20, library_id=2, path="C:/new")
    state = SimpleNamespace(
        current_library_id=1,
        current_snapshots=[old_snapshot],
        current_folder_paths={1: "C:/old"},
        strategy_overrides={(1, "old.mkv"): object()},
    )
    ctrl = LibraryController(
        state=state,
        services=SimpleNamespace(
            lib_mgr=SimpleNamespace(
                add_folder=lambda lib_id, path: new_folder,
                get_all_libraries=lambda: [],
                get_folders=lambda lib_id: [new_folder],
            )
        ),
        lib_panel=SimpleNamespace(populate=lambda libs, folders: None),
        file_panel=SimpleNamespace(),
        win=SimpleNamespace(set_status=lambda text: None),
        notifier=SimpleNamespace(),
        on_folder_probe=lambda folder_id, path: probed.append((folder_id, path)),
    )

    ctrl._on_folder_added(2, "C:/new")

    assert state.current_library_id == 2
    assert state.current_folder_paths == {20: "C:/new"}
    assert state.current_snapshots == []
    assert probed == [(20, "C:/new")]
    assert (1, "old.mkv") in state.strategy_overrides


def test_clear_current_state_returns_empty_collections():
    from leanreel.main import clear_current_state

    snapshots, folder_paths, overrides = clear_current_state()

    assert snapshots == []
    assert folder_paths == {}
    assert overrides == {}


def test_compute_encode_summary_returns_zero_for_empty_list():
    done, failed, cancelled = compute_encode_summary([])

    assert done == 0
    assert failed == 0
    assert cancelled == 0
