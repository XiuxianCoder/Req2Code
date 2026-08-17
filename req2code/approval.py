from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


class ApprovalStore:
    def __init__(self, path: str = ".req2code/approvals.yaml") -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"approvals": {}}
        with self.path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "approvals" not in data or not isinstance(data["approvals"], dict):
            data["approvals"] = {}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".approvals_", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
            os.replace(temp_name, self.path)
        except Exception:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise

    def submit(self, work_item_id: str, branch: str | None = None) -> None:
        data = self._load()
        data["approvals"][work_item_id] = {
            "status": "pending",
            "branch": branch,
            "comment": "",
        }
        self._save(data)

    def decide(self, work_item_id: str, approved: bool, comment: str = "") -> None:
        data = self._load()
        if work_item_id not in data["approvals"]:
            data["approvals"][work_item_id] = {}
        data["approvals"][work_item_id]["status"] = "approved" if approved else "rejected"
        data["approvals"][work_item_id]["comment"] = comment
        self._save(data)

    def get(self, work_item_id: str) -> dict[str, Any] | None:
        data = self._load()
        return data["approvals"].get(work_item_id)
