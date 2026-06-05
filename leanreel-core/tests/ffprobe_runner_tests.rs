use leanreel_rs_lib::domain::traits::MediaProber;
use leanreel_rs_lib::infrastructure::ffprobe::FfprobeRunner;
use std::path::{Path, PathBuf};

#[test]
fn test_runner_has_ffprobe() {
    let runner = FfprobeRunner::new(None);
    let result = runner.has_ffprobe();
    // ffprobe may or may not be installed; test that the function
    // returns a well-formed Result without panicking.
    match result {
        Ok(path) => assert!(!path.as_os_str().is_empty()),
        Err(e) => assert!(!e.is_empty()),
    }
}

#[test]
fn test_probe_nonexistent_file() {
    let runner = FfprobeRunner::new(None);
    let result = runner.probe(Path::new("definitely_not_a_real_file.mkv"));
    assert!(result.is_err());
}

#[test]
fn test_probe_batch_empty() {
    let runner = FfprobeRunner::new(None);
    let results = runner.probe_batch(&[]).unwrap();
    assert!(results.is_empty());
}

#[test]
fn test_probe_batch_skips_nonexistent() {
    let runner = FfprobeRunner::new(None);
    let paths = vec![PathBuf::from("fake1.mkv"), PathBuf::from("fake2.mp4")];
    let results = runner.probe_batch(&paths).unwrap();
    assert_eq!(results.len(), 2);
    for r in &results {
        assert!(r.metadata.is_err());
    }
}
