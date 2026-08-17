from pathlib import Path
from types import SimpleNamespace

import pytest

from req2code.config import AgentConfig
from req2code.models import TaskType, WorkItem
from req2code.repository import PreparedRepository, RepositoryError, RepositorySpec
from req2code.run_state import RunStatus
from req2code.workflow import WorkflowService


def config_for(tmp_path) -> AgentConfig:
    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path / "state")
    cfg.message.webhook = ""
    return cfg


def item() -> WorkItem:
    return WorkItem(id="1001", title="Fix card", description="Acceptance criteria", type=TaskType.BUG)


def test_failed_preparation_is_visible_in_run_store(tmp_path, monkeypatch):
    service = WorkflowService(config_for(tmp_path))

    def fail(*args, **kwargs):
        raise RepositoryError("git fetch timed out after 120s")

    monkeypatch.setattr(service.workspace, "prepare", fail)
    with pytest.raises(RepositoryError, match="timed out"):
        service.begin_agent_run([item()], RepositorySpec(local_path=str(tmp_path)))

    records = service.runs.list()
    assert len(records) == 1
    assert records[0].status == RunStatus.FAILED.value
    assert records[0].preparation_stage == "failed"
    assert "timed out" in records[0].error


def test_same_active_request_reuses_task_session(tmp_path, monkeypatch):
    service = WorkflowService(config_for(tmp_path))
    calls = 0

    def prepared(spec, run_id):
        nonlocal calls
        calls += 1
        return PreparedRepository(
            path=Path(tmp_path),
            repo_url="https://example.test/repo.git",
            push_url="https://example.test/repo.git",
            remote_name="origin",
            base_branch="main",
            work_branch="main",
            push_branch="main",
            baseline_sha="a" * 40,
            remote_branch_sha="a" * 40,
            branch_mode="current",
        )

    monkeypatch.setattr(service.workspace, "prepare", prepared)
    spec = RepositorySpec(local_path=str(tmp_path), sync_before_start=True)
    first = service.begin_agent_run([item()], spec)
    second = service.begin_agent_run([item()], spec)

    assert calls == 1
    assert first.run_id == second.run_id
    assert first.status == RunStatus.DEVELOPING.value
    assert first.sync_before_start is True


def test_feishu_schema_notes_are_included_in_the_agent_task_brief(tmp_path):
    service = WorkflowService(config_for(tmp_path))
    work_item = WorkItem(
        id="rec-1",
        title="保存失败",
        description="实际结果：点击保存没有响应\n预期结果：保存成功",
        type=TaskType.BUG,
        source="feishu",
        metadata={
            "normalized_fields": {"status": "未解决"},
            "feishu_schema": {"notes": ["问题分类决定需求或缺陷类型", "已验证和已关闭属于终态"]},
        },
    )
    record = SimpleNamespace(
        run_id="run-feishu",
        repo_path=str(tmp_path),
        baseline_sha="a" * 40,
        sync_before_start=False,
        work_branch="main",
        branch_mode="current",
        work_items=[service._item_dict(work_item)],
    )

    brief = service._agent_task_brief(record)

    assert "字段分析注意事项：问题分类决定需求或缺陷类型" in brief
    assert "字段分析注意事项：已验证和已关闭属于终态" in brief
    assert "实际结果：点击保存没有响应" in brief
