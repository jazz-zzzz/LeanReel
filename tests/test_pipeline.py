"""管线模型测试"""
import pytest
from leanreel.core.pipeline import (
    StageSlot, StageTask, PipelinePlan, ProgressType, SlotCategory, FailurePolicy,
    SLOT_PREPARE, SLOT_COPY_IN, SLOT_EXTRACT_RPU, SLOT_TRANSCODE, SLOT_INJECT_RPU, SLOT_MOVE_OUT,
)


def test_pipeline_plan_empty_returns_zero():
    plan = PipelinePlan()
    assert plan.compute_overall_progress() == 0.0


def test_pipeline_plan_all_completed_returns_one():
    plan = PipelinePlan(stages=[
        StageTask(slot=SLOT_PREPARE, status="completed", internal_progress=1.0),
        StageTask(slot=SLOT_TRANSCODE, status="completed", internal_progress=1.0),
        StageTask(slot=SLOT_MOVE_OUT, status="completed", internal_progress=1.0),
    ])
    assert plan.compute_overall_progress() == 1.0


def test_pipeline_plan_mid_running_weights_correctly():
    plan = PipelinePlan(stages=[
        StageTask(slot=SLOT_PREPARE, status="completed", internal_progress=1.0),      # weight 1, done
        StageTask(slot=SLOT_TRANSCODE, status="running", internal_progress=0.5),       # weight 80, half done
        StageTask(slot=SLOT_MOVE_OUT, status="pending"),                                # weight 3, not started
    ])
    expected = (1 + 0.5 * 80) / (1 + 80 + 3)  # = 41/84 ≈ 0.488
    assert pytest.approx(plan.compute_overall_progress()) == expected


def test_pipeline_plan_failed_stage_weights_as_completed():
    plan = PipelinePlan(stages=[
        StageTask(slot=SLOT_PREPARE, status="completed"),
        StageTask(slot=SLOT_TRANSCODE, status="failed"),
        StageTask(slot=SLOT_MOVE_OUT, status="skipped"),
    ])
    assert plan.compute_overall_progress() == 1.0


def test_current_stage_returns_running():
    plan = PipelinePlan(stages=[
        StageTask(slot=SLOT_PREPARE, status="completed"),
        StageTask(slot=SLOT_TRANSCODE, status="running"),
        StageTask(slot=SLOT_MOVE_OUT, status="pending"),
    ])
    stage = plan.current_stage
    assert stage is not None
    assert stage.slot.slot_id == "transcode"


def test_current_stage_returns_none_when_none_running():
    plan = PipelinePlan(stages=[
        StageTask(slot=SLOT_PREPARE, status="completed"),
    ])
    assert plan.current_stage is None


def test_mark_stage_running_sets_transitions():
    plan = PipelinePlan(stages=[
        StageTask(slot=SLOT_PREPARE),
        StageTask(slot=SLOT_TRANSCODE),
        StageTask(slot=SLOT_MOVE_OUT),
    ])
    plan.mark_stage_running(1)
    assert plan.stages[0].status == "completed"
    assert plan.stages[1].status == "running"
    assert plan.stages[2].status == "pending"


def test_skip_remaining():
    plan = PipelinePlan(stages=[
        StageTask(slot=SLOT_PREPARE, status="completed"),
        StageTask(slot=SLOT_EXTRACT_RPU, status="failed"),
        StageTask(slot=SLOT_TRANSCODE, status="pending"),
        StageTask(slot=SLOT_MOVE_OUT, status="pending"),
    ])
    plan.skip_remaining(2)
    assert plan.stages[2].status == "skipped"
    assert plan.stages[3].status == "skipped"


def test_dv_pipeline_uses_all_slots():
    """集成：DV_P7 管线使用完整 slot 集合"""
    slots = [SLOT_PREPARE, SLOT_COPY_IN, SLOT_EXTRACT_RPU, SLOT_TRANSCODE, SLOT_INJECT_RPU, SLOT_MOVE_OUT]
    plan = PipelinePlan(stages=[StageTask(slot=s) for s in slots])
    assert len(plan.stages) == 6
    # 验证权重都是正的
    total = sum(s.slot.weight for s in plan.stages)
    assert total > 0


def test_copy_mode_pipeline_is_minimal():
    """集成：copy 模式管线只有最简 slot"""
    slots = [SLOT_PREPARE, SLOT_MOVE_OUT]
    plan = PipelinePlan(stages=[StageTask(slot=s) for s in slots])
    assert len(plan.stages) == 2
