import pytest


def test_scan_ready_event_normalizes_folder_inputs_to_immutable_payload():
    from leanreel.controllers.events import FolderScanInput, ScanReadyEvent
    from leanreel.domain.models import FileSnapshot

    snap = FileSnapshot(library_folder_id=7, relative_path="movie.mkv", file_name="movie.mkv")
    event = ScanReadyEvent(
        batch_id=12,
        library_id=3,
        folder_inputs=[
            FolderScanInput(folder_id=7, path="C:/media", files=[("movie.mkv", "C:/media/movie.mkv")])
        ],
        placeholders=[snap],
    )

    assert event.batch_id == 12
    assert event.folder_ids == frozenset({7})
    assert event.folder_inputs[0].files == (("movie.mkv", "C:/media/movie.mkv"),)
    assert event.placeholders == (snap,)
    with pytest.raises(AttributeError):
        event.batch_id = 99


def test_task_progress_event_copies_task_state_without_exposing_mutable_task():
    from leanreel.controllers.events import TaskProgressEvent
    from leanreel.executor.worker import EncodeTask
    from leanreel.domain.models import TaskStatus

    task = EncodeTask(
        file_name="movie.mkv",
        input_path="C:/in/movie.mkv",
        output_path="C:/out/movie.mkv",
        strategy_name="x265",
        progress=0.42,
        status=TaskStatus.RUNNING,
    )

    event = TaskProgressEvent.from_task(task, sequence=5)
    task.progress = 0.9
    task.status = TaskStatus.FAILED
    task.error_message = "later failure"

    assert event.sequence == 5
    assert event.file_name == "movie.mkv"
    assert event.status is TaskStatus.RUNNING
    assert event.progress == pytest.approx(0.42)
    assert event.error_message == ""
