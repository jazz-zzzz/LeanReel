use crate::domain::traits::IoMetrics;
#[cfg(windows)]
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::time::Duration;
#[cfg(windows)]
use windows_sys::Win32::System::Threading::{GetProcessIoCounters, IO_COUNTERS};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProcessIoSnapshot {
    pub read_bytes: u64,
    pub write_bytes: u64,
}

#[cfg(windows)]
pub fn snapshot_process_io(child: &std::process::Child) -> Option<ProcessIoSnapshot> {
    let mut counters = unsafe { std::mem::zeroed::<IO_COUNTERS>() };
    if unsafe { GetProcessIoCounters(child.as_raw_handle(), &mut counters) } == 0 {
        return None;
    }

    Some(ProcessIoSnapshot {
        read_bytes: counters.ReadTransferCount,
        write_bytes: counters.WriteTransferCount,
    })
}

#[cfg(not(windows))]
pub fn snapshot_process_io(_child: &std::process::Child) -> Option<ProcessIoSnapshot> {
    None
}

fn has_server_and_share(path: &str) -> bool {
    let mut components = path.split('\\');
    matches!(components.next(), Some(server) if !server.is_empty())
        && matches!(components.next(), Some(share) if !share.is_empty())
}

pub fn is_smb_path(path: &Path) -> bool {
    let normalized = path.to_string_lossy().replace('/', r"\");

    if normalized
        .get(..8)
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case(r"\\?\UNC\"))
    {
        return has_server_and_share(&normalized[8..]);
    }

    if normalized.starts_with(r"\\?\") || normalized.starts_with(r"\\.\") {
        return false;
    }

    normalized
        .strip_prefix(r"\\")
        .is_some_and(has_server_and_share)
}

pub fn io_type_for_paths(input: &Path, output: &Path) -> &'static str {
    match (is_smb_path(input), is_smb_path(output)) {
        (false, false) => "local",
        (true, true) => "smb",
        _ => "mixed",
    }
}

pub fn summarize_io(
    start: ProcessIoSnapshot,
    end: ProcessIoSnapshot,
    duration: Duration,
    io_type: &str,
) -> Option<IoMetrics> {
    if duration.is_zero() {
        return None;
    }

    let seconds = duration.as_secs_f64();
    Some(IoMetrics {
        io_type: io_type.into(),
        read_bytes_per_sec: end.read_bytes.saturating_sub(start.read_bytes) as f64 / seconds,
        write_bytes_per_sec: end.write_bytes.saturating_sub(start.write_bytes) as f64 / seconds,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;
    use std::time::Duration;

    #[cfg(windows)]
    #[test]
    fn snapshots_a_running_child_process() {
        let mut child = std::process::Command::new("cmd")
            .args(["/C", "ping -n 3 127.0.0.1 >NUL"])
            .spawn()
            .expect("spawn child process");

        let snapshot = snapshot_process_io(&child);
        let _ = child.kill();
        let _ = child.wait();

        assert!(snapshot.is_some());
    }

    #[test]
    fn classifies_local_smb_and_mixed_paths() {
        assert_eq!(
            io_type_for_paths(Path::new(r"C:\input.mkv"), Path::new(r"D:\out.mkv")),
            "local"
        );
        assert_eq!(
            io_type_for_paths(
                Path::new(r"\\nas\share\input.mkv"),
                Path::new(r"\\nas\share\out.mkv")
            ),
            "smb"
        );
        assert_eq!(
            io_type_for_paths(
                Path::new(r"C:\input.mkv"),
                Path::new(r"\\nas\share\out.mkv")
            ),
            "mixed"
        );
        assert_eq!(
            io_type_for_paths(
                Path::new(r"\\nas\share\input.mkv"),
                Path::new(r"D:\out.mkv")
            ),
            "mixed"
        );
    }

    #[test]
    fn recognizes_only_valid_smb_paths() {
        assert!(!is_smb_path(Path::new(r"\\?\C:\input.mkv")));
        assert!(!is_smb_path(Path::new(r"\\.\pipe\name")));
        assert!(!is_smb_path(Path::new(r"\\")));
        assert!(is_smb_path(Path::new(r"\\nas\share\input.mkv")));
        assert!(is_smb_path(Path::new(r"//nas/share/input.mkv")));
        assert!(is_smb_path(Path::new(r"\\?\UNC\nas\share\input.mkv")));
    }

    #[test]
    fn summarizes_counter_delta_as_average_bytes_per_second() {
        let start = ProcessIoSnapshot {
            read_bytes: 100,
            write_bytes: 200,
        };
        let end = ProcessIoSnapshot {
            read_bytes: 2_100,
            write_bytes: 1_200,
        };

        assert_eq!(
            summarize_io(start, end, Duration::from_secs(2), "mixed"),
            Some(IoMetrics {
                io_type: "mixed".into(),
                read_bytes_per_sec: 1_000.0,
                write_bytes_per_sec: 500.0,
            })
        );
    }

    #[test]
    fn treats_counter_regression_as_zero_bytes_per_second() {
        let start = ProcessIoSnapshot {
            read_bytes: 200,
            write_bytes: 300,
        };
        let end = ProcessIoSnapshot {
            read_bytes: 100,
            write_bytes: 200,
        };

        assert_eq!(
            summarize_io(start, end, Duration::from_secs(2), "local"),
            Some(IoMetrics {
                io_type: "local".into(),
                read_bytes_per_sec: 0.0,
                write_bytes_per_sec: 0.0,
            })
        );
    }

    #[test]
    fn refuses_zero_duration_measurement() {
        let counters = ProcessIoSnapshot {
            read_bytes: 1,
            write_bytes: 1,
        };

        assert_eq!(
            summarize_io(counters, counters, Duration::ZERO, "local"),
            None
        );
    }
}
