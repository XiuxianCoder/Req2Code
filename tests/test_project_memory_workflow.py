from req2code.config import AgentConfig
from req2code.models import TaskType, WorkItem
from req2code.run_state import RunRecord
from req2code.workflow import WorkflowService


MEMORY = """## OVERVIEW
Service summary.
## ARCHITECTURE
Layered service.
## MODULES
Core module.
## DEVELOPMENT
Follow repository conventions.
## TESTING
Run tests.
## RISKS
Verify current code.
"""


class CountingMemoryRunner:
    session_id = "session-one"

    def __init__(self):
        self.understand_calls = 0
        self.context = ""

    def understand_project(self, *args, **kwargs):
        self.understand_calls += 1
        return MEMORY

    def set_project_context(self, context):
        self.context = context


def test_same_git_sha_reuses_project_memory_without_another_agent_scan(tmp_path):
    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path / "state")
    service = WorkflowService(cfg)
    project = service.projects.get_or_create("https://example.com/team/service.git", "main")
    item = WorkItem(id="REQ-1", title="Core change", description="Update core", type=TaskType.REQUIREMENT)
    record = RunRecord(
        run_id="memory-run",
        work_items=[],
        engine="codex",
        repo_path=str(tmp_path / "repo"),
        repo_url="https://example.com/team/service.git",
        push_url="https://example.com/team/service.git",
        remote_name="origin",
        base_branch="main",
        work_branch="feature/one",
        push_branch="feature/one",
        baseline_sha="a" * 40,
        remote_branch_sha=None,
        project_id=project.project_id,
    )
    runner = CountingMemoryRunner()

    service._prepare_project_memory(record, [item], item, runner)
    service._prepare_project_memory(record, [item], item, runner)

    assert runner.understand_calls == 1
    assert record.project_memory_revision == 1
    assert "Service summary" in runner.context