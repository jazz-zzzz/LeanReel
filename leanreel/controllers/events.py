"""Typed event payloads for controller-to-UI communication."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from leanreel.domain.models import FileSnapshot, TaskStatus


@dataclass(frozen=True)
class FolderScanInput:
    folder_id: int
    path: str
    files: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __init__(self, folder_id: int, path: str, files: Iterable[tuple[str, str]] = ()):
        object.__setattr__(self, "folder_id", int(folder_id))
        object.__setattr__(self, "path", str(path))
        object.__setattr__(self, "files", tuple((str(rel), str(abs_path)) for rel, abs_path in files))

    @classmethod
    def from_legacy(cls, item) -> "FolderScanInput":
        folder_id, path, files = item
        return cls(folder_id=folder_id, path=path, files=files)

    def as_legacy(self) -> tuple[int, str, list[tuple[str, str]]]:
        return self.folder_id, self.path, list(self.files)


@dataclass(frozen=True)
class ScanReadyEvent:
    batch_id: int
    library_id: int | None
    folder_inputs: tuple[FolderScanInput, ...] = field(default_factory=tuple)
    placeholders: tuple[FileSnapshot, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""
    partial: bool = False

    def __init__(
        self,
        batch_id: int,
        library_id: int | None = None,
        folder_inputs: Iterable[FolderScanInput | tuple[int, str, list[tuple[str, str]]]] = (),
        placeholders: Iterable[FileSnapshot] = (),
        warnings: Iterable[str] = (),
        error: str = "",
        partial: bool = False,
    ):
        inputs = tuple(
            item if isinstance(item, FolderScanInput) else FolderScanInput.from_legacy(item)
            for item in folder_inputs
        )
        object.__setattr__(self, "batch_id", int(batch_id))
        object.__setattr__(self, "library_id", library_id)
        object.__setattr__(self, "folder_inputs", inputs)
        object.__setattr__(self, "placeholders", tuple(placeholders))
        object.__setattr__(self, "warnings", tuple(str(w) for w in warnings))
        object.__setattr__(self, "error", str(error))
        object.__setattr__(self, "partial", bool(partial))

    @property
    def folder_ids(self) -> frozenset[int]:
        return frozenset(item.folder_id for item in self.folder_inputs)

    def legacy_args(self):
        return list(self.placeholders), [item.as_legacy() for item in self.folder_inputs], self.batch_id


@dataclass(frozen=True)
class ScanResolvedEvent:
    batch_id: int
    folder_inputs: tuple[FolderScanInput, ...] = field(default_factory=tuple)
    snapshots: tuple[FileSnapshot, ...] = field(default_factory=tuple)
    error: str = ""

    def __init__(
        self,
        batch_id: int,
        folder_inputs: Iterable[FolderScanInput | tuple[int, str, list[tuple[str, str]]]] = (),
        snapshots: Iterable[FileSnapshot] = (),
        error: str = "",
    ):
        inputs = tuple(
            item if isinstance(item, FolderScanInput) else FolderScanInput.from_legacy(item)
            for item in folder_inputs
        )
        object.__setattr__(self, "batch_id", int(batch_id))
        object.__setattr__(self, "folder_inputs", inputs)
        object.__setattr__(self, "snapshots", tuple(snapshots))
        object.__setattr__(self, "error", str(error))

    def legacy_args(self):
        return list(self.snapshots), [item.as_legacy() for item in self.folder_inputs], self.batch_id


@dataclass(frozen=True)
class ProbeResultEvent:
    batch_id: int
    snapshot: FileSnapshot

    def legacy_args(self):
        return self.snapshot, self.batch_id


@dataclass(frozen=True)
class TaskProgressEvent:
    task_id: str
    file_name: str
    input_path: str
    output_path: str
    strategy_name: str
    status: TaskStatus
    progress: float
    error_message: str
    original_size: int
    compressed_size: int
    stage_name: str = ""
    stage_progress: float = 0.0
    stage_indeterminate: bool = False
    sequence: int = 0

    @classmethod
    def from_task(cls, task, sequence: int = 0) -> "TaskProgressEvent":
        stage = getattr(task, "current_stage", None)
        stage_name = ""
        stage_progress = 0.0
        stage_indeterminate = False
        if stage is not None:
            stage_name = getattr(stage.slot, "display_name", "") or ""
            stage_progress = float(getattr(stage, "internal_progress", 0.0) or 0.0)
            progress_type = getattr(getattr(stage, "progress_type", None), "value", "")
            stage_indeterminate = progress_type == "indeterminate"
        return cls(
            task_id=str(getattr(task, "input_path", "")),
            file_name=str(getattr(task, "file_name", "")),
            input_path=str(getattr(task, "input_path", "")),
            output_path=str(getattr(task, "output_path", "")),
            strategy_name=str(getattr(task, "strategy_name", "")),
            status=getattr(task, "status", TaskStatus.PENDING),
            progress=float(getattr(task, "progress", 0.0) or 0.0),
            error_message=str(getattr(task, "error_message", "") or ""),
            original_size=int(getattr(task, "original_size", 0) or 0),
            compressed_size=int(getattr(task, "compressed_size", 0) or 0),
            stage_name=stage_name,
            stage_progress=stage_progress,
            stage_indeterminate=stage_indeterminate,
            sequence=int(sequence),
        )
