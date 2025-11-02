"""Shared data models used across the MinerU client services and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class TaskStatus(str, Enum):
    """Runtime lifecycle states for individual upload files."""

    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HistoryStatus(str, Enum):
    """High-level batch lifecycle used when persisting history entries."""

    UPLOADING = "uploading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class UploadFile:
    """Representation of a single file tracked through upload and parsing phases."""

    path: Path
    display_name: str
    status: TaskStatus = TaskStatus.PENDING
    progress_label: str = "待上传"
    error: Optional[str] = None
    attempts: int = 0
    remote_id: Optional[str] = None

    def as_dict(self) -> Dict[str, str | int | None]:
        """Return a serialisable snapshot useful for UI widgets."""
        return {
            "path": str(self.path),
            "display_name": self.display_name,
            "status": self.status.value,
            "progress_label": self.progress_label,
            "progress": self.progress_label,
            "error": self.error,
            "attempts": self.attempts,
            "remote_id": self.remote_id,
        }


@dataclass
class BatchTask:
    """Aggregate unit describing an API batch upload session."""

    batch_id: Optional[str]
    files: List[UploadFile] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    kind: str = "standard"
    output_dir: Path | None = None

    def mark_completed(self) -> None:
        """Stamp the task with the completion timestamp."""
        self.completed_at = datetime.utcnow()

    def success_count(self) -> int:
        """Count files that completed successfully."""
        return sum(1 for f in self.files if f.status == TaskStatus.COMPLETED)

    def failure_count(self) -> int:
        """Count files that ended in an error state."""
        return sum(1 for f in self.files if f.status == TaskStatus.FAILED)


@dataclass
class HistoryEntry:
    """Persisted batch summary surfaced in the task history UI."""

    batch_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    success: int = 0
    failed: int = 0
    output_dir: str = ""
    status: HistoryStatus = HistoryStatus.UNKNOWN
    files: List[Dict[str, str]] = field(default_factory=list)
    last_error: Optional[str] = None


@dataclass
class ApiError(Exception):
    """Wrapper for API errors that preserves server metadata and status codes."""

    message: str
    status_code: Optional[int] = None
    payload: Optional[Dict[str, str]] = None

    def __str__(self) -> str:
        details = f"{self.message}"
        if self.status_code:
            details += f" (status {self.status_code})"
        return details
