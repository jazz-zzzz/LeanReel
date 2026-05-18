"""FileTableStore 测试"""
import pytest
from leanreel.state.file_store import FileTableStore
from leanreel.domain.models import FileRow
from leanreel.domain.models import FileSnapshot, HDRType


def _snap(library_folder_id=7, relative_path="a.mkv", file_name="a.mkv",
          size_bytes=1024, video_codec="h264", probe_ok=True):
    return FileSnapshot(
        library_folder_id=library_folder_id, relative_path=relative_path,
        file_name=file_name, size_bytes=size_bytes,
        video_codec=video_codec, hdr_type=HDRType.SDR, probe_ok=probe_ok,
    )


def test_file_row_key():
    snap = _snap(library_folder_id=7, relative_path="Season 1/a.mkv")
    row = FileRow(snap=snap)
    assert row.key == (7, "Season 1/a.mkv")


def test_file_row_folder_name():
    snap = _snap(relative_path="Season 1/E01.mkv")
    row = FileRow(snap=snap)
    assert row.folder_name == "Season 1"


def test_file_row_folder_name_root():
    snap = _snap(relative_path="movie.mkv")
    row = FileRow(snap=snap)
    assert row.folder_name == "."


def test_store_rebuild():
    store = FileTableStore()
    snap = _snap()
    store.rebuild([FileRow(snap=snap)])
    assert store.count() == 1
    assert store.row_at(0).key == (7, "a.mkv")


def test_store_rebuild_clears_old():
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snap())])
    store.rebuild([])
    assert store.count() == 0


def test_store_row_by_key():
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snap(relative_path="x.mkv"))])
    row = store.row_by_key((7, "x.mkv"))
    assert row is not None
    assert store.row_by_key((7, "nonexistent")) is None


def test_store_update_row():
    store = FileTableStore()
    snap = _snap(video_codec="", size_bytes=0, probe_ok=False)
    store.rebuild([FileRow(snap=snap)])

    new_snap = _snap(video_codec="h264", size_bytes=2048, probe_ok=True)
    store.update_row((7, "a.mkv"), new_snap)

    row = store.row_at(0)
    assert row.snap.video_codec == "h264"
    assert row.snap.size_bytes == 2048


def test_store_update_row_ignores_unknown_key():
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snap())])
    store.update_row((99, "nonexistent"), _snap())  # 不应崩溃


def test_store_checked_toggle():
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snap())])
    assert not store.is_checked((7, "a.mkv"))
    store.toggle_checked((7, "a.mkv"))
    assert store.is_checked((7, "a.mkv"))
    store.toggle_checked((7, "a.mkv"))
    assert not store.is_checked((7, "a.mkv"))


def test_store_checked_keys():
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snap(relative_path="a.mkv")),
                   FileRow(snap=_snap(relative_path="b.mkv"))])
    store.set_checked((7, "a.mkv"), True)
    store.set_checked((7, "b.mkv"), True)
    assert store.checked_keys() == [(7, "a.mkv"), (7, "b.mkv")]


def test_store_rebuild_preserves_checked():
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snap(relative_path="a.mkv"))])
    store.set_checked((7, "a.mkv"), True)
    store.rebuild([FileRow(snap=_snap(relative_path="a.mkv")),
                   FileRow(snap=_snap(relative_path="b.mkv"))])
    assert store.is_checked((7, "a.mkv"))
    assert not store.is_checked((7, "b.mkv"))


def test_store_rebuild_keep_checked_false():
    store = FileTableStore()
    store.rebuild([FileRow(snap=_snap())])
    store.set_checked((7, "a.mkv"), True)
    store.rebuild([FileRow(snap=_snap())], keep_checked=False)
    assert not store.is_checked((7, "a.mkv"))


def test_store_folder_stats():
    store = FileTableStore()
    store.rebuild([
        FileRow(snap=_snap(relative_path="S1/a.mkv", size_bytes=1000)),
        FileRow(snap=_snap(relative_path="S1/b.mkv", size_bytes=2000)),
        FileRow(snap=_snap(relative_path="S2/c.mkv", size_bytes=500)),
    ])
    stats = store.folder_stats()
    assert stats["S1"] == 3000
    assert stats["S2"] == 500