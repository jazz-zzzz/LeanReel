use leanreel_rs_lib::infrastructure::ffmpeg::FfmpegRunner;

#[test]
fn test_runner_has_ffmpeg() {
    let runner = FfmpegRunner::new(None);
    let _ = runner.has_ffmpeg();
}

#[test]
fn test_cancel_no_running_job() {
    let runner = FfmpegRunner::new(None);
    assert!(runner.cancel().is_ok());
}
