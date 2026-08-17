from pathlib import Path

import pytest

from req2code.models import TaskType, WorkItem
from req2code.project_memory import ProjectStore, canonical_repository_url, project_identity


MEMORY = """## OVERVIEW
Payment service overview.
## ARCHITECTURE
API calls the payment module.
## MODULES
payments.py owns payment processing.
## DEVELOPMENT
Use Python and keep changes focused.
## TESTING
Run python -m pytest -q.
## RISKS
Never log credentials.
"""


def test_project_identity_is_stable_and_removes_credentials():
    first = project_identity("https://user:secret@Example.COM/team/service.git?token=secret")
    second = project_identity("https://example.com/team/service")
    assert first == second
    assert "secret" not in canonical_repository_url("https://user:secret@example.com/team/service.git")
    assert project_identity("git@example.com:team/service.git") == project_identity("ssh://example.com/team/service")


def test_memory_is_structured_versioned_and_retrieved_by_work_item(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.get_or_create("https://example.com/team/payment.git", "main")
    store.write_memory(project, MEMORY, "a" * 40, "codex", ["payments.py"])

    loaded = store.require(project.project_id)
    assert loaded.memory_revision == 1
    assert loaded.source_sha == "a" * 40
    assert set(store.read_documents(project.project_id)) >= {
        "overview", "architecture", "modules", "development", "testing", "risks"
    }
    item = WorkItem(
        id="PAY-1",
        title="Payment retry",
        description="Update payment processing",
        type=TaskType.BUG,
    )
    context = store.context_for(project.project_id, [item], max_chars=4000)
    assert "payments.py" in context
    assert len(context) <= 4000


def test_incomplete_memory_cannot_replace_canonical_context(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.get_or_create("https://example.com/team/service.git")
    with pytest.raises(ValueError, match="missing sections"):
        store.write_memory(project, "## OVERVIEW\nOnly one section", "a" * 40, "codex")
    assert store.require(project.project_id).memory_revision == 0


def test_candidate_is_promoted_only_when_requested(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.get_or_create("https://example.com/team/service.git")
    store.write_memory(project, MEMORY, "a" * 40, "codex")
    candidate = store.stage_candidate(project.project_id, "run1", MEMORY.replace("overview", "updated overview"))
    assert Path(candidate).is_file()
    assert store.require(project.project_id).memory_revision == 1

    promoted = store.promote_candidate(
        project.project_id,
        "run1",
        "b" * 40,
        "codex",
        [{"id": "ITEM-1"}],
        ["payments.py"],
    )
    assert promoted is not None
    assert promoted.memory_revision == 2
    assert promoted.source_sha == "b" * 40
    assert not Path(candidate).exists()
    assert "ITEM-1" in store.read_documents(project.project_id)["changes"]


def test_export_refuses_to_overwrite_native_instruction_file(tmp_path):
    store = ProjectStore(tmp_path / "state")
    project = store.get_or_create("https://example.com/team/service.git")
    store.write_memory(project, MEMORY, "a" * 40, "codex")
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)

    output = store.export_instructions(project.project_id, repository, "codex")
    assert output.name == "AGENTS.md"
    assert "Req2Code project guidance" in output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        store.export_instructions(project.project_id, repository, "codex")