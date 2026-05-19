"""Scan progress state for one scan batch."""
from dataclasses import dataclass, field


@dataclass
class ScanState:
    """Owns progress and scope for a single scan token."""

    running: bool = False
    token: int = 0
    library_id: int | None = None
    folder_ids: set[int] = field(default_factory=set)
    total_files: int = 0
    done_files: int = 0
    anchor_folder_id: int = 0

    @property
    def finished(self) -> bool:
        return self.total_files > 0 and self.done_files >= self.total_files

    def owns_any_folder(self, folder_ids: set[int]) -> bool:
        owned = set(self.folder_ids)
        if self.anchor_folder_id:
            owned.add(self.anchor_folder_id)
        return bool(owned.intersection(folder_ids))

    def reset(self):
        self.running = False
        self.token = 0
        self.library_id = None
        self.folder_ids.clear()
        self.total_files = 0
        self.done_files = 0
        self.anchor_folder_id = 0
