from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class RunStatus(str, Enum):
    PREPARING = "preparing"
    DEVELOPING = "developing"
    TESTING = "testing"
    WAITING_APPROVAL = "waiting_approval"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"
    STALE = "stale"
    COMMITTING = "committing"
    PUSHING = "pushing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    run_id: str
    work_items: list[dict[str, Any]]
    engine: str
    repo_path: str
    repo_url: str
    push_url: str
    remote_name: str
    base_branch: str
    work_branch: str
    push_branch: str
    baseline_sha: str
    remote_branch_sha: str | None
    execution_mode: str = "nested_cli"
    branch_mode: str = "selected"
    model: str = ""
    status: str = RunStatus.PREPARING.value
    approval_token: str = ""
    publish_nonce: str = ""
    diff_hash: str = ""
    changed_files: list[str] = field(default_factory=list)
    item_results: list[dict[str, Any]] = field(default_factory=list)
    report_path: str = ""
    analysis: str = ""
    development: str = ""
    test_result: dict[str, Any] = field(default_factory=dict)
    commit_sha: str = ""
    error: str = ""
    approval_comment: str = ""
    project_id: str = ""
    project_memory_revision: int = 0
    project_memory_source_sha: str = ""
    memory_candidate_path: str = ""
    engine_session_id: str = ""
    task_brief: str = ""
    agent_test_evidence: str = ""
    verification_count: int = 0
    preparation_stage: str = ""
    request_fingerprint: str = ""
    sync_before_start: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        payload = dict(data)
        payload.setdefault("push_url", payload.get("repo_url", ""))
        payload.setdefault("model", "")
        payload.setdefault("preparation_stage", "")
        payload.setdefault("request_fingerprint", "")
        payload.setdefault("sync_before_start", False)
        payload.setdefault("publish_nonce", "")
        payload.setdefault("item_results", [])
        return cls(**payload)


class RunStore:
    def __init__(self, state_dir: str | Path = ".req2code") -> None:
        self.root = Path(state_dir).resolve() / "runs"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in {"-", "_"})
        if not safe or safe != run_id:
            raise ValueError("Invalid run id")
        return self.root / f"{safe}.json"

    def save(self, record: RunRecord) -> Path:
        record.updated_at = utc_now()
        path = self._path(record.run_id)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{record.run_id}_", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp_name, path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        return path

    def get(self, run_id: str) -> RunRecord | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def require(self, run_id: str) -> RunRecord:
        record = self.get(run_id)
        if record is None:
            raise KeyError(f"Run not found: {run_id}")
        return record

    def list(self, limit: int = 20) -> list[RunRecord]:
        rows = [RunRecord.from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in self.root.glob("*.json")]
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return rows[: max(1, limit)]
