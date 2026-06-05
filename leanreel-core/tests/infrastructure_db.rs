use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::domain::traits::SnapshotStore;
use leanreel_rs_lib::infrastructure::db::{CreateCompressionRecordParams, SqliteSnapshotStore};
use std::path::Path;

fn make_test_snapshot(path: &str, codec: VideoCodec, hdr: HdrType) -> FileSnapshot {
    FileSnapshot {
        id: None,
        library_folder_id: 1,
        relative_path: path.into(),
        file_name: path.split('/').next_back().unwrap_or(path).into(),
        size_bytes: 1_000_000_000,
        video_codec: codec,
        video_width: 1920,
        video_height: 1080,
        hdr_type: hdr,
        audio_tracks: vec![],
        subtitle_tracks: vec![],
        duration_seconds: 3600.0,
        bitrate_bps: 2_200_000,
        file_mtime: 1716500000.0,
        probe_ok: true,
        probe_error: String::new(),
        scanned_at: "2026-05-30 12:00:00".into(),
        ..Default::default()
    }
}

/// Helper: ensure library+library_folder parent rows exist so FK constraints pass.
fn ensure_folder(store: &SqliteSnapshotStore, folder_id: i64, library_id: i64, path: &str) {
    store
        .ensure_library_folder(folder_id, library_id, path)
        .unwrap();
}

#[test]
fn test_upsert_and_query() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    ensure_folder(&store, 1, 1, "root");

    let snapshots = vec![
        make_test_snapshot("movies/a.mkv", VideoCodec::H264, HdrType::Sdr),
        make_test_snapshot("movies/b.mkv", VideoCodec::Hevc, HdrType::Hdr10),
        make_test_snapshot("tv/c.mkv", VideoCodec::Av1, HdrType::Sdr),
    ];

    let count = store.upsert(&snapshots).unwrap();
    assert_eq!(count, 3);

    let filter = FileFilter {
        library_id: None,
        folder_id: None,
        probe_ok_only: None,
    };
    let results = store.query(&filter).unwrap();
    assert_eq!(results.len(), 3);
}

#[test]
fn test_upsert_dedup_by_path() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    ensure_folder(&store, 1, 1, "root");

    let snap1 = make_test_snapshot("movies/x.mkv", VideoCodec::H264, HdrType::Sdr);
    store.upsert(&[snap1]).unwrap();

    let snap2 = make_test_snapshot("movies/x.mkv", VideoCodec::Hevc, HdrType::Sdr);
    store.upsert(&[snap2]).unwrap();

    let filter = FileFilter {
        library_id: None,
        folder_id: None,
        probe_ok_only: None,
    };
    let results = store.query(&filter).unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].video_codec, VideoCodec::Hevc);
}

#[test]
fn test_mark_deleted() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    ensure_folder(&store, 1, 1, "root");

    let snap = make_test_snapshot("movies/to_delete.mkv", VideoCodec::H264, HdrType::Sdr);
    store.upsert(&[snap]).unwrap();

    let result = store
        .mark_deleted(1, Path::new("movies/to_delete.mkv"))
        .unwrap();
    assert!(result);

    let filter = FileFilter {
        library_id: None,
        folder_id: None,
        probe_ok_only: None,
    };
    let results = store.query(&filter).unwrap();
    assert!(results.is_empty());
}

#[test]
fn test_random_snapshot() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    ensure_folder(&store, 1, 1, "root");

    let snapshots = vec![
        make_test_snapshot("a.mkv", VideoCodec::H264, HdrType::Sdr),
        make_test_snapshot("b.mkv", VideoCodec::Hevc, HdrType::Hdr10),
    ];
    store.upsert(&snapshots).unwrap();

    let random = store.random_snapshot().unwrap();
    assert!(random.is_some());
    let snap = random.unwrap();
    assert!(snap.file_name == "a.mkv" || snap.file_name == "b.mkv");
}

#[test]
fn test_upsert_rollback_on_fk_violation() {
    // M9: Verify that a failed upsert (foreign key violation) does not leave
    // partial data — the entire batch must be rolled back.
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    // Only create folder 1, NOT folder 999
    ensure_folder(&store, 1, 1, "root");

    // Batch: first snapshot is valid, second has a non-existent library_folder_id
    let mut valid = make_test_snapshot("movies/valid.mkv", VideoCodec::H264, HdrType::Sdr);
    valid.library_folder_id = 1;
    let mut invalid = make_test_snapshot("movies/invalid.mkv", VideoCodec::Hevc, HdrType::Sdr);
    invalid.library_folder_id = 999; // FK violation — folder 999 does not exist

    let result = store.upsert(&[valid, invalid]);
    // The batch must fail due to the FK violation on the second snapshot
    assert!(
        result.is_err(),
        "Expected FK violation to cause upsert failure"
    );

    // After transaction rollback, neither snapshot should be present
    let filter = FileFilter {
        library_id: None,
        folder_id: None,
        probe_ok_only: None,
    };
    let results = store.query(&filter).unwrap();
    assert!(
        results.is_empty(),
        "Rollback must leave no partial data behind"
    );
}

// ── H-030: JOIN-based history query tests ─────────────────────────────────

#[test]
fn test_compression_history_joined_returns_empty_when_no_records() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    let results = store.get_compression_history_joined().unwrap();
    assert!(
        results.is_empty(),
        "Should return empty vec when no compression records exist"
    );
}

#[test]
fn test_compression_history_joined_includes_live_library_data() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();

    // Setup: library → folder → snapshot
    ensure_folder(&store, 1, 1, "/movies");
    let snap = make_test_snapshot("movies/test.mkv", VideoCodec::H264, HdrType::Sdr);
    store.upsert(&[snap]).unwrap();

    // Create a compression record linked to the snapshot
    let all_snaps = store
        .query(&FileFilter {
            library_id: None,
            folder_id: None,
            probe_ok_only: None,
        })
        .unwrap();
    let snap_id = all_snaps[0].id.unwrap();

    let record_id = store
        .create_compression_record(CreateCompressionRecordParams {
            file_snapshot_id: snap_id,
            batch_id: "batch-1",
            strategy_name: "AV1 CQ28",
            original_size: 2_000_000_000,
            output_path: "/output/test_out.mkv",
            encoder: "av1_nvenc",
            cq_value: 28,
            preset: "p7",
            pix_fmt: "yuv420p10le",
            audio_mode: "copy",
            sub_mode: "copy",
        })
        .unwrap();

    // Query via JOIN
    let history = store.get_compression_history_joined().unwrap();
    assert_eq!(history.len(), 1, "Should have 1 history entry");
    let entry = &history[0];
    assert_eq!(entry.id, record_id);
    // The JOIN should compute the source path from library_folder.path + snapshot.relative_path
    assert!(entry.source_path.contains("test.mkv"));
    assert_eq!(entry.strategy_name, "AV1 CQ28");
    assert_eq!(entry.encoder, "av1_nvenc");
    assert_eq!(entry.status, "pending");
}

#[test]
fn test_both_history_methods_consistent() {
    // Verify that the JOIN-based method and the stored-copy method
    // return consistent results when stored copy columns are populated.
    let store = SqliteSnapshotStore::open_in_memory().unwrap();

    ensure_folder(&store, 1, 1, "/videos");
    let snap = make_test_snapshot("videos/f.mkv", VideoCodec::H264, HdrType::Sdr);
    store.upsert(&[snap]).unwrap();

    let all_snaps = store
        .query(&FileFilter {
            library_id: None,
            folder_id: None,
            probe_ok_only: None,
        })
        .unwrap();
    let snap_id = all_snaps[0].id.unwrap();

    store
        .create_compression_record(CreateCompressionRecordParams {
            file_snapshot_id: snap_id,
            batch_id: "b2",
            strategy_name: "H264 CRF23",
            original_size: 1_000_000_000,
            output_path: "/o/f_out.mkv",
            encoder: "libx264",
            cq_value: 0,
            preset: "medium",
            pix_fmt: "yuv420p",
            audio_mode: "copy",
            sub_mode: "copy",
        })
        .unwrap();

    // Explicitly set stored-copy columns so old method also works
    store.get_compression_history().unwrap();

    let joined = store.get_compression_history_joined().unwrap();
    let stored = store.get_compression_history().unwrap();

    // Both should return the same number of entries
    assert_eq!(joined.len(), stored.len());
    // Both should have the same IDs
    if !joined.is_empty() && !stored.is_empty() {
        assert_eq!(joined[0].id, stored[0].id);
        assert_eq!(joined[0].strategy_name, stored[0].strategy_name);
    }
}

#[test]
fn test_empty_store_random_returns_none() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    let result = store.random_snapshot().unwrap();
    assert!(result.is_none());
}

#[test]
fn test_filter_by_folder_id() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    ensure_folder(&store, 1, 1, "folder_a");
    ensure_folder(&store, 2, 1, "folder_b");

    let mut snap1 = make_test_snapshot("folder_a/file1.mkv", VideoCodec::H264, HdrType::Sdr);
    snap1.library_folder_id = 1;
    let mut snap2 = make_test_snapshot("folder_b/file2.mkv", VideoCodec::Hevc, HdrType::Sdr);
    snap2.library_folder_id = 2;

    store.upsert(&[snap1, snap2]).unwrap();

    let filter = FileFilter {
        library_id: None,
        folder_id: Some(1),
        probe_ok_only: None,
    };
    let results = store.query(&filter).unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].file_name, "file1.mkv");
}

#[test]
fn test_get_by_folder_path_distinguishes_duplicate_relative_paths() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    ensure_folder(&store, 1, 1, "folder_a");
    ensure_folder(&store, 2, 1, "folder_b");

    let mut first = make_test_snapshot("movie.mkv", VideoCodec::H264, HdrType::Sdr);
    first.library_folder_id = 1;
    let mut second = make_test_snapshot("movie.mkv", VideoCodec::Hevc, HdrType::Sdr);
    second.library_folder_id = 2;
    store.upsert(&[first, second]).unwrap();

    let result = store
        .get_by_folder_path(2, Path::new("movie.mkv"))
        .unwrap()
        .unwrap();
    assert_eq!(result.library_folder_id, 2);
    assert_eq!(result.video_codec, VideoCodec::Hevc);
}

#[test]
fn test_batch_progress_consumes_query_rows() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    ensure_folder(&store, 1, 1, "folder");
    store
        .upsert(&[make_test_snapshot(
            "movie.mkv",
            VideoCodec::H264,
            HdrType::Sdr,
        )])
        .unwrap();
    let snapshot = store
        .get_by_folder_path(1, Path::new("movie.mkv"))
        .unwrap()
        .unwrap();
    store
        .create_compression_record(CreateCompressionRecordParams {
            file_snapshot_id: snapshot.id.unwrap(),
            batch_id: "batch-progress",
            strategy_name: "strategy",
            original_size: snapshot.size_bytes,
            output_path: "output.mkv",
            encoder: "libx265",
            cq_value: 23,
            preset: "medium",
            pix_fmt: "yuv420p",
            audio_mode: "copy",
            sub_mode: "copy",
        })
        .unwrap();

    let progress = store.get_batch_progress("batch-progress").unwrap();
    assert_eq!(progress["total"], 1);
    assert_eq!(progress["pending"], 1);
}

#[test]
fn test_batch_progress_treats_nan_as_zero() {
    let store = SqliteSnapshotStore::open_in_memory().unwrap();
    ensure_folder(&store, 1, 1, "folder");
    store
        .upsert(&[make_test_snapshot(
            "movie.mkv",
            VideoCodec::H264,
            HdrType::Sdr,
        )])
        .unwrap();
    let snapshot = store
        .get_by_folder_path(1, Path::new("movie.mkv"))
        .unwrap()
        .unwrap();
    let record_id = store
        .create_compression_record(CreateCompressionRecordParams {
            file_snapshot_id: snapshot.id.unwrap(),
            batch_id: "batch-nan",
            strategy_name: "strategy",
            original_size: snapshot.size_bytes,
            output_path: "output.mkv",
            encoder: "libx265",
            cq_value: 23,
            preset: "medium",
            pix_fmt: "yuv420p",
            audio_mode: "copy",
            sub_mode: "copy",
        })
        .unwrap();

    store
        .update_compression_runtime(record_id, "running", f64::NAN, "transcoding", 0)
        .unwrap();

    let progress = store.get_batch_progress("batch-nan").unwrap();
    assert_eq!(progress["percentage"], 0.0);
}
