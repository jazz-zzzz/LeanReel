import threading

import pytest

from leanreel.utils import threading_contract


def setup_function():
    threading_contract._reset_for_tests()


def teardown_function():
    threading_contract._reset_for_tests()


def test_require_main_thread_allows_captured_thread():
    threading_contract.capture_main_thread()

    threading_contract.require_main_thread("store update")


def test_require_main_thread_rejects_worker_thread():
    threading_contract.capture_main_thread()
    errors = []

    def worker():
        try:
            threading_contract.require_main_thread("store update")
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "store update" in errors[0]
    assert "main thread" in errors[0]


def test_forbid_main_thread_rejects_captured_thread():
    threading_contract.capture_main_thread()

    with pytest.raises(RuntimeError, match="cache loading"):
        threading_contract.forbid_main_thread("cache loading")


def test_forbid_main_thread_allows_worker_thread():
    threading_contract.capture_main_thread()
    errors = []

    def worker():
        try:
            threading_contract.forbid_main_thread("cache loading")
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors == []


from leanreel.state.file_store import FileTableStore
from leanreel.domain.models import FileRow
from leanreel.domain.models import FileSnapshot


def _snapshot(name="a.mkv"):
    return FileSnapshot(
        library_folder_id=1,
        relative_path=name,
        file_name=name,
        size_bytes=10,
        probe_ok=False,
    )


def test_file_table_store_rejects_worker_thread_rebuild_after_capture():
    threading_contract.capture_main_thread()
    store = FileTableStore()
    errors = []

    def worker():
        try:
            store.rebuild([FileRow(snap=_snapshot())])
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "FileTableStore.rebuild" in errors[0]


def test_file_table_store_rejects_worker_thread_update_after_capture():
    threading_contract.capture_main_thread()
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snapshot())])
    errors = []

    def worker():
        try:
            store.update_row((1, "a.mkv"), _snapshot())
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert errors
    assert "FileTableStore.update_row" in errors[0]