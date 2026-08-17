from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from req2code.models import WorkItem

MEMORY_SCHEMA_VERSION = 1
SECTION_FILES = {
    "overview": "overview.md",
    "architecture": "architecture.md",
    "modules": "modules.md",
    "development": "development.md",
    "testing": "testing.md",
    "risks": "risks.md",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_repository_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Repository URL is required for project memory")
    # SCP-like Git syntax: git@example.com:group/repo.git
    scp_match = re.match(r"^(?:[^@]+@)?([^:]+):(.+)$", raw)
    if scp_match and "://" not in raw and not re.match(r"^[A-Za-z]:[\\/]", raw):
        host, path = scp_match.groups()
        cleaned = path.rstrip("/")
        if cleaned.lower().endswith(".git"):
            cleaned = cleaned[:-4]
        return f"ssh://{host.lower()}/{cleaned}"
    parsed = urlsplit(raw)
    if parsed.scheme and parsed.netloc:
        hostname = (parsed.hostname or "").lower()
        port = f":{parsed.port}" if parsed.port else ""
        path = parsed.path.rstrip("/")
        if path.lower().endswith(".git"):
            path = path[:-4]
        return urlunsplit((parsed.scheme.lower(), hostname + port, path, "", ""))
    path = Path(raw).expanduser().resolve()
    normalized = path.as_posix()
    return normalized.lower() if os.name == "nt" else normalized


def project_identity(repository_url: str) -> tuple[str, str]:
    canonical = canonical_repository_url(repository_url)
    stem = canonical.rstrip("/").rsplit("/", 1)[-1] or "project"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", stem).strip("-").lower() or "project"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:40]}-{digest}", canonical


@dataclass
class ProjectRecord:
    project_id: str
    canonical_url: str
    repository_url: str
    default_branch: str = ""
    source_sha: str = ""
    memory_revision: int = 0
    memory_schema_version: int = MEMORY_SCHEMA_VERSION
    generated_by: str = ""
    prompt_version: int = 1
    changed_files: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProjectRecord":
        payload = dict(value)
        payload.setdefault("memory_schema_version", MEMORY_SCHEMA_VERSION)
        payload.setdefault("changed_files", [])
        return cls(**payload)


class ProjectStore:
    def __init__(self, state_dir: str | Path) -> None:
        self.root = Path(state_dir).expanduser().resolve() / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", project_id):
            raise ValueError("Invalid project id")
        return self.root / project_id

    def _atomic_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_name, path)
        except Exception:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise

    def _atomic_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(temp_name, path)
        except Exception:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
    def save(self, record: ProjectRecord) -> Path:
        record.updated_at = utc_now()
        path = self._project_dir(record.project_id) / "project.json"
        self._atomic_json(path, asdict(record))
        return path

    def get(self, project_id: str) -> ProjectRecord | None:
        path = self._project_dir(project_id) / "project.json"
        if not path.is_file():
            return None
        return ProjectRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def require(self, project_id: str) -> ProjectRecord:
        record = self.get(project_id)
        if record is None:
            raise KeyError(f"Project not found: {project_id}")
        return record

    def get_or_create(self, repository_url: str, default_branch: str = "") -> ProjectRecord:
        project_id, canonical = project_identity(repository_url)
        record = self.get(project_id)
        if record is None:
            record = ProjectRecord(
                project_id=project_id,
                canonical_url=canonical,
                repository_url=canonical,
                default_branch=default_branch,
            )
            self.save(record)
        elif (default_branch and not record.default_branch) or record.repository_url != canonical:
            record.default_branch = record.default_branch or default_branch
            record.repository_url = canonical
            self.save(record)
        return record

    def list(self, limit: int = 50) -> list[ProjectRecord]:
        rows: list[ProjectRecord] = []
        for path in self.root.glob("*/project.json"):
            try:
                rows.append(ProjectRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        rows.sort(key=lambda item: item.updated_at, reverse=True)
        return rows[: max(1, limit)]

    def _memory_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "memory"

    def read_documents(self, project_id: str) -> dict[str, str]:
        result: dict[str, str] = {}
        root = self._memory_dir(project_id)
        for section, filename in SECTION_FILES.items():
            path = root / filename
            if path.is_file():
                result[section] = path.read_text(encoding="utf-8").strip()
        changes = root / "changes.md"
        if changes.is_file():
            result["changes"] = changes.read_text(encoding="utf-8").strip()
        return result

    def _parse_sections(self, markdown: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current = "overview"
        sections[current] = []
        for line in (markdown or "").splitlines():
            match = re.match(r"^##\s+(OVERVIEW|ARCHITECTURE|MODULES|DEVELOPMENT|TESTING|RISKS)\s*$", line.strip(), re.I)
            if match:
                current = match.group(1).lower()
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line)
        cleaned = {name: "\n".join(lines).strip() for name, lines in sections.items() if "\n".join(lines).strip()}
        if not cleaned and markdown.strip():
            cleaned["overview"] = markdown.strip()
        return cleaned

    def write_memory(
        self,
        record: ProjectRecord,
        markdown: str,
        source_sha: str,
        engine: str,
        changed_files: Iterable[str] = (),
    ) -> ProjectRecord:
        sections = self._parse_sections(markdown)
        missing = sorted(set(SECTION_FILES) - set(sections))
        if missing:
            raise ValueError(f"Project memory is incomplete; missing sections: {', '.join(missing)}")
        memory_dir = self._memory_dir(record.project_id)
        memory_dir.mkdir(parents=True, exist_ok=True)
        for section, filename in SECTION_FILES.items():
            content = sections.get(section)
            if content:
                self._atomic_text(memory_dir / filename, f"# {section.title()}\n\n{content}\n")
        record.source_sha = source_sha
        record.generated_by = engine
        record.memory_revision += 1
        record.changed_files = sorted(set(changed_files))
        self.save(record)
        return record

    def stage_candidate(self, project_id: str, run_id: str, markdown: str) -> str:
        missing = sorted(set(SECTION_FILES) - set(self._parse_sections(markdown)))
        if missing:
            raise ValueError(f"Project-memory candidate is incomplete; missing sections: {', '.join(missing)}")
        candidate = self._project_dir(project_id) / "candidates" / f"{run_id}.md"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_text(candidate, markdown.strip() + "\n")
        return str(candidate)

    def discard_candidate(self, project_id: str, run_id: str) -> None:
        path = self._project_dir(project_id) / "candidates" / f"{run_id}.md"
        if path.is_file():
            path.unlink()

    def promote_candidate(
        self,
        project_id: str,
        run_id: str,
        source_sha: str,
        engine: str,
        work_items: list[dict[str, Any]],
        changed_files: list[str],
    ) -> ProjectRecord | None:
        candidate = self._project_dir(project_id) / "candidates" / f"{run_id}.md"
        if not candidate.is_file():
            return None
        record = self.require(project_id)
        self.write_memory(record, candidate.read_text(encoding="utf-8"), source_sha, engine, changed_files)
        changes_path = self._memory_dir(project_id) / "changes.md"
        ids = ", ".join(str(item.get("id")) for item in work_items)
        entry = "\n".join(
            [
                f"## {utc_now()} / {source_sha[:12]}",
                f"- Run: `{run_id}`",
                f"- Work items: {ids}",
                f"- Changed files: {', '.join(changed_files) or '(none)'}",
                "",
            ]
        )
        previous = changes_path.read_text(encoding="utf-8") if changes_path.is_file() else "# Approved changes\n\n"
        self._atomic_text(changes_path, previous.rstrip() + "\n\n" + entry)
        candidate.unlink()
        return record

    def invalidate(self, project_id: str) -> ProjectRecord:
        record = self.require(project_id)
        record.source_sha = ""
        self.save(record)
        return record

    def forget(self, project_id: str) -> None:
        target = self._project_dir(project_id).resolve()
        if target.parent != self.root or not target.is_dir():
            raise ValueError(f"Project directory does not exist: {project_id}")
        shutil.rmtree(target)

    def export_instructions(self, project_id: str, repository_path: str | Path, target: str) -> Path:
        normalized = target.strip().lower()
        context = self.context_for(project_id, [], max_chars=12000)
        if not context:
            raise ValueError("Project has no memory to export")
        root = Path(repository_path).expanduser().resolve()
        if not (root / ".git").exists():
            raise ValueError(f"Not a Git repository: {root}")
        header = (
            "This file was generated from Req2Code project memory. Verify critical facts against current code.\n"
            "Do not commit, push, merge, reset, or rewrite Git history during Req2Code development runs.\n\n"
        )
        if normalized == "codex":
            output = root / "AGENTS.md"
            body = "# Req2Code project guidance\n\n" + header + context + "\n"
        elif normalized == "claude":
            output = root / "CLAUDE.md"
            body = "# Req2Code project guidance\n\n" + header + context + "\n"
        elif normalized == "cursor":
            output = root / ".cursor" / "rules" / "req2code-project.mdc"
            body = "---\ndescription: Req2Code-generated project architecture and workflow guidance\nalwaysApply: true\n---\n\n" + header + context + "\n"
        else:
            raise ValueError("target must be codex, claude, or cursor")
        if output.exists():
            raise FileExistsError(f"Refusing to overwrite existing instruction file: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(body, encoding="utf-8")
        return output
    def context_for(self, project_id: str, work_items: Iterable[WorkItem], max_chars: int = 14000) -> str:
        documents = self.read_documents(project_id)
        if not documents:
            return ""
        query = " ".join(
            f"{item.title} {item.description or ''}" for item in work_items
        ).lower()
        terms = {term for term in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]{2,}", query) if len(term) > 1}
        ranked: list[tuple[int, str, str]] = []
        priorities = {"overview": 100, "testing": 80, "architecture": 60, "modules": 50, "development": 40, "risks": 30, "changes": 10}
        for section, content in documents.items():
            lowered = content.lower()
            score = priorities.get(section, 0) + sum(5 for term in terms if term in lowered)
            ranked.append((score, section, content))
        ranked.sort(reverse=True)
        blocks: list[str] = []
        size = 0
        for _, section, content in ranked:
            block = f"## {section.title()}\n{content}"
            if blocks and size + len(block) > max_chars:
                continue
            remaining = max_chars - size
            if remaining <= 0:
                break
            blocks.append(block[:remaining])
            size += len(block)
        return "\n\n".join(blocks)