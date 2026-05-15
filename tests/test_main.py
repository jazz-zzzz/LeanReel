"""Application wiring helpers."""
from pathlib import Path

from leanreel.core.strategy import Strategy
from leanreel.data.models import FileSnapshot
from leanreel.executor.worker import EncodeTask
from leanreel.data.models import TaskStatus
from leanreel.main import build_encode_tasks, make_output_path, compute_encode_summary


def test_make_output_path_adds_suffix_without_overwriting_original():
    source = Path("C:/media/Movie.mkv")

    assert make_output_path(source) == Path("C:/media/Movie_SS.mkv")


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
    assert tasks[0].output_path == str(Path("D:/TV") / "Season 1/Episode 1_SS.mkv")
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
        {"b.mkv": custom_strategy},
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
    from leanreel.main import build_encode_tasks
    from leanreel.core.strategy import Strategy
    from leanreel.data.models import FileSnapshot

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
    from leanreel.data.models import FileSnapshot

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

