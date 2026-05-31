use crate::domain::traits::EncodingJob;
use std::time::Instant;

/// Stage kind — identifies which phase of the pipeline this slot represents.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StageKind {
    Prepare,
    Transcode,
    MoveOut,
}

/// Runtime status of a single pipeline stage.
#[derive(Debug, Clone, PartialEq)]
pub enum StageStatus {
    Pending,
    Running,
    Completed,
    Failed(String),
    Skipped,
}

/// A single slot in the pipeline — defines the stage kind, weight, and tracks runtime state.
#[derive(Debug, Clone)]
pub struct StageSlot {
    pub kind: StageKind,
    /// Weight for overall progress calculation (all weights sum to 1.0)
    pub weight: f32,
    /// Human-readable display name for UI
    pub display_name: String,
    /// Current runtime status
    pub status: StageStatus,
    /// Maximum retry attempts on failure (0 = abort immediately)
    pub max_retries: u32,
    /// Internal progress within this stage (0.0-1.0)
    pub internal_progress: f32,
    /// Optional detail string for UI
    pub detail: String,
    /// Timestamp when stage began
    pub started_at: Option<Instant>,
    /// Timestamp when stage completed
    pub completed_at: Option<Instant>,
    /// Error message if stage failed
    pub error_message: String,
}

impl StageSlot {
    fn new(kind: StageKind, weight: f32, display_name: &str, max_retries: u32) -> Self {
        Self {
            kind,
            weight,
            display_name: display_name.to_string(),
            status: StageStatus::Pending,
            max_retries,
            internal_progress: 0.0,
            detail: String::new(),
            started_at: None,
            completed_at: None,
            error_message: String::new(),
        }
    }
}

/// A multi-stage pipeline plan that tracks progress through each encode phase.
///
/// Architecture: Prepare -> Transcode -> MoveOut (3 stages)
///
/// Stage weights (normalized to 1.0):
/// - prepare: 0.05
/// - transcode: 0.85
/// - move_out: 0.10
#[derive(Debug, Clone)]
pub struct PipelinePlan {
    pub stages: Vec<StageSlot>,
}

impl PipelinePlan {
    /// Build the pipeline plan for a given encoding job.
    pub fn build(_job: &EncodingJob) -> Self {
        let mut stages: Vec<StageSlot> = Vec::new();

        // Stage 1: Prepare — always present
        stages.push(StageSlot::new(StageKind::Prepare, 0.05, "准备", 0));

        // Stage 2: Transcode — always present
        stages.push(StageSlot::new(StageKind::Transcode, 0.85, "压缩视频", 0));

        // Stage 3: Move out — always present
        stages.push(StageSlot::new(StageKind::MoveOut, 0.10, "移入目标", 2));

        Self { stages }
    }

    /// Calculate weighted overall progress from 0.0 to 1.0.
    ///
    /// Completed/skipped/failed stages contribute their full weight.
    /// The currently running stage contributes `internal_progress * weight`.
    /// Pending stages contribute nothing.
    pub fn overall_progress(&self) -> f32 {
        let total_weight: f32 = self.stages.iter().map(|s| s.weight).sum();
        if total_weight == 0.0 {
            return 0.0;
        }

        let mut completed_weight: f32 = 0.0;
        for s in &self.stages {
            match &s.status {
                StageStatus::Completed | StageStatus::Skipped => {
                    completed_weight += s.weight;
                }
                StageStatus::Failed(_) => {
                    // Failed stages still count as "processed" — we won't retry past max_retries
                    completed_weight += s.weight;
                }
                StageStatus::Running => {
                    completed_weight += s.internal_progress * s.weight;
                    // Stop at the running stage — subsequent stages are still pending
                    break;
                }
                StageStatus::Pending => {
                    break;
                }
            }
        }
        (completed_weight / total_weight).min(1.0)
    }

    /// Return the index of the currently running stage, if any.
    pub fn current_stage_index(&self) -> Option<usize> {
        self.stages
            .iter()
            .position(|s| s.status == StageStatus::Running)
    }

    /// Return a reference to the currently running stage, if any.
    pub fn current_stage(&self) -> Option<&StageSlot> {
        self.current_stage_index().and_then(|i| self.stages.get(i))
    }

    /// Mark stage at `index` as Running. All prior stages are marked Completed,
    /// all subsequent stages are set back to Pending.
    pub fn start_stage(&mut self, index: usize) {
        for (i, s) in self.stages.iter_mut().enumerate() {
            if i < index {
                s.status = StageStatus::Completed;
                s.internal_progress = 1.0;
            } else if i == index {
                s.status = StageStatus::Running;
                s.started_at = Some(Instant::now());
            } else {
                s.status = StageStatus::Pending;
            }
        }
    }

    /// Mark stage at `index` as Completed.
    pub fn complete_stage(&mut self, index: usize) {
        if let Some(s) = self.stages.get_mut(index) {
            s.status = StageStatus::Completed;
            s.internal_progress = 1.0;
            s.completed_at = Some(Instant::now());
        }
    }

    /// Mark stage at `index` as Failed with the given error message.
    pub fn fail_stage(&mut self, index: usize, error: impl Into<String>) {
        if let Some(s) = self.stages.get_mut(index) {
            let msg: String = error.into();
            s.error_message = msg.clone();
            s.status = StageStatus::Failed(msg);
            s.completed_at = Some(Instant::now());
        }
    }

    /// Mark all pending stages from `from_index` onward as Skipped.
    /// Used when a stage fails with ABORT policy.
    pub fn skip_remaining(&mut self, from_index: usize) {
        for s in self.stages.iter_mut().skip(from_index) {
            if matches!(s.status, StageStatus::Pending) {
                s.status = StageStatus::Skipped;
            }
        }
    }

    /// Update the internal progress of the stage at `index`.
    ///
    /// Used to feed ffmpeg time= progress into the transcode stage's weight contribution.
    pub fn set_stage_progress(&mut self, index: usize, progress: f32) {
        if let Some(s) = self.stages.get_mut(index) {
            s.internal_progress = progress.clamp(0.0, 1.0);
        }
    }

    /// Number of stages in this plan.
    pub fn len(&self) -> usize {
        self.stages.len()
    }

    /// True if the plan has no stages.
    pub fn is_empty(&self) -> bool {
        self.stages.is_empty()
    }
}

// ── Staging / atomic-commit helpers ──────────────────────────────────────

use std::path::{Path, PathBuf};

/// Compute the temp output path (during encoding) from the final output path.
///
/// Example: `output.mkv` -> `output.tmp.mkv`
pub fn temp_output_path(final_path: &Path) -> PathBuf {
    let mut s = final_path.as_os_str().to_os_string();
    if let (Some(stem), Some(ext)) = (final_path.file_stem(), final_path.extension()) {
        let mut new_name = stem.to_os_string();
        new_name.push(".tmp.");
        new_name.push(ext);
        if let Some(parent) = final_path.parent() {
            PathBuf::from(parent).join(new_name)
        } else {
            PathBuf::from(new_name)
        }
    } else {
        s.push(".tmp");
        PathBuf::from(s)
    }
}

/// Atomic rename (same-filesystem). Temp path is derived from final path.
/// No staging needed — `std::fs::rename` is atomic within the same volume.
pub fn atomic_commit(temp_path: &Path, final_path: &Path) -> Result<(), String> {
    std::fs::rename(temp_path, final_path).map_err(|e| {
        format!(
            "原子提交失败 ({} -> {}): {}",
            temp_path.display(),
            final_path.display(),
            e
        )
    })
}

/// Clean up temp artifacts on error.
pub fn cleanup_temp(final_path: &Path) {
    let temp = temp_output_path(final_path);
    if temp.exists() {
        let _ = std::fs::remove_file(&temp);
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::models::*;
    use std::path::PathBuf;

    fn make_encoding_job(hdr_type: HdrType, dv_handling: &str) -> EncodingJob {
        EncodingJob {
            id: "test-job".into(),
            input_path: PathBuf::from("test.mkv"),
            output_path: PathBuf::from("output.mkv"),
            strategy: Strategy {
                hdr: HdrConfig {
                    dv_handling: dv_handling.to_string(),
                    ..Default::default()
                },
                ..Strategy::default()
            },
            snapshot: FileSnapshot {
                hdr_type: hdr_type.clone(),
                ..FileSnapshot::default()
            },
            has_dolby_vision: matches!(hdr_type, HdrType::DolbyVision { .. }),
        }
    }

    // ── build() tests ──────────────────────────────────────────────────────

    #[test]
    fn test_build_sdr_pipeline_has_three_stages() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let plan = PipelinePlan::build(&job);
        assert_eq!(plan.stages.len(), 3);
        assert_eq!(plan.stages[0].kind, StageKind::Prepare);
        assert_eq!(plan.stages[1].kind, StageKind::Transcode);
        assert_eq!(plan.stages[2].kind, StageKind::MoveOut);
    }

    #[test]
    fn test_build_hdr10_pipeline_has_three_stages() {
        let job = make_encoding_job(HdrType::Hdr10, "");
        let plan = PipelinePlan::build(&job);
        assert_eq!(plan.stages.len(), 3);
        assert_eq!(plan.stages[0].kind, StageKind::Prepare);
        assert_eq!(plan.stages[1].kind, StageKind::Transcode);
        assert_eq!(plan.stages[2].kind, StageKind::MoveOut);
    }

    #[test]
    fn test_build_dv_p7_pipeline_has_three_stages() {
        let dv_p7 = HdrType::DolbyVision {
            profile: DvProfile::Profile7,
        };
        let job = make_encoding_job(dv_p7, "reinject_rpu");
        let plan = PipelinePlan::build(&job);
        assert_eq!(plan.stages.len(), 3);
        assert_eq!(plan.stages[0].kind, StageKind::Prepare);
        assert_eq!(plan.stages[1].kind, StageKind::Transcode);
        assert_eq!(plan.stages[2].kind, StageKind::MoveOut);
    }

    #[test]
    fn test_build_dv_p7_pass_through_pipeline_has_three_stages() {
        let dv_p7 = HdrType::DolbyVision {
            profile: DvProfile::Profile7,
        };
        let job = make_encoding_job(dv_p7, "pass_through");
        let plan = PipelinePlan::build(&job);
        assert_eq!(plan.stages.len(), 3);
        assert_eq!(plan.stages[0].kind, StageKind::Prepare);
        assert_eq!(plan.stages[1].kind, StageKind::Transcode);
        assert_eq!(plan.stages[2].kind, StageKind::MoveOut);
    }

    #[test]
    fn test_build_pipeline_weights_sum_to_one() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let plan = PipelinePlan::build(&job);
        let total: f32 = plan.stages.iter().map(|s| s.weight).sum();
        assert!(
            (total - 1.0).abs() < 0.001,
            "weights sum to {}, expected 1.0",
            total
        );
    }

    #[test]
    fn test_build_sdr_pipeline_weights_sum_to_one() {
        // 3 stages: prepare (0.05) + transcode (0.85) + move_out (0.10) = 1.0
        let job = make_encoding_job(HdrType::Sdr, "");
        let plan = PipelinePlan::build(&job);
        let total: f32 = plan.stages.iter().map(|s| s.weight).sum();
        assert!(
            (total - 1.0).abs() < 0.001,
            "weights sum to {}, expected 1.0",
            total
        );
    }

    #[test]
    fn test_build_all_initial_status_pending() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let plan = PipelinePlan::build(&job);
        for s in &plan.stages {
            assert_eq!(s.status, StageStatus::Pending);
        }
    }

    // ── compute_overall_progress() tests ───────────────────────────────────

    #[test]
    fn test_progress_all_pending_is_zero() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let plan = PipelinePlan::build(&job);
        assert_eq!(plan.overall_progress(), 0.0);
    }

    #[test]
    fn test_progress_all_completed_is_one() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);
        for i in 0..plan.stages.len() {
            plan.complete_stage(i);
        }
        assert!((plan.overall_progress() - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_progress_partial_completion_reflects_weights() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        // Complete prepare (weight 0.05 out of total 1.0) — expect 0.05
        plan.complete_stage(0);
        assert!((plan.overall_progress() - 0.05).abs() < 0.01);

        // Complete transcode (weight 0.85) — expect 0.05 + 0.85 = 0.90
        plan.complete_stage(1);
        assert!((plan.overall_progress() - 0.90).abs() < 0.01);
    }

    #[test]
    fn test_progress_running_stage_contributes_partial() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        // Complete prepare (0.05)
        plan.complete_stage(0);

        // Transcode is running, 50% done
        plan.start_stage(1);
        plan.set_stage_progress(1, 0.5);

        // Expected: 0.05 + 0.5 * 0.85 = 0.475
        let expected = 0.05 + 0.5 * 0.85;
        assert!((plan.overall_progress() - expected).abs() < 0.01);
    }

    #[test]
    fn test_progress_failed_stage_contributes_full_weight() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        // Complete prepare
        plan.complete_stage(0);
        // Transcode fails
        plan.start_stage(1);
        plan.fail_stage(1, "ffmpeg error");

        // Expected: 0.05 + 0.85 = 0.90
        assert!((plan.overall_progress() - 0.90).abs() < 0.01);
    }

    #[test]
    fn test_progress_skipped_stages_contribute_full_weight() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        // Complete prepare, transcode fails, move_out skipped
        plan.complete_stage(0);
        plan.start_stage(1);
        plan.fail_stage(1, "error");
        plan.skip_remaining(2);

        // Expected: 0.05 + 0.85 + 0.10 = 1.0
        assert!((plan.overall_progress() - 1.0).abs() < 0.01);
    }

    // ── stage status transition tests ──────────────────────────────────────

    #[test]
    fn test_start_stage_marks_prior_completed_and_subsequent_pending() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        plan.start_stage(1); // Start transcode

        assert_eq!(plan.stages[0].status, StageStatus::Completed);
        assert_eq!(plan.stages[1].status, StageStatus::Running);
        assert_eq!(plan.stages[2].status, StageStatus::Pending);
    }

    #[test]
    fn test_start_stage_sets_started_at_timestamp() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        assert!(plan.stages[0].started_at.is_none());
        plan.start_stage(0);
        assert!(plan.stages[0].started_at.is_some());
    }

    #[test]
    fn test_complete_stage_sets_internal_progress_to_one() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        plan.start_stage(0);
        plan.set_stage_progress(0, 0.3);
        plan.complete_stage(0);

        assert_eq!(plan.stages[0].status, StageStatus::Completed);
        assert_eq!(plan.stages[0].internal_progress, 1.0);
        assert!(plan.stages[0].completed_at.is_some());
    }

    #[test]
    fn test_fail_stage_stores_error_and_timestamp() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        plan.start_stage(1);
        plan.fail_stage(1, "disk full");

        match &plan.stages[1].status {
            StageStatus::Failed(msg) => assert!(msg.contains("disk full")),
            _ => panic!("Expected Failed status"),
        }
        assert!(plan.stages[1].completed_at.is_some());
        assert!(!plan.stages[1].error_message.is_empty());
    }

    #[test]
    fn test_skip_remaining_only_skips_pending() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        // Complete first stage
        plan.complete_stage(0);

        // Skip from index 1 (transcode)
        plan.skip_remaining(1);

        // Already completed stage should remain completed
        assert_eq!(plan.stages[0].status, StageStatus::Completed);

        // Pending stages from index 1 should be skipped
        assert_eq!(plan.stages[1].status, StageStatus::Skipped);
        assert_eq!(plan.stages[2].status, StageStatus::Skipped);
    }

    #[test]
    fn test_current_stage_index_returns_running_slot() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        assert_eq!(plan.current_stage_index(), None);

        plan.start_stage(1);
        assert_eq!(plan.current_stage_index(), Some(1));
    }

    #[test]
    fn test_set_stage_progress_clamps_to_range() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let mut plan = PipelinePlan::build(&job);

        plan.start_stage(1);

        plan.set_stage_progress(1, -0.5);
        assert_eq!(plan.stages[1].internal_progress, 0.0);

        plan.set_stage_progress(1, 1.5);
        assert_eq!(plan.stages[1].internal_progress, 1.0);

        plan.set_stage_progress(1, 0.42);
        assert_eq!(plan.stages[1].internal_progress, 0.42);
    }

    // ── staging / atomic commit tests ──────────────────────────────────────

    #[test]
    fn test_temp_output_path_appends_suffix() {
        let final_path = PathBuf::from("output.mkv");
        let temp = temp_output_path(&final_path);
        assert_eq!(temp, PathBuf::from("output.tmp.mkv"));
    }

    #[test]
    fn test_atomic_commit_writes_final_file() {
        let dir = std::env::temp_dir().join("leanreel_staging_test");
        let _ = std::fs::create_dir_all(&dir);

        let final_path = dir.join("commit_test.mkv");
        let temp_path = temp_output_path(&final_path);

        // Clean up any leftovers
        cleanup_temp(&final_path);
        if final_path.exists() {
            let _ = std::fs::remove_file(&final_path);
        }

        // Write content to temp file
        let test_content = b"leanreel encoded video content";
        std::fs::write(&temp_path, test_content).unwrap();

        // Atomic commit
        let result = atomic_commit(&temp_path, &final_path);
        assert!(result.is_ok(), "atomic_commit failed: {:?}", result.err());

        // Verify final path exists with correct content
        assert!(final_path.exists(), "final path should exist after commit");
        let content = std::fs::read(&final_path).unwrap();
        assert_eq!(content, test_content);

        // Temp file should be cleaned up
        assert!(!temp_path.exists(), "temp file should be cleaned up");

        // Clean up test artifacts
        let _ = std::fs::remove_file(&final_path);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_cleanup_temp_removes_artifacts() {
        let dir = std::env::temp_dir().join("leanreel_cleanup_test");
        let _ = std::fs::create_dir_all(&dir);

        let final_path = dir.join("cleanup_test.mkv");
        let temp_path = temp_output_path(&final_path);

        // Create dummy temp file
        std::fs::write(&temp_path, b"temp").unwrap();

        assert!(temp_path.exists());

        cleanup_temp(&final_path);

        assert!(!temp_path.exists());

        // Clean up test dir
        if final_path.exists() {
            let _ = std::fs::remove_file(&final_path);
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_len_and_is_empty() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let plan = PipelinePlan::build(&job);
        assert_eq!(plan.len(), 3);
        assert!(!plan.is_empty());
    }

    #[test]
    fn test_stage_slot_max_retries() {
        let job = make_encoding_job(HdrType::Sdr, "");
        let plan = PipelinePlan::build(&job);

        // Prepare: 0 retries
        assert_eq!(plan.stages[0].max_retries, 0);
        // Transcode: 0 retries
        assert_eq!(plan.stages[1].max_retries, 0);
        // MoveOut: 2 retries
        assert_eq!(plan.stages[2].max_retries, 2);
    }

    #[test]
    fn test_build_dv_p8_not_reinject() {
        // DV Profile 8.1 should NOT trigger DV stages
        let dv_p8 = HdrType::DolbyVision {
            profile: DvProfile::Profile8_1,
        };
        let job = make_encoding_job(dv_p8, "reinject_rpu");
        let plan = PipelinePlan::build(&job);
        // DV_P8 with reinject_rpu still only has 3 stages since needs_dovi_processing
        // checks for Profile7 specifically
        assert_eq!(plan.stages.len(), 3);
    }
}
