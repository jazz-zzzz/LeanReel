use leanreel_rs_lib::domain::models::*;
use leanreel_rs_lib::services::pipeline::*;
use std::path::PathBuf;

fn make_dv_p7_job() -> leanreel_rs_lib::domain::traits::EncodingJob {
    leanreel_rs_lib::domain::traits::EncodingJob {
        id: "test-dv".into(),
        input_path: PathBuf::from("input.mkv"),
        output_path: PathBuf::from("output.mkv"),
        strategy: Strategy {
            name: "hevc_main".into(),
            hdr: HdrConfig {
                dv_handling: "reinject_rpu".into(),
                ..Default::default()
            },
            video: VideoConfig {
                encoder: "libx265".into(),
                crf: 22,
                ..Default::default()
            },
            ..Strategy::default()
        },
        has_dolby_vision: true,
        snapshot: FileSnapshot {
            hdr_type: HdrType::DolbyVision {
                profile: DvProfile::Profile7,
            },
            duration_seconds: 120.0,
            file_name: "movie.mkv".into(),
            ..FileSnapshot::default()
        },
    }
}

fn make_sdr_job() -> leanreel_rs_lib::domain::traits::EncodingJob {
    leanreel_rs_lib::domain::traits::EncodingJob {
        id: "test-sdr".into(),
        input_path: PathBuf::from("input.mkv"),
        output_path: PathBuf::from("output.mkv"),
        strategy: Strategy {
            name: "fast".into(),
            video: VideoConfig {
                encoder: "libx265".into(),
                crf: 28,
                ..Default::default()
            },
            ..Strategy::default()
        },
        has_dolby_vision: false,
        snapshot: FileSnapshot {
            hdr_type: HdrType::Sdr,
            duration_seconds: 60.0,
            file_name: "show.mkv".into(),
            ..FileSnapshot::default()
        },
    }
}

// ── PipelinePlan::build() tests ───────────────────────────────────────────

#[test]
fn test_build_sdr_pipeline_stage_count() {
    let plan = PipelinePlan::build(&make_sdr_job());
    assert_eq!(plan.len(), 3);
    assert!(!plan.is_empty());
}

#[test]
fn test_build_dv_p7_pipeline_stage_count() {
    let plan = PipelinePlan::build(&make_dv_p7_job());
    assert_eq!(plan.len(), 3);
}

#[test]
fn test_build_dv_p7_stage_kinds_in_order() {
    let plan = PipelinePlan::build(&make_dv_p7_job());
    assert_eq!(plan.stages[0].kind, StageKind::Prepare);
    assert_eq!(plan.stages[1].kind, StageKind::Transcode);
    assert_eq!(plan.stages[2].kind, StageKind::MoveOut);
}

#[test]
fn test_build_sdr_stage_kinds_in_order() {
    let plan = PipelinePlan::build(&make_sdr_job());
    assert_eq!(plan.stages[0].kind, StageKind::Prepare);
    assert_eq!(plan.stages[1].kind, StageKind::Transcode);
    assert_eq!(plan.stages[2].kind, StageKind::MoveOut);
}

#[test]
fn test_build_dv_p8_still_three_stages() {
    // DV Profile 8.1 should still produce 3 stages
    let mut job = make_sdr_job();
    job.snapshot.hdr_type = HdrType::DolbyVision {
        profile: DvProfile::Profile8_1,
    };
    job.strategy.hdr.dv_handling = "reinject_rpu".into();
    let plan = PipelinePlan::build(&job);
    assert_eq!(plan.len(), 3);
    assert_eq!(plan.stages[0].kind, StageKind::Prepare);
    assert_eq!(plan.stages[1].kind, StageKind::Transcode);
    assert_eq!(plan.stages[2].kind, StageKind::MoveOut);
}

#[test]
fn test_build_dv_p7_without_reinject_skips_dovi_stages() {
    let mut job = make_dv_p7_job();
    job.strategy.hdr.dv_handling = "pass_through".into();
    let plan = PipelinePlan::build(&job);
    assert_eq!(plan.len(), 3);
}

#[test]
fn test_weights_sum_to_one_for_dv_p7() {
    let plan = PipelinePlan::build(&make_dv_p7_job());
    let total: f32 = plan.stages.iter().map(|s| s.weight).sum();
    assert!((total - 1.0).abs() < 0.001, "weights sum to {}", total);
}

#[test]
fn test_weights_sum_to_one_for_sdr() {
    // 3 stages: prepare (0.05) + transcode (0.85) + move_out (0.10) = 1.0
    let plan = PipelinePlan::build(&make_sdr_job());
    let total: f32 = plan.stages.iter().map(|s| s.weight).sum();
    assert!((total - 1.0).abs() < 0.001, "weights sum to {}", total);
}

#[test]
fn test_initial_status_all_pending() {
    let plan = PipelinePlan::build(&make_sdr_job());
    for s in &plan.stages {
        assert!(matches!(s.status, StageStatus::Pending));
    }
}

#[test]
fn test_stage_max_retries_correct() {
    let plan = PipelinePlan::build(&make_sdr_job());
    assert_eq!(plan.stages[0].max_retries, 0); // Prepare
    assert_eq!(plan.stages[1].max_retries, 0); // Transcode
    assert_eq!(plan.stages[2].max_retries, 2); // MoveOut
}

// ── compute_overall_progress() tests ───────────────────────────────────────

#[test]
fn test_overall_progress_all_pending_is_zero() {
    let plan = PipelinePlan::build(&make_sdr_job());
    assert_eq!(plan.overall_progress(), 0.0);
}

#[test]
fn test_overall_progress_all_completed_is_one() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    for i in 0..plan.len() {
        plan.complete_stage(i);
    }
    assert!((plan.overall_progress() - 1.0).abs() < 0.001);
}

#[test]
fn test_overall_progress_after_prepare_is_005() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.complete_stage(0); // Prepare weight 0.05
    assert!((plan.overall_progress() - 0.05).abs() < 0.01);
}

#[test]
fn test_overall_progress_after_prepare_and_transcode() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.complete_stage(0); // 0.05
    plan.complete_stage(1); // 0.85
    assert!((plan.overall_progress() - 0.90).abs() < 0.001);
}

#[test]
fn test_overall_progress_running_at_half_contributes_partial_weight() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.complete_stage(0); // Prepare: 0.05
    plan.start_stage(1); // Transcode running
    plan.set_stage_progress(1, 0.5);
    let expected = 0.05 + 0.85 * 0.5;
    assert!((plan.overall_progress() - expected).abs() < 0.01);
}

#[test]
fn test_overall_progress_running_at_quarter_contributes_partial_weight() {
    let dv_plan = PipelinePlan::build(&make_dv_p7_job());
    let mut plan = dv_plan;
    plan.complete_stage(0); // Prepare: 0.05
    plan.start_stage(1); // Transcode running
    plan.set_stage_progress(1, 0.25);
    let expected = 0.05 + 0.85 * 0.25;
    assert!((plan.overall_progress() - expected).abs() < 0.01);
}

#[test]
fn test_overall_progress_failed_stage_contributes_full_weight() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.complete_stage(0); // Prepare: 0.05
    plan.start_stage(1);
    plan.fail_stage(1, "crash");
    assert!((plan.overall_progress() - 0.90).abs() < 0.01);
}

#[test]
fn test_overall_progress_skipped_contributes_full_weight() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.complete_stage(0); // 0.05
    plan.fail_stage(1, "error"); // 0.85
    plan.skip_remaining(2); // 0.10 skipped
    assert!((plan.overall_progress() - 1.0).abs() < 0.01);
}

#[test]
fn test_overall_progress_dv_full_cycle() {
    let mut plan = PipelinePlan::build(&make_dv_p7_job());
    assert_eq!(plan.overall_progress(), 0.0);

    plan.complete_stage(0); // 0.05
    assert!((plan.overall_progress() - 0.05).abs() < 0.01);

    plan.complete_stage(1); // 0.85
    assert!((plan.overall_progress() - 0.90).abs() < 0.01);

    plan.complete_stage(2); // 0.10
    assert!((plan.overall_progress() - 1.0).abs() < 0.001);
}

// ── Stage status transition tests ──────────────────────────────────────────

#[test]
fn test_start_stage_marks_prior_completed() {
    let mut plan = PipelinePlan::build(&make_dv_p7_job());
    plan.start_stage(1); // Jump to transcode
    assert_eq!(plan.stages[0].status, StageStatus::Completed);
    assert_eq!(plan.stages[1].status, StageStatus::Running);
    assert_eq!(plan.stages[2].status, StageStatus::Pending);
}

#[test]
fn test_start_stage_sets_timestamp() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    assert!(plan.stages[0].started_at.is_none());
    plan.start_stage(0);
    assert!(plan.stages[0].started_at.is_some());
}

#[test]
fn test_complete_stage_sets_progress_to_one() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.start_stage(0);
    plan.set_stage_progress(0, 0.3);
    plan.complete_stage(0);
    assert_eq!(plan.stages[0].internal_progress, 1.0);
    assert_eq!(plan.stages[0].status, StageStatus::Completed);
}

#[test]
fn test_fail_stage_stores_error_message() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.start_stage(1);
    plan.fail_stage(1, "disk full");
    match &plan.stages[1].status {
        StageStatus::Failed(msg) => assert!(msg.contains("disk full")),
        _ => panic!("Expected Failed status"),
    }
}

#[test]
fn test_fail_stage_sets_completed_at() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.start_stage(1);
    assert!(plan.stages[1].completed_at.is_none());
    plan.fail_stage(1, "error");
    assert!(plan.stages[1].completed_at.is_some());
}

#[test]
fn test_skip_remaining_preserves_completed_stages() {
    let mut plan = PipelinePlan::build(&make_dv_p7_job());
    plan.complete_stage(0);
    plan.complete_stage(1);
    plan.skip_remaining(2);
    assert_eq!(plan.stages[0].status, StageStatus::Completed);
    assert_eq!(plan.stages[1].status, StageStatus::Completed);
    assert_eq!(plan.stages[2].status, StageStatus::Skipped);
}

#[test]
fn test_skip_remaining_does_not_overwrite_failed() {
    let mut plan = PipelinePlan::build(&make_dv_p7_job());
    plan.complete_stage(0);
    plan.fail_stage(1, "rpu fail");
    plan.skip_remaining(2);
    // Stage 1 should still be Failed, not Skipped
    match &plan.stages[1].status {
        StageStatus::Failed(_) => {} // OK
        _ => panic!("Failed stage should stay Failed, not be overwritten"),
    }
}

#[test]
fn test_current_stage_index_none_when_idle() {
    let plan = PipelinePlan::build(&make_sdr_job());
    assert_eq!(plan.current_stage_index(), None);
}

#[test]
fn test_current_stage_index_returns_running() {
    let mut plan = PipelinePlan::build(&make_sdr_job());
    plan.start_stage(1);
    assert_eq!(plan.current_stage_index(), Some(1));
    assert_eq!(
        plan.current_stage_index(),
        plan.stages
            .iter()
            .position(|s| matches!(s.status, StageStatus::Running))
    );
}

// ── staging / atomic commit tests ──────────────────────────────────────────

#[test]
fn test_temp_output_path_contains_tmp_suffix() {
    let path = PathBuf::from("my_movie.mkv");
    let temp = temp_output_path(&path);
    let s = temp.to_string_lossy();
    assert!(s.contains(".tmp"));
    assert!(s.starts_with("my_movie.tmp"));
}

#[test]
fn test_atomic_commit_produces_final_file() {
    let dir = std::env::temp_dir().join("leanreel_staging_test");
    let _ = std::fs::create_dir_all(&dir);

    let final_path = dir.join("committed.mkv");
    let temp = temp_output_path(&final_path);

    // Clean up any leftovers
    cleanup_temp(&final_path);
    if final_path.exists() {
        let _ = std::fs::remove_file(&final_path);
    }

    let data = b"encoded content for atomic commit test";
    std::fs::write(&temp, data).unwrap();

    let result = atomic_commit(&temp, &final_path);
    assert!(result.is_ok(), "atomic_commit failed: {:?}", result.err());

    assert!(final_path.exists());
    let read_back = std::fs::read(&final_path).unwrap();
    assert_eq!(read_back, data);

    // Temp file cleaned up
    assert!(!temp.exists());
    // Staging file cleaned up
    // no staging — rename removes source atomically

    let _ = std::fs::remove_file(&final_path);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn test_cleanup_temp_removes_artifacts() {
    let dir = std::env::temp_dir().join("leanreel_cleanup_test");
    let _ = std::fs::create_dir_all(&dir);

    let final_path = dir.join("to_clean.mkv");
    let temp = temp_output_path(&final_path);

    std::fs::write(&temp, b"x").unwrap();
    assert!(temp.exists());

    cleanup_temp(&final_path);
    assert!(!temp.exists());

    if final_path.exists() {
        let _ = std::fs::remove_file(&final_path);
    }
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn test_atomic_commit_cleans_temp_even_when_final_exists() {
    let dir = std::env::temp_dir().join("leanreel_overwrite_test");
    let _ = std::fs::create_dir_all(&dir);

    let final_path = dir.join("existing.mkv");
    let temp = temp_output_path(&final_path);

    cleanup_temp(&final_path);
    if final_path.exists() {
        let _ = std::fs::remove_file(&final_path);
    }

    // Pre-create a "final" file to simulate overwrite
    std::fs::write(&final_path, b"old content").unwrap();
    std::fs::write(&temp, b"new content for overwrite test").unwrap();

    let result = atomic_commit(&temp, &final_path);
    assert!(result.is_ok());

    // Should have new content
    let read_back = std::fs::read(&final_path).unwrap();
    assert_eq!(read_back, b"new content for overwrite test");

    // Temp cleaned
    assert!(!temp.exists());

    let _ = std::fs::remove_file(&final_path);
    let _ = std::fs::remove_dir_all(&dir);
}
