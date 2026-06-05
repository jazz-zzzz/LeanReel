//! Shared time utilities used by scanner and audit modules.
//!
//! ⚠️  TODO: Uses hardcoded UTC+8 offset (China Standard Time).
//! This will produce wrong timestamps for users in other timezones.
//! Replace with `chrono::Local::now()` once the chrono dependency is added.

/// Convert Rata Die day number to (year, month, day).
/// Algorithm: Howard Hinnant's civil_from_days (C++20 chrono).
pub fn civil_from_days(d: i32) -> (i32, i32, i32) {
    let z = d + 719468;
    let era = (if z >= 0 { z } else { z - 146096 }) / 146097;
    let doe = (z - era * 146097) as u32;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i32 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    (y, m as i32, d as i32)
}

/// Returns current local time as formatted string (UTC+8).
pub fn local_now() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = now.as_secs();
    // UTC+8 for China
    let local_secs = secs + 8 * 3600;
    let days = (local_secs / 86400) as i32;
    let remaining = local_secs % 86400;
    let hours = remaining / 3600;
    let minutes = (remaining % 3600) / 60;
    let seconds = remaining % 60;
    let (y, m, d) = civil_from_days(days);
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        y, m, d, hours, minutes, seconds
    )
}
