use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::domain::traits::*;
use std::path::{Path, PathBuf};

struct MockStore;
impl SnapshotStore for MockStore {
    fn upsert(&self, _snapshots: &[FileSnapshot]) -> Result<usize, String> {
        Ok(0)
    }
    fn query(&self, _filter: &FileFilter) -> Result<Vec<FileSnapshot>, String> {
        Ok(vec![])
    }
    fn mark_deleted(&self, _folder_id: i64, _path: &Path) -> Result<bool, String> {
        Ok(true)
    }
    fn get_by_path(&self, _path: &Path) -> Result<Option<FileSnapshot>, String> {
        Ok(None)
    }
    fn random_snapshot(&self) -> Result<Option<FileSnapshot>, String> {
        Ok(None)
    }
    fn update_compression_runtime(
        &self,
        _record_id: i64,
        _status: &str,
        _progress: f64,
        _stage: &str,
        _duration_seconds: i64,
    ) -> Result<(), String> {
        Ok(())
    }
    fn finish_compression(
        &self,
        _record_id: i64,
        _status: &str,
        _progress: f64,
        _duration_seconds: i64,
        _compressed_size: i64,
        _error_message: &str,
        _sidecar_path: &str,
        _source_deleted: i32,
        _ffmpeg_command: &str,
    ) -> Result<(), String> {
        Ok(())
    }
}

struct MockProber;
impl MediaProber for MockProber {
    fn probe(&self, _path: &Path) -> Result<VideoMetadata, String> {
        Err("not implemented".into())
    }
    fn probe_batch(&self, _paths: &[PathBuf]) -> Result<Vec<ProbeResult>, String> {
        Ok(vec![])
    }
}

struct MockEncoder;
impl Encoder for MockEncoder {
    fn run(
        &self,
        _job: &EncodingJob,
        _on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
    ) -> Result<EncodeOutput, String> {
        Err("not implemented".into())
    }
    fn cancel(&self, _job_id: &JobId) -> Result<(), String> {
        Ok(())
    }
}

#[test]
fn test_traits_are_object_safe() {
    let _store: Box<dyn SnapshotStore> = Box::new(MockStore);
    let _prober: Box<dyn MediaProber> = Box::new(MockProber);
    let _encoder: Box<dyn Encoder> = Box::new(MockEncoder);
}

#[test]
fn test_mock_store_upsert_returns_count() {
    let store = MockStore;
    let snapshots = vec![];
    let result = store.upsert(&snapshots);
    assert!(result.is_ok());
    assert_eq!(result.unwrap(), 0);
}

#[test]
fn test_mock_prober_returns_empty_batch() {
    let prober = MockProber;
    let paths = vec![];
    let result = prober.probe_batch(&paths);
    assert!(result.is_ok());
    assert_eq!(result.unwrap().len(), 0);
}
