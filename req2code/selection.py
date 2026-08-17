from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from req2code.run_state import utc_now


@dataclass
class WorkItemSelection:
    selection_id: str
    items: list[dict[str, Any]]
    status: str = "open"
    selected_keys: list[str] = field(default_factory=list)
    selected_specs: list[str] = field(default_factory=list)
    source_profile_id: str = ""
    source_profile_name: str = ""
    source: str = ""
    source_analysis_id: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkItemSelection":
        return cls(**data)


class WorkItemSelectionStore:
    """Server-owned work-item selections shared by text and MCP Apps clients."""

    def __init__(self, state_dir: str | Path) -> None:
        self.root = Path(state_dir).expanduser().resolve() / "selections"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, selection_id: str) -> Path:
        safe = "".join(ch for ch in selection_id if ch.isalnum() or ch in {"-", "_"})
        if not safe or safe != selection_id:
            raise ValueError("Invalid selection id")
        return self.root / f"{safe}.json"

    @staticmethod
    def _item_kind(item: dict[str, Any]) -> str:
        metadata = item.get("metadata")
        if item.get("type") == "bug" or (
            isinstance(metadata, dict) and isinstance(metadata.get("Bug"), dict)
        ):
            return "bug"
        return "story"

    @staticmethod
    def _short_key(item: dict[str, Any], used: set[str]) -> str:
        prefix = "B" if WorkItemSelectionStore._item_kind(item) == "bug" else "S"
        item_id = str(item.get("id") or "")
        digits = "".join(ch for ch in item_id if ch.isdigit())
        suffix = (digits[-4:] if digits else item_id[-4:]).upper() or "ITEM"
        base = f"{prefix}{suffix}"
        key = base
        counter = 2
        while key in used:
            key = f"{base}-{counter}"
            counter += 1
        return key

    def create(
        self,
        items: list[dict[str, Any]],
        source_profile_id: str = "",
        source_profile_name: str = "",
        source: str = "",
        source_analysis_id: str = "",
    ) -> WorkItemSelection:
        if not items:
            raise ValueError("No work items are available for selection")
        used: set[str] = set()
        keyed: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            kind = self._item_kind(row)
            row["type"] = "bug" if kind == "bug" else "requirement"
            key = self._short_key(row, used)
            used.add(key)
            row["key"] = key
            row["spec"] = f"{kind}:{row['id']}"
            keyed.append(row)
        selection = WorkItemSelection(
            selection_id=uuid.uuid4().hex[:12],
            items=keyed,
            source_profile_id=source_profile_id,
            source_profile_name=source_profile_name,
            source=source,
            source_analysis_id=source_analysis_id,
        )
        self.save(selection)
        return selection

    def save(self, selection: WorkItemSelection) -> Path:
        selection.updated_at = utc_now()
        path = self._path(selection.selection_id)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{selection.selection_id}_", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(selection.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp_name, path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        return path

    def get(self, selection_id: str) -> WorkItemSelection | None:
        path = self._path(selection_id)
        if not path.is_file():
            return None
        return WorkItemSelection.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def require(self, selection_id: str) -> WorkItemSelection:
        selection = self.get(selection_id)
        if selection is None:
            raise KeyError(f"Work-item selection not found: {selection_id}")
        return selection

    def confirm(self, selection_id: str, selected_keys: list[str]) -> WorkItemSelection:
        selection = self.require(selection_id)
        normalized = list(dict.fromkeys(str(key).strip().upper() for key in selected_keys if str(key).strip()))
        if not normalized:
            raise ValueError("Select at least one requirement or defect")
        by_key = {str(item["key"]).upper(): item for item in selection.items}
        unknown = [key for key in normalized if key not in by_key]
        if unknown:
            raise ValueError(f"Unknown selection key(s): {', '.join(unknown)}")
        # Repair sessions created by older versions that classified TAPD Bug
        # records from Bug.type instead of the /bugs endpoint.
        for item in selection.items:
            kind = self._item_kind(item)
            item["type"] = "bug" if kind == "bug" else "requirement"
            item["spec"] = f"{kind}:{item['id']}"
        selection.selected_keys = normalized
        selection.selected_specs = [str(by_key[key]["spec"]) for key in normalized]
        selection.status = "confirmed"
        self.save(selection)
        return selection
