from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    REQUIREMENT = "requirement"
    BUG = "bug"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"
    FAILED = "failed"


@dataclass
class WorkItem:
    id: str
    title: str
    description: str
    type: TaskType = TaskType.REQUIREMENT
    source: str = "tapd"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    __test__ = False

    unit_passed: bool
    script_passed: bool
    coverage: float
    details: str = ""


@dataclass
class WorkflowResult:
    work_item_id: str
    status: WorkflowStatus
    branch_name: str | None = None
    commit_id: str | None = None
    dev_report_path: str | None = None
    test_report_path: str | None = None
    review_comment: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None
