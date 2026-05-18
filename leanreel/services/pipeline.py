"""编码管线模型 — 阶段的抽象数据模型，无 UI/IO 依赖"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProgressType(Enum):
    DETERMINISTIC = "deterministic"      # 字节级跟踪（文件复制）
    ESTIMATED = "estimated"              # time= 解析（ffmpeg stderr）
    INDETERMINATE = "indeterminate"      # 无进度源（subprocess.run）
    INSTANT = "instant"                  # 瞬时完成


class SlotCategory(Enum):
    PRE_PROCESS = "pre_process"          # 编码之前
    MAIN_PROCESS = "main_process"        # 核心编码
    POST_PROCESS = "post_process"        # 编码之后


class FailurePolicy(Enum):
    ABORT = "abort"
    RETRY = "retry"
    CONTINUE = "continue"


@dataclass
class StageSlot:
    slot_id: str
    display_name: str
    weight: float
    category: SlotCategory = SlotCategory.MAIN_PROCESS
    on_failure: FailurePolicy = FailurePolicy.ABORT
    max_retries: int = 0


@dataclass
class StageTask:
    slot: StageSlot
    progress_type: ProgressType = ProgressType.INSTANT
    internal_progress: float = 0.0
    status: str = "pending"  # pending, running, completed, failed, skipped
    detail: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    error_message: str = ""


@dataclass
class PipelinePlan:
    stages: list[StageTask] = field(default_factory=list)

    def compute_overall_progress(self) -> float:
        total_weight = sum(s.slot.weight for s in self.stages) or 1.0
        completed_weight = 0.0
        for s in self.stages:
            if s.status == "completed":
                completed_weight += s.slot.weight
            elif s.status == "running":
                completed_weight += s.internal_progress * s.slot.weight
                break
            elif s.status in ("failed", "skipped"):
                completed_weight += s.slot.weight
            else:
                break
        return min(1.0, completed_weight / total_weight)

    @property
    def current_stage(self) -> Optional[StageTask]:
        for s in self.stages:
            if s.status == "running":
                return s
        return None

    def mark_stage_running(self, index: int):
        for i, s in enumerate(self.stages):
            if i < index:
                s.status = "completed"
                s.internal_progress = 1.0
            elif i == index:
                s.status = "running"
                s.started_at = __import__("time").time()
            else:
                s.status = "pending"

    def mark_stage_completed(self, index: int):
        if 0 <= index < len(self.stages):
            s = self.stages[index]
            s.status = "completed"
            s.internal_progress = 1.0
            s.completed_at = __import__("time").time()

    def mark_stage_failed(self, index: int, error_message: str):
        if 0 <= index < len(self.stages):
            s = self.stages[index]
            s.status = "failed"
            s.error_message = error_message
            s.completed_at = __import__("time").time()

    def skip_remaining(self, from_index: int):
        for i in range(from_index, len(self.stages)):
            s = self.stages[i]
            if s.status == "pending":
                s.status = "skipped"


# ── 预定义的 stage slot 常量 ──

SLOT_PREPARE = StageSlot("prepare", "准备", weight=1, category=SlotCategory.PRE_PROCESS, on_failure=FailurePolicy.ABORT)
SLOT_COPY_IN = StageSlot("copy_in", "复制到临时目录", weight=2, category=SlotCategory.PRE_PROCESS, on_failure=FailurePolicy.RETRY, max_retries=2)
SLOT_EXTRACT_RPU = StageSlot("extract_rpu", "提取 RPU", weight=2, category=SlotCategory.PRE_PROCESS, on_failure=FailurePolicy.ABORT, max_retries=1)
SLOT_TRANSCODE = StageSlot("transcode", "压缩视频", weight=80, category=SlotCategory.MAIN_PROCESS, on_failure=FailurePolicy.ABORT)
SLOT_INJECT_RPU = StageSlot("inject_rpu", "注入 RPU", weight=2, category=SlotCategory.POST_PROCESS, on_failure=FailurePolicy.ABORT, max_retries=1)
SLOT_MOVE_OUT = StageSlot("move_out", "移入目标", weight=3, category=SlotCategory.POST_PROCESS, on_failure=FailurePolicy.RETRY, max_retries=2)


def build_pipeline(task) -> PipelinePlan:
    """根据任务构建编码阶段管线。"""
    from leanreel.domain.models import HDRType

    stages: list[StageTask] = []

    # 1. 准备阶段（始终存在）
    stages.append(StageTask(slot=SLOT_PREPARE, progress_type=ProgressType.INSTANT))

    # 2. 复制入（如果启用 I/O 分离）
    snap = getattr(task, "snapshot", None)
    strategy = getattr(task, "strategy", None)
    needs_io = strategy is not None and getattr(strategy, "hdr", None) is not None
    # I/O 分离在 FFmpegExecutor 中通过 temp_dir 控制，总是启用
    stages.append(StageTask(slot=SLOT_COPY_IN, progress_type=ProgressType.DETERMINISTIC))

    # 3. 提取 RPU（DV_P7 + reinject_rpu 策略）
    if snap is not None and strategy is not None:
        hdr_type = getattr(snap, "hdr_type", None)
        dv_handling = getattr(getattr(strategy, "hdr", None), "dv_handling", "") if hasattr(strategy, "hdr") else ""
        if hdr_type and hasattr(hdr_type, "value") and hdr_type.value == "DV_P7" and dv_handling == "reinject_rpu":
            stages.append(StageTask(slot=SLOT_EXTRACT_RPU, progress_type=ProgressType.INDETERMINATE))

    # 4. 压缩（始终存在）
    is_copy = strategy is not None and getattr(getattr(strategy, "video", None), "encoder", "") == "copy" if strategy else False
    if is_copy:
        stages.append(StageTask(slot=SLOT_TRANSCODE, progress_type=ProgressType.INSTANT))
    else:
        stages.append(StageTask(slot=SLOT_TRANSCODE, progress_type=ProgressType.ESTIMATED))

    # 5. 注入 RPU（DV_P7 + reinject_rpu）
    if snap is not None and strategy is not None:
        hdr_type = getattr(snap, "hdr_type", None)
        dv_handling = getattr(getattr(strategy, "hdr", None), "dv_handling", "") if hasattr(strategy, "hdr") else ""
        if hdr_type and hasattr(hdr_type, "value") and hdr_type.value == "DV_P7" and dv_handling == "reinject_rpu":
            stages.append(StageTask(slot=SLOT_INJECT_RPU, progress_type=ProgressType.INDETERMINATE))

    # 6. 移出（始终存在）
    stages.append(StageTask(slot=SLOT_MOVE_OUT, progress_type=ProgressType.DETERMINISTIC))

    return PipelinePlan(stages=stages)
