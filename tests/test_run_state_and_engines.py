from pathlib import Path

from req2code.config import AgentConfig
from req2code.run_state import RunRecord, RunStatus, RunStore
from req2code.runners.claude_code_runner import ClaudeCodeRunner
from req2code.runners.codex_runner import CodexRunner
from req2code.runners.cursor_runner import CursorRunner
from req2code.workflow import WorkflowService


def make_record() -> RunRecord:
    return RunRecord(
        run_id="abc123",
        work_items=[{"id": "TAPD-1", "type": "requirement", "title": "t", "description": "d"}],
        engine="codex",
        repo_path="C:/repo",
        repo_url="https://example/repo.git",
        push_url="https://example/repo.git",
        remote_name="origin",
        base_branch="main",
        work_branch="feature/one",
        push_branch="feature/one",
        baseline_sha="a" * 40,
        remote_branch_sha=None,
        status=RunStatus.WAITING_APPROVAL.value,
    )


def test_run_store_round_trip(tmp_path):
    store = RunStore(tmp_path)
    record = make_record()
    store.save(record)
    loaded = store.require(record.run_id)
    assert loaded.work_items[0]["id"] == "TAPD-1"
    assert loaded.status == "waiting_approval"
    assert store.list()[0].run_id == record.run_id


def test_all_three_engines_are_selectable(tmp_path):
    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path)
    service = WorkflowService(cfg)
    assert isinstance(service._runner("claude_code")[0], ClaudeCodeRunner)
    assert isinstance(service._runner("codex")[0], CodexRunner)
    assert isinstance(service._runner("cursor")[0], CursorRunner)
