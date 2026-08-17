from req2code.approval import ApprovalStore
from req2code.config import AgentConfig
from req2code.models import TaskType, WorkItem
from req2code.workflow import WorkflowService


def test_continue_after_manual_review_pending(tmp_path):
    cfg = AgentConfig()
    cfg.review.mode = "manual"
    cfg.review.approvals_file = str(tmp_path / "approvals.yaml")

    service = WorkflowService(cfg)
    work_item = WorkItem(id="REQ-1", title="t", description="d", type=TaskType.REQUIREMENT)
    service.approvals.submit(work_item.id, branch="feature/req-1")

    result = service.continue_after_manual_review(work_item)
    assert result.status.value == "review_required"


def test_approval_store_decide_approved(tmp_path):
    path = tmp_path / "approvals.yaml"
    store = ApprovalStore(str(path))
    store.submit("REQ-2", branch="feature/req-2")
    store.decide("REQ-2", approved=True, comment="ok")
    row = store.get("REQ-2")
    assert row is not None
    assert row["status"] == "approved"
