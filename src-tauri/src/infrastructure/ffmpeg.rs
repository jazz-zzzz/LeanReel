use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use crate::domain::traits::{EncodeOutput, Encoder, EncodingJob, IoMetrics, JobId, ProgressEvent};
use crate::infrastructure::ffmpeg_builder::build_ffmpeg_command;
use crate::infrastructure::process_io::{io_type_for_paths, snapshot_process_io, summarize_io};

pub struct FfmpegRunner {
    ffmpeg_path: Arc<Mutex<PathBuf>>,
    running_children: Mutex<HashMap<JobId, Arc<Mutex<Child>>>>,
}

fn read_stderr_records<R, F>(mut reader: R, mut on_record: F) -> Result<(), String>
where
    R: BufRead,
    F: FnMut(&str),
{
    let mut record = Vec::new();
    loop {
        let available = reader
            .fill_buf()
            .map_err(|e| format!("读取 ffmpeg 输出失败: {}", e))?;
        if available.is_empty() {
            if !record.is_empty() {
                on_record(&String::from_utf8_lossy(&record));
            }
            return Ok(());
        }

        let consumed = available.len();
        for &byte in available {
            if byte == b'\r' || byte == b'\n' {
                if !record.is_empty() {
                    on_record(&String::from_utf8_lossy(&record));
                    record.clear();
                }
            } else {
                record.push(byte);
            }
        }
        reader.consume(consumed);
    }
}

impl FfmpegRunner {
    pub fn new(path: Option<PathBuf>) -> Self {
        let ffmpeg_path = path.unwrap_or_else(|| {
            if let Ok(p) = std::env::var("FFMPEG_PATH") {
                return PathBuf::from(p);
            }
            let exe_dir = std::env::current_exe()
                .ok()
                .and_then(|p| p.parent().map(|d| d.to_path_buf()))
                .unwrap_or_default();

            let mut search = exe_dir.clone();
            for _ in 0..5 {
                let candidate = search.join("ffmpeg.exe");
                if candidate.exists() {
                    return candidate;
                }
                let candidate2 = search.join("resources").join("ffmpeg").join("ffmpeg.exe");
                if candidate2.exists() {
                    return candidate2;
                }
                let candidate3 = search
                    .join("leanreel")
                    .join("resources")
                    .join("ffmpeg")
                    .join("ffmpeg.exe");
                if candidate3.exists() {
                    return candidate3;
                }
                match search.parent() {
                    Some(p) => search = p.to_path_buf(),
                    None => break,
                }
            }
            PathBuf::from("ffmpeg")
        });
        Self {
            ffmpeg_path: Arc::new(Mutex::new(ffmpeg_path)),
            running_children: Mutex::new(HashMap::new()),
        }
    }

    pub fn load_from_config(&self, store: &crate::infrastructure::db::SqliteSnapshotStore) {
        if let Some(p) = store.get_config("ffmpeg_path") {
            let path = PathBuf::from(&p);
            if path.exists() {
                *self.ffmpeg_path.lock().unwrap() = path;
            }
        }
    }

    pub fn has_ffmpeg(&self) -> Result<PathBuf, String> {
        let path = self.ffmpeg_path.lock().unwrap().clone();
        if path.is_absolute() && path.exists() {
            return Ok(path);
        }
        which::which(&path).map_err(|e| format!("ffmpeg 未找到: {}", e))
    }

    fn track_child(&self, job_id: JobId, child: Child) -> Result<Arc<Mutex<Child>>, String> {
        let child = Arc::new(Mutex::new(child));
        self.running_children
            .lock()
            .map_err(|_| "互斥锁中毒".to_string())?
            .insert(job_id, child.clone());
        Ok(child)
    }

    fn untrack_child(&self, job_id: &str) {
        if let Ok(mut children) = self.running_children.lock() {
            children.remove(job_id);
        }
    }

    /// Parse a single FFmpeg stderr progress line. Returns `None` if the line
    /// doesn't contain a `time=` marker; otherwise returns the extracted
    /// (percent, fps, bitrate_kbps) triple.
    fn parse_progress_line(line: &str, duration_seconds: f64) -> Option<(f32, f32, u32)> {
        if !line.contains("time=") {
            return None;
        }
        eprintln!("PROGRESS_LINE dur={}: {}", duration_seconds, line);
        let percent = line
            .split("time=")
            .nth(1)
            .and_then(|value| value.split_whitespace().next())
            .and_then(|value| {
                let parts: Vec<&str> = value.split(':').collect();
                if parts.len() != 3 {
                    return None;
                }
                let hours = parts[0].parse::<f64>().ok()?;
                let minutes = parts[1].parse::<f64>().ok()?;
                let seconds = parts[2].parse::<f64>().ok()?;
                let pct = if duration_seconds > 0.0 {
                    ((hours * 3600.0 + minutes * 60.0 + seconds) / duration_seconds).min(0.98)
                        as f32
                } else {
                    0.5
                };
                Some(pct)
            })
            .unwrap_or(0.0);
        let fps = line
            .split("fps=")
            .nth(1)
            .and_then(|value| value.split_whitespace().next())
            .and_then(|value| value.parse::<f32>().ok())
            .unwrap_or(0.0);
        let bitrate_kbps = line
            .split("bitrate=")
            .nth(1)
            .and_then(|value| value.split_whitespace().next())
            .and_then(|value| value.trim_end_matches("kbits/s").parse::<f32>().ok())
            .map(|value| value as u32)
            .unwrap_or(0);
        Some((percent, fps, bitrate_kbps))
    }

    fn run_inner(
        &self,
        job: &EncodingJob,
        on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
    ) -> Result<EncodeOutput, String> {
        let ffmpeg_path = self.has_ffmpeg()?;
        let ffmpeg_str = ffmpeg_path.to_string_lossy().to_string();

        let args = build_ffmpeg_command(
            &job.snapshot,
            &job.strategy,
            &job.input_path,
            &job.output_path,
            &ffmpeg_str,
        )?;

        // Capture the full command line for audit (space-joined)
        let ffmpeg_command = args.join(" ");

        // Skip the first arg (ffmpeg path) — it's already the program
        let cmd_args: Vec<&str> = args[1..].iter().map(|s| s.as_str()).collect();

        on_progress(ProgressEvent::StageStart {
            stage: "transcode".into(),
            total_stages: 1,
        });

        let encode_start = Instant::now();

        eprintln!("FFmpeg 命令: {}", ffmpeg_command);

        let mut child = Command::new(&ffmpeg_path)
            .args(&cmd_args)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|e| format!("启动 ffmpeg 失败: {}", e))?;

        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "无法读取 ffmpeg stderr".to_string())?;
        let child = self.track_child(job.id.clone(), child)?;

        // Capture initial I/O counters right after spawn
        let io_start = snapshot_process_io(&*child.lock().map_err(|_| "互斥锁中毒".to_string())?);

        let mut err_tail = VecDeque::with_capacity(5);
        let mut line_count = 0u64;
        let mut max_fps: f32 = 0.0;
        let mut bitrate_sum: u64 = 0;
        let mut bitrate_samples: u64 = 0;
        read_stderr_records(BufReader::new(stderr), |line| {
            line_count += 1;
            if line_count <= 5 {
                eprintln!("STDERR[{}]: {}", line_count, &line[..line.len().min(120)]);
            }
            if let Some((percent, fps, bitrate_kbps)) =
                Self::parse_progress_line(line, job.snapshot.duration_seconds)
            {
                if fps > max_fps {
                    max_fps = fps;
                }
                if bitrate_kbps > 0 {
                    bitrate_sum += bitrate_kbps as u64;
                    bitrate_samples += 1;
                }
                on_progress(ProgressEvent::StageProgress {
                    percent,
                    fps,
                    bitrate_kbps,
                });
            }
            if err_tail.len() == 5 {
                err_tail.pop_front();
            }
            err_tail.push_back(line.to_string());
        })?;

        // Capture final I/O snapshot while child handle is still alive
        let io_end = {
            let guard = child.lock().map_err(|_| "互斥锁中毒".to_string())?;
            snapshot_process_io(&*guard)
        };

        let status = child
            .lock()
            .map_err(|_| "互斥锁中毒".to_string())?
            .wait()
            .map_err(|e| format!("等待 ffmpeg 失败: {}", e))?;
        self.untrack_child(&job.id);
        if !status.success() {
            return Err(format!(
                "ffmpeg 异常退出 ({:?}): {}\n命令: {}",
                status.code(),
                err_tail.into_iter().collect::<Vec<_>>().join("\n"),
                ffmpeg_command,
            ));
        }
        let duration_ms = encode_start.elapsed().as_millis() as u64;
        on_progress(ProgressEvent::StageComplete {
            stage: "transcode".into(),
            duration_ms,
        });
        let original_size = std::fs::metadata(&job.input_path)
            .map(|m| m.len())
            .unwrap_or(0);
        let compressed_size = std::fs::metadata(&job.output_path)
            .map(|m| m.len())
            .unwrap_or(0);
        let avg_bitrate_kbps = if bitrate_samples > 0 {
            (bitrate_sum / bitrate_samples) as u32
        } else {
            0
        };
        let io_metrics = match (io_start, io_end) {
            (Some(start), Some(end)) => {
                let io_type = io_type_for_paths(&job.input_path, &job.output_path);
                summarize_io(start, end, encode_start.elapsed(), io_type)
            }
            _ => None,
        };

        Ok(EncodeOutput {
            output_path: job.output_path.clone(),
            original_size,
            compressed_size,
            duration_ms,
            command: ffmpeg_command.clone(),
            max_fps,
            avg_bitrate_kbps,
            io_metrics,
        })
    }

    pub fn cancel(&self) -> Result<(), String> {
        self.cancel_job("")
    }

    pub fn cancel_job(&self, job_id: &str) -> Result<(), String> {
        let children: Vec<Arc<Mutex<Child>>> = {
            let children = self
                .running_children
                .lock()
                .map_err(|_| "互斥锁中毒".to_string())?;
            if job_id.is_empty() {
                children.values().cloned().collect()
            } else {
                children.get(job_id).cloned().into_iter().collect()
            }
        };
        for child in children {
            let mut child = child.lock().map_err(|_| "互斥锁中毒".to_string())?;
            if child
                .try_wait()
                .map_err(|e| format!("检查 ffmpeg 状态失败: {}", e))?
                .is_none()
            {
                child
                    .kill()
                    .map_err(|e| format!("终止 ffmpeg 失败: {}", e))?;
            }
        }
        Ok(())
    }
}

impl Encoder for FfmpegRunner {
    fn run(
        &self,
        job: &EncodingJob,
        on_progress: &(dyn Fn(ProgressEvent) + Send + Sync),
    ) -> Result<EncodeOutput, String> {
        self.run_inner(job, on_progress)
    }

    fn cancel(&self, job_id: &JobId) -> Result<(), String> {
        self.cancel_job(job_id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::models::{FileSnapshot, HdrType, Strategy, VideoCodec};
    #[test]
    fn test_runner_has_ffmpeg() {
        let runner = FfmpegRunner::new(None);
        match runner.has_ffmpeg() {
            Ok(path) => assert!(!path.as_os_str().is_empty()),
            Err(e) => assert!(!e.is_empty()),
        }
    }
    #[test]
    fn test_run_nonexistent_file() {
        let runner = FfmpegRunner::new(None);
        let snap = FileSnapshot {
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            audio_tracks: vec![],
            subtitle_tracks: vec![],
            ..Default::default()
        };
        let job = EncodingJob {
            id: "test".into(),
            input_path: PathBuf::from("nonexistent.mkv"),
            output_path: PathBuf::from("out.mkv"),
            strategy: Strategy::default(),
            has_dolby_vision: false,
            snapshot: snap,
        };
        let result = runner.run(&job, &|_| {});
        assert!(result.is_err(), "Should fail on nonexistent file");
    }
    #[test]
    fn test_cancel_no_running_job() {
        let runner = FfmpegRunner::new(None);
        let result = runner.cancel();
        assert!(result.is_ok(), "Cancel with no running job should be ok");
    }

    #[test]
    fn test_read_stderr_records_splits_carriage_return_progress_updates() {
        let input = b"frame=1 time=00:00:01.00\rframe=2 time=00:00:02.50\r";
        let mut records = Vec::new();

        read_stderr_records(&input[..], |record| records.push(record.to_string())).unwrap();

        assert_eq!(
            records,
            vec!["frame=1 time=00:00:01.00", "frame=2 time=00:00:02.50",]
        );
    }

    #[test]
    fn test_read_stderr_records_preserves_newline_logs_and_carriage_return_progress() {
        let input = b"Input #0\nframe=3 time=00:00:03.75\rvideo:120kB\n";
        let mut records = Vec::new();

        read_stderr_records(&input[..], |record| records.push(record.to_string())).unwrap();

        assert_eq!(
            records,
            vec!["Input #0", "frame=3 time=00:00:03.75", "video:120kB",]
        );
    }

    #[test]
    #[cfg(windows)]
    fn test_cancel_kills_running_child_without_waiting_for_exit() {
        use std::time::{Duration, Instant};

        let runner = FfmpegRunner::new(None);
        let child = Command::new("cmd")
            .args(["/C", "ping 127.0.0.1 -n 30 > nul"])
            .spawn()
            .unwrap();
        runner.track_child("slow-job".into(), child).unwrap();

        let started = Instant::now();
        runner.cancel_job("slow-job").unwrap();

        assert!(
            started.elapsed() < Duration::from_secs(2),
            "cancel should not wait for the child process to finish naturally"
        );
    }
}
