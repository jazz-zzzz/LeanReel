"""Application wiring helpers."""
from pathlib import Path

from leanreel.core.strategy import Strategy
from leanreel.data.models import FileSnapshot
from leanreel.main import build_encode_tasks, make_output_path


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


