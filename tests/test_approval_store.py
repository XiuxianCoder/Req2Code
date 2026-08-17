from req2code.approval import ApprovalStore


def test_approval_store_submit_and_decide(tmp_path):
    path = tmp_path / "approvals.yaml"
    store = ApprovalStore(str(path))

    store.submit("REQ-1", branch="feature/req-1")
    row = store.get("REQ-1")
    assert row is not None
    assert row["status"] == "pending"

    store.decide("REQ-1", approved=True, comment="ok")
    row2 = store.get("REQ-1")
    assert row2 is not None
    assert row2["status"] == "approved"
