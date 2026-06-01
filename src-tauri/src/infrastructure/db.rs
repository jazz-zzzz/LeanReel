use crate::domain::models::*;
use crate::domain::traits::{FinishCompressionParams, SnapshotStore};
use rusqlite::OptionalExtension;
use rusqlite::{params, Connection, Row};
use std::path::Path;

pub struct SqliteSnapshotStore {
    conn: Connection,
}

pub struct CreateCompressionRecordParams<'a> {
    pub file_snapshot_id: i64,
    pub batch_id: &'a str,
    pub strategy_name: &'a str,
    pub original_size: i64,
    pub output_path: &'a str,
    pub encoder: &'a str,
    pub cq_value: i32,
    pub preset: &'a str,
    pub pix_fmt: &'a str,
    pub audio_mode: &'a str,
    pub sub_mode: &'a str,
}

/// Shared helper: map a rusqlite Row to a FileSnapshot.
/// Avoids duplicating the 23-field mapping between query() and random_snapshot().
fn row_to_snapshot(row: &Row) -> rusqlite::Result<FileSnapshot> {
    let codec_str: String = row.get(5)?;
    let hdr_str: String = row.get(8)?;
    let audio_json: String = row.get(9)?;
    let sub_json: String = row.get(10)?;

    let hdr_type = match hdr_str.as_str() {
        "HDR10" => HdrType::Hdr10,
        "HDR10+" => HdrType::Hdr10Plus,
        "DV_P5" => HdrType::DolbyVision {
            profile: DvProfile::Profile5,
        },
        "DV_P7" => HdrType::DolbyVision {
            profile: DvProfile::Profile7,
        },
        "DV_P8" => HdrType::DolbyVision {
            profile: DvProfile::Profile8_1,
        },
        // Legacy format compat (old Rust code wrote these)
        s if s.starts_with("DolbyVision") => {
            let profile = if let Some(prof) = s.strip_prefix("DolbyVision:") {
                match prof {
                    "Profile5" => DvProfile::Profile5,
                    "Profile7" => DvProfile::Profile7,
                    "Profile8_4" => DvProfile::Profile8_4,
                    _ => DvProfile::Profile8_1,
                }
            } else {
                DvProfile::Profile8_1 // old format without profile
            };
            HdrType::DolbyVision { profile }
        }
        _ => HdrType::Sdr,
    };

    // H-029: Read extended probe fields from columns 17-21 (may be NULL for old DBs)
    let pix_fmt: String = row.get(17).unwrap_or_default();
    let frame_rate: String = row.get(18).unwrap_or_default();
    let color_primaries: String = row.get(19).unwrap_or_default();
    let color_transfer: String = row.get(20).unwrap_or_default();
    let color_space: String = row.get(21).unwrap_or_default();

    Ok(FileSnapshot {
        id: Some(row.get(0)?),
        library_folder_id: row.get(1)?,
        relative_path: row.get(2)?,
        file_name: row.get(3)?,
        size_bytes: row.get(4)?,
        video_codec: VideoCodec::from_codec(&codec_str),
        video_width: row.get(6)?,
        video_height: row.get(7)?,
        hdr_type,
        audio_tracks: serde_json::from_str(&audio_json).unwrap_or_default(),
        subtitle_tracks: serde_json::from_str(&sub_json).unwrap_or_default(),
        duration_seconds: row.get(11)?,
        bitrate_bps: row.get(12)?,
        file_mtime: row.get(13)?,
        probe_ok: row.get::<_, i32>(14)? != 0,
        probe_error: row.get(15)?,
        scanned_at: row.get(16)?,
        pix_fmt,
        frame_rate,
        color_primaries,
        color_transfer,
        color_space,
    })
}

impl SqliteSnapshotStore {
    pub fn open(path: &Path) -> Result<Self, String> {
        let conn = Connection::open(path).map_err(|e| e.to_string())?;
        let store = Self { conn };
        store.create_tables()?;
        Ok(store)
    }

    pub fn open_in_memory() -> Result<Self, String> {
        let conn = Connection::open_in_memory().map_err(|e| e.to_string())?;
        let store = Self { conn };
        store.create_tables()?;
        Ok(store)
    }

    /// Begin a transaction. Enables atomic multi-step operations.
    /// Callers should pair with commit() or rollback().
    pub fn begin(&self) -> Result<(), String> {
        self.conn
            .execute("BEGIN IMMEDIATE", [])
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Commit the active transaction.
    pub fn commit(&self) -> Result<(), String> {
        self.conn.execute("COMMIT", []).map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Roll back the active transaction.
    pub fn rollback(&self) -> Result<(), String> {
        self.conn
            .execute("ROLLBACK", [])
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Insert parent library + library_folder rows so that foreign key
    /// constraints (PRAGMA foreign_keys = ON) are satisfied before upserting
    /// file_snapshot records.  Uses OR IGNORE so it is idempotent.
    pub fn ensure_library_folder(
        &self,
        folder_id: i64,
        library_id: i64,
        path: &str,
    ) -> Result<(), String> {
        use rusqlite::params;
        // ensure library exists
        self.conn
            .execute(
                "INSERT OR IGNORE INTO library (id, name) VALUES (?1, ?2)",
                params![library_id, "test_library"],
            )
            .map_err(|e| e.to_string())?;
        // ensure library_folder exists
        self.conn
            .execute(
                "INSERT OR IGNORE INTO library_folder (id, library_id, path) VALUES (?1, ?2, ?3)",
                params![folder_id, library_id, path],
            )
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn create_compression_record(
        &self,
        params: CreateCompressionRecordParams<'_>,
    ) -> Result<i64, String> {
        let CreateCompressionRecordParams {
            file_snapshot_id,
            batch_id,
            strategy_name,
            original_size,
            output_path,
            encoder,
            cq_value,
            preset,
            pix_fmt,
            audio_mode,
            sub_mode,
        } = params;
        self.conn.execute(
        "INSERT INTO compression_history (file_snapshot_id, batch_id, strategy_name, original_size, output_path, status, progress, stage, encoder, cq_value, preset, pix_fmt, audio_mode, sub_mode, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, 'pending', 0, '', ?6, ?7, ?8, ?9, ?10, ?11, datetime('now','localtime'))",
        params![file_snapshot_id, batch_id, strategy_name, original_size, output_path, encoder, cq_value, preset, pix_fmt, audio_mode, sub_mode],
    ).map_err(|e| e.to_string())?;
        Ok(self.conn.last_insert_rowid())
    }

    /// H5: Backfill source_library_id/source_library_folder_id/source_library_name/
    /// source_folder_path/source_relative_path/source_file_name from the
    /// file_snapshot → library_folder → library JOIN chain.
    /// Mirrors Python `_snapshot_history_sources`.
    pub fn backfill_history_sources(
        &self,
        record_id: i64,
        file_snapshot_id: i64,
    ) -> Result<(), String> {
        self.conn.execute(
        "UPDATE compression_history SET \
         source_library_id = (SELECT l.id FROM file_snapshot fs \
                              JOIN library_folder lf ON fs.library_folder_id = lf.id \
                              JOIN library l ON lf.library_id = l.id WHERE fs.id = ?2), \
         source_library_folder_id = (SELECT fs.library_folder_id FROM file_snapshot fs WHERE fs.id = ?2), \
         source_library_name = (SELECT l.name FROM file_snapshot fs \
                                JOIN library_folder lf ON fs.library_folder_id = lf.id \
                                JOIN library l ON lf.library_id = l.id WHERE fs.id = ?2), \
         source_folder_path = (SELECT lf.path FROM file_snapshot fs \
                               JOIN library_folder lf ON fs.library_folder_id = lf.id WHERE fs.id = ?2), \
         source_relative_path = (SELECT fs.relative_path FROM file_snapshot fs WHERE fs.id = ?2), \
         source_file_name = (SELECT fs.file_name FROM file_snapshot fs WHERE fs.id = ?2) \
         WHERE id = ?1",
        params![record_id, file_snapshot_id],
    ).map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn get_batch_progress(&self, batch_id: &str) -> Result<serde_json::Value, String> {
        let mut rows = self
            .conn
            .prepare("SELECT status, progress FROM compression_history WHERE batch_id=?1")
            .map_err(|e| e.to_string())?;
        let mut total = 0i64;
        let mut completed = 0i64;
        let mut failed = 0i64;
        let mut cancelled = 0i64;
        let mut discarded = 0i64;
        let mut skipped = 0i64;
        let mut running = 0i64;
        let mut pending_count = 0i64;
        let mut progress_sum = 0.0f64;
        let mapped = rows
            .query_map(params![batch_id], |row| {
                let s: String = row.get(0)?;
                let p: f64 = row.get(1)?;
                total += 1;
                match s.as_str() {
                    "completed" => completed += 1,
                    "failed" => failed += 1,
                    "cancelled" => cancelled += 1,
                    "discarded" => discarded += 1,
                    "skipped" => skipped += 1,
                    "running" => running += 1,
                    _ => pending_count += 1,
                }
                progress_sum += p.clamp(0.0, 100.0);
                Ok(())
            })
            .map_err(|e| e.to_string())?;
        for row in mapped {
            row.map_err(|e| e.to_string())?;
        }
        let pct = if total > 0 {
            progress_sum / total as f64
        } else {
            0.0
        };
        Ok(serde_json::json!({
            "total": total, "completed": completed, "failed": failed,
            "cancelled": cancelled, "discarded": discarded, "skipped": skipped,
            "running": running, "pending": pending_count,
            "percentage": pct,
        }))
    }

    /// Join-based history query (H-030): reads live data from
    /// compression_history ← file_snapshot ← library_folder ← library.
    ///
    /// Unlike `get_compression_history` which reads stored copy columns
    /// (`source_folder_path`, `source_relative_path`), this method computes
    /// the real-time source path from the relational chain, ensuring the
    /// history always reflects the current folder paths even after moves/renames.
    pub fn get_compression_history_joined(
        &self,
    ) -> Result<Vec<crate::domain::models::HistoryEntry>, String> {
        use crate::domain::models::HistoryEntry;
        let mut stmt = self.conn.prepare(
        "SELECT \
         ch.id, \
         COALESCE(lf.path || '/' || fs.relative_path, ch.source_folder_path || ch.source_relative_path, ch.source_relative_path, ''), \
         ch.output_path, \
         COALESCE(ch.original_size, 0), \
         COALESCE(ch.output_size_bytes, 0), \
         COALESCE(ch.savings_pct, 0.0), \
         ch.strategy_name, \
         COALESCE(ch.encoder, ''), \
         COALESCE(ch.status, ''), \
         COALESCE(ch.duration_seconds, 0) * 1000, \
         COALESCE(ch.completed_at, ''), \
         CASE WHEN ch.status = 'completed' THEN 1 ELSE 0 END, \
         COALESCE(ch.cq_value, 0), \
         COALESCE(ch.preset, ''), \
         COALESCE(ch.pix_fmt, ''), \
         COALESCE(ch.audio_mode, ''), \
         COALESCE(ch.sub_mode, ''), \
         COALESCE(ch.ffmpeg_command, ''), \
         COALESCE(ch.leanreel_version, ''), \
         COALESCE(ch.batch_id, ''), \
         COALESCE(ch.stage, ''), \
         COALESCE(ch.started_at, ''), \
         COALESCE(ch.source_deleted, 0), \
         COALESCE(ch.error_message, ''), \
         COALESCE(l.name, ch.source_library_name, ''), \
         COALESCE(lf.path, ch.source_folder_path, '') \
         FROM compression_history ch \
         LEFT JOIN file_snapshot fs ON ch.file_snapshot_id = fs.id \
         LEFT JOIN library_folder lf ON fs.library_folder_id = lf.id \
         LEFT JOIN library l ON lf.library_id = l.id \
         ORDER BY COALESCE(ch.completed_at, ch.created_at) DESC"
    ).map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| {
                Ok(HistoryEntry {
                    id: row.get(0)?,
                    source_path: row.get(1)?,
                    output_path: row.get(2)?,
                    source_size_bytes: row.get(3)?,
                    output_size_bytes: row.get(4)?,
                    savings_pct: row.get(5)?,
                    strategy_name: row.get(6)?,
                    encoder: row.get(7)?,
                    status: row.get(8)?,
                    duration_ms: row.get(9)?,
                    completed_at: row.get(10)?,
                    success: row.get::<_, i32>(11)? != 0,
                    cq_value: row.get(12)?,
                    preset: row.get(13)?,
                    pix_fmt: row.get(14)?,
                    audio_mode: row.get(15)?,
                    sub_mode: row.get(16)?,
                    ffmpeg_command: row.get(17)?,
                    leanreel_version: row.get(18)?,
                    batch_id: row.get(19)?,
                    stage: row.get(20)?,
                    started_at: row.get(21)?,
                    source_deleted: row.get::<_, i32>(22)? != 0,
                    error_message: row.get(23)?,
                })
            })
            .map_err(|e| e.to_string())?;
        let mut results = Vec::new();
        for row in rows {
            results.push(row.map_err(|e| e.to_string())?);
        }
        Ok(results)
    }

    // TODO: Use LEFT JOIN to file_snapshot → library_folder → library for source paths
    // instead of stored `source_folder_path || source_relative_path` (redundant columns).
    // Python uses JOIN to fetch real-time folder data; Rust currently reads stored copies.
    pub fn get_compression_history(
        &self,
    ) -> Result<Vec<crate::domain::models::HistoryEntry>, String> {
        use crate::domain::models::HistoryEntry;
        let mut stmt = self
            .conn
            .prepare(
                "SELECT \
         id, \
         COALESCE(source_folder_path || source_relative_path, source_relative_path, ''), \
         output_path, \
         COALESCE(original_size, 0), \
         COALESCE(output_size_bytes, 0), \
         COALESCE(savings_pct, 0.0), \
         strategy_name, \
         COALESCE(encoder, ''), \
         COALESCE(status, ''), \
         COALESCE(duration_seconds, 0) * 1000, \
         COALESCE(completed_at, ''), \
         CASE WHEN status = 'completed' THEN 1 ELSE 0 END, \
         COALESCE(cq_value, 0), \
         COALESCE(preset, ''), \
         COALESCE(pix_fmt, ''), \
         COALESCE(audio_mode, ''), \
         COALESCE(sub_mode, ''), \
         COALESCE(ffmpeg_command, ''), \
         COALESCE(leanreel_version, ''), \
         COALESCE(batch_id, ''), \
         COALESCE(stage, ''), \
         COALESCE(started_at, ''), \
         COALESCE(source_deleted, 0), \
         COALESCE(error_message, '') \
         FROM compression_history ORDER BY COALESCE(completed_at, created_at) DESC",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| {
                Ok(HistoryEntry {
                    id: row.get(0)?,
                    source_path: row.get(1)?,
                    output_path: row.get(2)?,
                    source_size_bytes: row.get(3)?,
                    output_size_bytes: row.get(4)?,
                    savings_pct: row.get(5)?,
                    strategy_name: row.get(6)?,
                    encoder: row.get(7)?,
                    status: row.get(8)?,
                    duration_ms: row.get(9)?,
                    completed_at: row.get(10)?,
                    success: row.get::<_, i32>(11)? != 0,
                    // ── Expanded fields (M8 fix) ──────────────────────────
                    cq_value: row.get(12)?,
                    preset: row.get(13)?,
                    pix_fmt: row.get(14)?,
                    audio_mode: row.get(15)?,
                    sub_mode: row.get(16)?,
                    ffmpeg_command: row.get(17)?,
                    leanreel_version: row.get(18)?,
                    batch_id: row.get(19)?,
                    stage: row.get(20)?,
                    started_at: row.get(21)?,
                    source_deleted: row.get::<_, i32>(22)? != 0,
                    error_message: row.get(23)?,
                })
            })
            .map_err(|e| e.to_string())?;
        let mut results = Vec::new();
        for row in rows {
            results.push(row.map_err(|e| e.to_string())?);
        }
        Ok(results)
    }

    // --- App Config ---

    pub fn get_config(&self, key: &str) -> Option<String> {
        self.conn
            .query_row(
                "SELECT value FROM app_config WHERE key = ?1",
                params![key],
                |row| row.get(0),
            )
            .ok()
    }

    pub fn set_config(&self, key: &str, value: &str) -> Result<(), String> {
        self.conn
            .execute(
                "INSERT OR REPLACE INTO app_config (key, value) VALUES (?1, ?2)",
                params![key, value],
            )
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    // --- Library CRUD ---

    pub fn create_library(&self, name: &str) -> Result<i64, String> {
        self.conn
            .execute("INSERT INTO library (name) VALUES (?1)", params![name])
            .map_err(|e| format!("创建库失败: {}", e))?;
        Ok(self.conn.last_insert_rowid())
    }

    pub fn delete_library(&self, id: i64) -> Result<bool, String> {
        let affected = self
            .conn
            .execute("DELETE FROM library WHERE id = ?1", params![id])
            .map_err(|e| format!("删除库失败: {}", e))?;
        Ok(affected > 0)
    }

    pub fn add_folder(&self, library_id: i64, path: &str) -> Result<i64, String> {
        // Case-insensitive duplicate check
        let existing: bool = self.conn
            .query_row(
                "SELECT COUNT(*) > 0 FROM library_folder WHERE library_id = ?1 AND LOWER(path) = LOWER(?2)",
                params![library_id, path],
                |row| row.get(0),
            )
            .unwrap_or(false);
        if existing {
            return Err(format!("文件夹已存在: {}", path));
        }
        self.conn
            .execute(
                "INSERT INTO library_folder (library_id, path) VALUES (?1, ?2)",
                params![library_id, path],
            )
            .map_err(|e| format!("添加文件夹失败: {}", e))?;
        Ok(self.conn.last_insert_rowid())
    }

    pub fn remove_folder(&self, folder_id: i64) -> Result<bool, String> {
        let affected = self
            .conn
            .execute(
                "DELETE FROM library_folder WHERE id = ?1",
                params![folder_id],
            )
            .map_err(|e| format!("删除文件夹失败: {}", e))?;
        Ok(affected > 0)
    }

    pub fn get_libraries(&self) -> Result<Vec<LibraryInfo>, String> {
        let mut stmt = self
            .conn
            .prepare("SELECT id, name, created_at FROM library ORDER BY created_at DESC")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(|e| e.to_string())?;
        // Collect all rows first — releasing the statement before we call
        // get_folders() which needs its own prepared statement on the same conn.
        let mut lib_data: Vec<(i64, String, String)> = Vec::new();
        for row in rows {
            lib_data.push(row.map_err(|e| e.to_string())?);
        }
        drop(stmt);
        let mut libs = Vec::new();
        for (id, name, created_at) in lib_data {
            let folders = self.get_folders(id).unwrap_or_default();
            libs.push(LibraryInfo {
                id,
                name,
                created_at,
                folders,
            });
        }
        Ok(libs)
    }

    pub fn get_folders(&self, library_id: i64) -> Result<Vec<FolderInfo>, String> {
        let mut stmt = self
            .conn
            .prepare("SELECT id, path FROM library_folder WHERE library_id = ?1")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params![library_id], |row| {
                Ok(FolderInfo {
                    id: row.get(0)?,
                    path: row.get(1)?,
                })
            })
            .map_err(|e| e.to_string())?;
        let mut folders = Vec::new();
        for row in rows {
            folders.push(row.map_err(|e| e.to_string())?);
        }
        Ok(folders)
    }

    /// Query a single folder's path by folder_id (used to resolve relative paths to absolute).
    pub fn get_folder_path_by_id(&self, folder_id: i64) -> Result<String, String> {
        self.conn
            .query_row(
                "SELECT path FROM library_folder WHERE id = ?1",
                params![folder_id],
                |row| row.get(0),
            )
            .map_err(|e| format!("文件夹未找到 (id={}): {}", folder_id, e))
    }

    pub fn get_by_folder_path(
        &self,
        folder_id: i64,
        path: &Path,
    ) -> Result<Option<FileSnapshot>, String> {
        let relative = path.to_string_lossy().replace('\\', "/");
        eprintln!(
            "DB_LOOKUP: searching for path='{}' folder_id={}",
            relative, folder_id
        );
        let fields = "SELECT id, library_folder_id, relative_path, file_name, size_bytes, video_codec, video_width, video_height, hdr_type, audio_tracks, subtitle_tracks, duration_seconds, bitrate_bps, file_mtime, probe_ok, probe_error, scanned_at, pix_fmt, frame_rate, color_primaries, color_transfer, color_space FROM file_snapshot";
        let sql = if folder_id > 0 {
            format!(
                "{fields} WHERE library_folder_id = ?1 AND REPLACE(relative_path, '\\', '/') = ?2"
            )
        } else {
            format!("{fields} WHERE REPLACE(relative_path, '\\', '/') = ?1 LIMIT 1")
        };
        let params: &[&dyn rusqlite::types::ToSql] = if folder_id > 0 {
            &[&folder_id, &relative]
        } else {
            &[&relative]
        };
        let result = self
            .conn
            .query_row(&sql, params, row_to_snapshot)
            .optional();
        if !matches!(result, Ok(Some(_))) {
            // Debug: list similar paths in DB
            let stmt = self.conn.prepare("SELECT relative_path FROM file_snapshot WHERE relative_path LIKE '%' || ?1 || '%' LIMIT 5").ok();
            if let Some(mut s) = stmt {
                let needle = relative.rsplit('/').next().unwrap_or(&relative);
                if let Ok(rows) = s.query_map(params![needle], |row| row.get::<_, String>(0)) {
                    eprintln!("DB_LOOKUP: similar paths in DB:");
                    for r in rows.flatten() {
                        eprintln!("  '{}'", r);
                    }
                }
            }
        }
        result.map_err(|e| e.to_string())
    }

    pub fn open_readonly(path: &Path) -> Result<Self, String> {
        let conn = Connection::open_with_flags(path, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
            .map_err(|e| e.to_string())?;
        Ok(Self { conn })
    }

    fn create_tables(&self) -> Result<(), String> {
        // Fix 1: PRAGMA foreign_keys = ON (match Python behavior)
        self.conn
            .execute_batch("PRAGMA foreign_keys = ON;")
            .map_err(|e| e.to_string())?;
        self.conn
            .execute_batch("PRAGMA journal_mode = WAL;")
            .map_err(|e| e.to_string())?;

        self.conn
            .execute_batch(
                "
            CREATE TABLE IF NOT EXISTS library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS library_folder (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_id INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                UNIQUE(library_id, path)
            );
            CREATE TABLE IF NOT EXISTS file_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_folder_id INTEGER NOT NULL REFERENCES library_folder(id) ON DELETE CASCADE,
                relative_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                size_bytes INTEGER DEFAULT 0,
                video_codec TEXT DEFAULT '',
                video_width INTEGER DEFAULT 0,
                video_height INTEGER DEFAULT 0,
                hdr_type TEXT DEFAULT 'SDR',
                audio_tracks TEXT DEFAULT '[]',
                subtitle_tracks TEXT DEFAULT '[]',
                duration_seconds REAL DEFAULT 0,
                bitrate_bps INTEGER DEFAULT 0,
                file_mtime REAL DEFAULT 0,
                probe_ok INTEGER DEFAULT 0,
                probe_error TEXT DEFAULT '',
                scanned_at TEXT DEFAULT (datetime('now','localtime')),
                pix_fmt TEXT DEFAULT '',
                frame_rate TEXT DEFAULT '',
                color_primaries TEXT DEFAULT '',
                color_transfer TEXT DEFAULT '',
                color_space TEXT DEFAULT '',
                UNIQUE(library_folder_id, relative_path)
            );
            CREATE TABLE IF NOT EXISTS compression_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_snapshot_id INTEGER REFERENCES file_snapshot(id) ON DELETE SET NULL,
                strategy_name TEXT NOT NULL,
                original_size INTEGER DEFAULT 0,
                compressed_size INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                duration_seconds INTEGER DEFAULT 0,
                error_message TEXT DEFAULT '',
                output_path TEXT DEFAULT '',
                output_size_bytes INTEGER DEFAULT 0,
                savings_pct REAL DEFAULT 0,
                encoder TEXT DEFAULT '',
                cq_value INTEGER DEFAULT 0,
                preset TEXT DEFAULT '',
                pix_fmt TEXT DEFAULT '',
                audio_mode TEXT DEFAULT '',
                sub_mode TEXT DEFAULT '',
                ffmpeg_command TEXT DEFAULT '',
                sidecar_path TEXT DEFAULT '',
                leanreel_version TEXT DEFAULT '',
                source_deleted INTEGER DEFAULT 0,
                progress REAL DEFAULT 0,
                stage TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                batch_id TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                source_library_id INTEGER DEFAULT 0,
                source_library_folder_id INTEGER DEFAULT 0,
                source_library_name TEXT DEFAULT '',
                source_folder_path TEXT DEFAULT '',
                source_relative_path TEXT DEFAULT '',
                source_file_name TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS app_config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            ",
            )
            .map_err(|e| e.to_string())?;
        // Migrate: add columns that may be missing from older DBs
        self.migrate_add_columns()
    }

    fn migrate_add_columns(&self) -> Result<(), String> {
        let migrations: &[&str] = &[
            "ALTER TABLE file_snapshot ADD COLUMN file_mtime REAL DEFAULT 0",
            "ALTER TABLE file_snapshot ADD COLUMN probe_ok INTEGER DEFAULT 0",
            "ALTER TABLE file_snapshot ADD COLUMN probe_error TEXT DEFAULT ''",
            "ALTER TABLE file_snapshot ADD COLUMN pix_fmt TEXT DEFAULT ''",
            "ALTER TABLE file_snapshot ADD COLUMN frame_rate TEXT DEFAULT ''",
            "ALTER TABLE file_snapshot ADD COLUMN color_primaries TEXT DEFAULT ''",
            "ALTER TABLE file_snapshot ADD COLUMN color_transfer TEXT DEFAULT ''",
            "ALTER TABLE file_snapshot ADD COLUMN color_space TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN output_path TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN output_size_bytes INTEGER DEFAULT 0",
            "ALTER TABLE compression_history ADD COLUMN savings_pct REAL DEFAULT 0",
            "ALTER TABLE compression_history ADD COLUMN encoder TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN cq_value INTEGER DEFAULT 0",
            "ALTER TABLE compression_history ADD COLUMN preset TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN pix_fmt TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN audio_mode TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN sub_mode TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN ffmpeg_command TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN sidecar_path TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN leanreel_version TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN source_deleted INTEGER DEFAULT 0",
            "ALTER TABLE compression_history ADD COLUMN progress REAL DEFAULT 0",
            "ALTER TABLE compression_history ADD COLUMN stage TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN started_at TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN completed_at TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN updated_at TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN batch_id TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN source_library_id INTEGER DEFAULT 0",
            "ALTER TABLE compression_history ADD COLUMN source_library_folder_id INTEGER DEFAULT 0",
            "ALTER TABLE compression_history ADD COLUMN source_library_name TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN source_folder_path TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN source_relative_path TEXT DEFAULT ''",
            "ALTER TABLE compression_history ADD COLUMN source_file_name TEXT DEFAULT ''",
        ];
        for sql in migrations {
            // SQLite has no IF NOT EXISTS for ALTER TABLE — ignore "duplicate column" errors
            if let Err(e) = self.conn.execute(sql, []) {
                let msg = e.to_string();
                if !msg.contains("duplicate column") {
                    return Err(msg);
                }
            }
        }
        Ok(())
    }
}

impl SnapshotStore for SqliteSnapshotStore {
    // Fix 2: wrap upsert in a transaction for batch performance
    fn upsert(&self, snapshots: &[FileSnapshot]) -> Result<usize, String> {
        self.conn
            .execute("BEGIN IMMEDIATE", [])
            .map_err(|e| e.to_string())?;
        let result = self.do_upsert(snapshots);
        if result.is_ok() {
            self.conn.execute("COMMIT", []).map_err(|e| e.to_string())?;
        } else {
            // M9: Explicit rollback on failure so partial inserts are never visible.
            let _ = self.conn.execute("ROLLBACK", []);
        }
        result
    }

    fn query(&self, filter: &FileFilter) -> Result<Vec<FileSnapshot>, String> {
        let mut sql = String::from(
            "SELECT fs.id, fs.library_folder_id, fs.relative_path, fs.file_name, fs.size_bytes, fs.video_codec, fs.video_width, fs.video_height, fs.hdr_type, fs.audio_tracks, fs.subtitle_tracks, fs.duration_seconds, fs.bitrate_bps, fs.file_mtime, fs.probe_ok, fs.probe_error, fs.scanned_at, fs.pix_fmt, fs.frame_rate, fs.color_primaries, fs.color_transfer, fs.color_space FROM file_snapshot fs"
        );
        let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();

        if filter.library_id.is_some() {
            sql.push_str(" JOIN library_folder lf ON fs.library_folder_id = lf.id");
        }
        sql.push_str(" WHERE 1=1");

        if let Some(library_id) = filter.library_id {
            sql.push_str(" AND lf.library_id = ?");
            param_values.push(Box::new(library_id));
        }
        if let Some(folder_id) = filter.folder_id {
            sql.push_str(" AND fs.library_folder_id = ?");
            param_values.push(Box::new(folder_id));
        }
        if filter.probe_ok_only.unwrap_or(false) {
            sql.push_str(" AND fs.probe_ok = 1");
        }

        let mut stmt = self.conn.prepare(&sql).map_err(|e| e.to_string())?;
        let param_refs: Vec<&dyn rusqlite::types::ToSql> =
            param_values.iter().map(|p| p.as_ref()).collect();

        let rows = stmt
            .query_map(param_refs.as_slice(), row_to_snapshot)
            .map_err(|e| e.to_string())?;

        let mut results = Vec::new();
        for row in rows {
            results.push(row.map_err(|e| e.to_string())?);
        }
        Ok(results)
    }

    /// NOTE: Currently DELETEs rows. Python version keeps deleted records with a flag.
    /// Consider adding a `deleted` column to file_snapshot table for soft-delete
    /// (UPDATE file_snapshot SET deleted=1 WHERE ... instead of DELETE).
    fn mark_deleted(&self, folder_id: i64, path: &Path) -> Result<bool, String> {
        let relative = path.to_string_lossy().to_string();
        let affected = self
            .conn
            .execute(
                "DELETE FROM file_snapshot WHERE library_folder_id = ?1 AND relative_path = ?2",
                params![folder_id, relative],
            )
            .map_err(|e| e.to_string())?;
        Ok(affected > 0)
    }

    // Fix 3: document the O(n) scan limitation and fix probe_ok_only
    fn get_by_path(&self, path: &Path) -> Result<Option<FileSnapshot>, String> {
        // NOTE: This scans all records. For production use, add folder_id to
        // signature and query by (library_folder_id, relative_path) compound key.
        let relative = path.to_string_lossy().to_string();
        let filter = FileFilter {
            library_id: None,
            folder_id: None,
            probe_ok_only: None,
        };
        let all = self.query(&filter)?;
        Ok(all.into_iter().find(|s| s.relative_path == relative))
    }

    // Fix 4: use ORDER BY RANDOM() LIMIT 1 instead of loading all rows
    fn random_snapshot(&self) -> Result<Option<FileSnapshot>, String> {
        let result = self.conn.query_row(
            "SELECT id, library_folder_id, relative_path, file_name, size_bytes, video_codec, video_width, video_height, hdr_type, audio_tracks, subtitle_tracks, duration_seconds, bitrate_bps, file_mtime, probe_ok, probe_error, scanned_at, pix_fmt, frame_rate, color_primaries, color_transfer, color_space FROM file_snapshot ORDER BY RANDOM() LIMIT 1",
            [],
            row_to_snapshot,
        );
        match result {
            Ok(snap) => Ok(Some(snap)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    }

    /// C2: Runtime status/progress update during encoding (mirrors Python `_update_runtime`).
    fn update_compression_runtime(
        &self,
        record_id: i64,
        status: &str,
        progress: f64,
        stage: &str,
        duration_seconds: i64,
    ) -> Result<(), String> {
        self.conn.execute(
            "UPDATE compression_history SET status=?1, progress=?2, stage=?3, duration_seconds=?4, started_at=CASE WHEN started_at='' THEN datetime('now','localtime') ELSE started_at END, updated_at=datetime('now','localtime') WHERE id=?5",
            params![status, progress, stage, duration_seconds, record_id],
        ).map_err(|e| e.to_string())?;
        Ok(())
    }

    /// C2: Finalize a compression record on encode completion or failure.
    fn finish_compression(&self, params: FinishCompressionParams<'_>) -> Result<(), String> {
        let FinishCompressionParams {
            record_id,
            status,
            progress,
            duration_seconds,
            compressed_size,
            error_message,
            sidecar_path,
            source_deleted,
            ffmpeg_command,
        } = params;
        let orig: i64 = self
            .conn
            .query_row(
                "SELECT COALESCE(original_size, 1) FROM compression_history WHERE id=?1",
                params![record_id],
                |row| row.get(0),
            )
            .unwrap_or(1);
        let pct = if compressed_size > 0 && orig > 0 {
            (orig - compressed_size) as f64 / orig as f64 * 100.0
        } else {
            0.0
        };
        self.conn.execute(
            "UPDATE compression_history SET status=?1, progress=?2, duration_seconds=?3, compressed_size=?4, output_size_bytes=?4, savings_pct=?5, error_message=?6, sidecar_path=?7, source_deleted=?8, ffmpeg_command=?9, completed_at=datetime('now','localtime'), updated_at=datetime('now','localtime') WHERE id=?10",
            params![status, progress, duration_seconds, compressed_size, pct, error_message, sidecar_path, source_deleted, ffmpeg_command, record_id],
        ).map_err(|e| e.to_string())?;
        Ok(())
    }
}

// --- private helpers ---

impl SqliteSnapshotStore {
    // Fix 2 (part 2): actual upsert logic extracted for transaction wrapping
    fn do_upsert(&self, snapshots: &[FileSnapshot]) -> Result<usize, String> {
        let mut count = 0;
        for snap in snapshots {
            let audio_json =
                serde_json::to_string(&snap.audio_tracks).unwrap_or_else(|_| "[]".into());
            let sub_json =
                serde_json::to_string(&snap.subtitle_tracks).unwrap_or_else(|_| "[]".into());
            let codec_str = match &snap.video_codec {
                VideoCodec::H264 => "h264",
                VideoCodec::Hevc => "hevc",
                VideoCodec::Av1 => "av1",
                VideoCodec::Vp9 => "vp9",
                VideoCodec::Mpeg2 => "mpeg2",
                VideoCodec::Vc1 => "vc1",
                VideoCodec::Unknown(s) => s.as_str(),
            };
            // Encode hdr_type in Python-compatible format (DV_P5/DV_P7/DV_P8)
            let hdr_str = match &snap.hdr_type {
                HdrType::Sdr => "SDR".to_string(),
                HdrType::Hdr10 => "HDR10".to_string(),
                HdrType::Hdr10Plus => "HDR10+".to_string(),
                HdrType::DolbyVision { profile } => match profile {
                    DvProfile::Profile5 => "DV_P5".to_string(),
                    DvProfile::Profile7 => "DV_P7".to_string(),
                    DvProfile::Profile8_1 | DvProfile::Profile8_4 => "DV_P8".to_string(),
                },
            };

            self.conn.execute(
                "INSERT INTO file_snapshot (library_folder_id, relative_path, file_name, size_bytes, video_codec, video_width, video_height, hdr_type, audio_tracks, subtitle_tracks, duration_seconds, bitrate_bps, file_mtime, probe_ok, probe_error, scanned_at, pix_fmt, frame_rate, color_primaries, color_transfer, color_space)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21)
                 ON CONFLICT(library_folder_id, relative_path) DO UPDATE SET
                 file_name=excluded.file_name,
                 size_bytes=excluded.size_bytes, video_codec=excluded.video_codec,
                 video_width=excluded.video_width, video_height=excluded.video_height,
                 hdr_type=excluded.hdr_type, audio_tracks=excluded.audio_tracks,
                 subtitle_tracks=excluded.subtitle_tracks, duration_seconds=excluded.duration_seconds,
                 bitrate_bps=excluded.bitrate_bps, file_mtime=excluded.file_mtime,
                 probe_ok=excluded.probe_ok, probe_error=excluded.probe_error,
                 scanned_at=excluded.scanned_at, pix_fmt=excluded.pix_fmt,
                 frame_rate=excluded.frame_rate, color_primaries=excluded.color_primaries,
                 color_transfer=excluded.color_transfer, color_space=excluded.color_space",
                params![
                    snap.library_folder_id,
                    snap.relative_path,
                    snap.file_name,
                    snap.size_bytes,
                    codec_str,
                    snap.video_width,
                    snap.video_height,
                    hdr_str,
                    audio_json,
                    sub_json,
                    snap.duration_seconds,
                    snap.bitrate_bps,
                    snap.file_mtime,
                    snap.probe_ok as i32,
                    snap.probe_error,
                    snap.scanned_at,
                    snap.pix_fmt,
                    snap.frame_rate,
                    snap.color_primaries,
                    snap.color_transfer,
                    snap.color_space,
                ],
            )
            .map_err(|e| e.to_string())?;
            count += 1;
        }
        Ok(count)
    }
}
