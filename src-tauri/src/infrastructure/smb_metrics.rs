use crate::domain::traits::SmbMetrics;
use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

/// Start background SMB performance sampling via Windows `typeperf`.
///
/// Returns a join handle and a stop flag. Caller sets the flag to stop
/// sampling, then joins the handle to collect aggregated metrics.
/// Returns `None` if `typeperf` isn't available (non-Windows or missing).
pub fn spawn_smb_sampler(share_unc: String) -> Option<(Arc<AtomicBool>, thread::JoinHandle<SmbMetrics>)> {
    // typeperf only exists on Windows
    if !cfg!(windows) {
        return None;
    }

    let share_label = share_unc.clone(); // for error messages inside the thread

    let counters = format!(
        "\"\\SMB Client Shares({})\\Read Bytes/sec\" \
         \"\\SMB Client Shares({})\\Write Bytes/sec\" \
         \"\\SMB Client Shares({})\\Avg. Data Bytes/Request\" \
         \"\\SMB Client Shares({})\\Avg. Data Queue Length\"",
        share_unc, share_unc, share_unc, share_unc,
    );

    let mut child = match Command::new("typeperf")
        .args(["-si", "2", &counters])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            eprintln!("SMB 采样启动失败: {}", e);
            return None;
        }
    };

    let stdout = match child.stdout.take() {
        Some(s) => s,
        None => {
            let _ = child.kill();
            return None;
        }
    };

    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = stop.clone();

    let handle = thread::spawn(move || {
        let mut read_vals: Vec<f64> = Vec::new();
        let mut write_vals: Vec<f64> = Vec::new();
        let mut bytes_per_req: Vec<f64> = Vec::new();
        let mut queue_len: Vec<f64> = Vec::new();

        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            if stop_clone.load(Ordering::Relaxed) {
                break;
            }
            let line = match line {
                Ok(l) => l,
                Err(_) => break,
            };
            // Sample rows look like: "06/01/2026 22:50:31.000","123.456","78.9",...
            // Header row has counter paths — skip anything without a date-like first field.
            if !line.starts_with('"') || line.len() < 24 || !line.as_bytes().get(2).map_or(false, |b| *b == b'/') {
                continue;
            }
            let parts: Vec<&str> = line.split(',').collect();
            if parts.len() < 5 {
                continue;
            }
            let parse = |s: &str| s.trim_matches('"').parse::<f64>().unwrap_or(0.0);
            read_vals.push(parse(parts[1]));
            write_vals.push(parse(parts[2]));
            bytes_per_req.push(parse(parts[3]));
            queue_len.push(parse(parts[4]));
        }

        let _ = child.kill();
        let _ = child.wait();

        // If we got no samples, typeperf likely failed — read stderr for diagnostics
        if read_vals.is_empty() {
            if let Some(stderr) = child.stderr.take() {
                let err_text = BufReader::new(stderr)
                    .lines()
                    .filter_map(|l| l.ok())
                    .collect::<Vec<_>>()
                    .join("\n");
                if !err_text.is_empty() {
                    eprintln!("SMB typeperf stderr: {}", err_text);
                }
            }
            eprintln!("SMB 采样数据为空，检查计数器实例名是否正确: {}", share_label);
        }

        let avg = |v: &[f64]| {
            if v.is_empty() {
                0.0
            } else {
                v.iter().sum::<f64>() / v.len() as f64
            }
        };

        SmbMetrics {
            read_bytes_per_sec: avg(&read_vals),
            write_bytes_per_sec: avg(&write_vals),
            avg_data_bytes_per_request: avg(&bytes_per_req),
            avg_data_queue_length: avg(&queue_len),
        }
    });

    // Give typeperf a moment to start collecting
    thread::sleep(Duration::from_millis(500));

    Some((stop, handle))
}
