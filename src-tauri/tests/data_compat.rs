use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::domain::traits::SnapshotStore;
use leanreel_rs_lib::infrastructure::db::SqliteSnapshotStore;
use std::path::PathBuf;

/// 在 CI 中运行时需要设置 LEANREEL_PY_DB 环境变量
/// 指向 Python 版生成的 .db 文件
fn get_python_db_path() -> Option<PathBuf> {
    std::env::var("LEANREEL_PY_DB").ok().map(PathBuf::from)
}

#[test]
fn test_can_open_python_db_readonly() {
    let path = match get_python_db_path() {
        Some(p) => p,
        None => {
            eprintln!("Skipping: LEANREEL_PY_DB not set");
            return;
        }
    };
    let store = SqliteSnapshotStore::open_readonly(&path);
    assert!(store.is_ok(), "Should open Python DB in read-only mode");
}

#[test]
fn test_query_python_db_returns_data() {
    let path = match get_python_db_path() {
        Some(p) => p,
        None => {
            eprintln!("Skipping: LEANREEL_PY_DB not set");
            return;
        }
    };
    let store = SqliteSnapshotStore::open_readonly(&path).unwrap();
    let filter = FileFilter {
        library_id: None,
        folder_id: None,
        probe_ok_only: None,
    };
    let results = store.query(&filter).unwrap();
    assert!(
        !results.is_empty(),
        "Python DB should have file_snapshot rows"
    );
    let first = &results[0];
    assert!(!first.file_name.is_empty(), "file_name should not be empty");
    assert!(
        !first.relative_path.is_empty(),
        "relative_path should not be empty"
    );
}

#[test]
fn test_random_snapshot_from_python_db() {
    let path = match get_python_db_path() {
        Some(p) => p,
        None => {
            eprintln!("Skipping: LEANREEL_PY_DB not set");
            return;
        }
    };
    let store = SqliteSnapshotStore::open_readonly(&path).unwrap();
    let snap = store.random_snapshot().unwrap();
    assert!(
        snap.is_some(),
        "Python DB should have at least one snapshot"
    );
    let snap = snap.unwrap();
    assert!(snap.size_bytes > 0, "size should be positive");
}
