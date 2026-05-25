from pathlib import Path


def test_output_committer_moves_temp_through_staging_file(tmp_path: Path):
    from leanreel.executor.output_commit import OutputCommitter

    temp_output = tmp_path / "encoded.tmp"
    final_output = tmp_path / "movie_zcompressed.mkv"
    temp_output.write_bytes(b"encoded")
    final_output.write_bytes(b"old")

    result = OutputCommitter().commit(temp_output, final_output)

    assert result == final_output
    assert final_output.read_bytes() == b"encoded"
    assert not temp_output.exists()
    assert not (tmp_path / "movie_zcompressed.staging.mkv").exists()


def test_output_committer_rejects_empty_temp_and_preserves_existing_output(tmp_path: Path):
    from leanreel.executor.output_commit import OutputCommitter

    temp_output = tmp_path / "encoded.tmp"
    final_output = tmp_path / "movie_zcompressed.mkv"
    temp_output.write_bytes(b"")
    final_output.write_bytes(b"old")

    try:
        OutputCommitter().commit(temp_output, final_output)
    except ValueError as exc:
        assert "empty" in str(exc).lower()
    else:
        raise AssertionError("empty output must be rejected")

    assert final_output.read_bytes() == b"old"
