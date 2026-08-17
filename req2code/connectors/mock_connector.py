from __future__ import annotations

from typing import Iterable

from req2code.connectors.base import SourceConnector
from req2code.models import TaskType, WorkItem


DEMO_ITEMS = (
    WorkItem(
        id="DEMO-STORY-1",
        title="Add multiplication to the demo calculator",
        description=(
            "Add a multiply(a, b) function to calculator.py and add unit tests for "
            "positive, negative, and zero operands. Keep existing behavior unchanged."
        ),
        type=TaskType.REQUIREMENT,
        source="mock",
    ),
    WorkItem(
        id="DEMO-BUG-1",
        title="Return a clear error when dividing by zero",
        description=(
            "Change calculator.divide(a, b) so a zero divisor raises "
            "ValueError('divisor must not be zero'), and add a regression test."
        ),
        type=TaskType.BUG,
        source="mock",
    ),
)


class MockConnector(SourceConnector):
    def fetch_latest(self, limit: int = 10) -> Iterable[WorkItem]:
        return list(DEMO_ITEMS[: max(0, limit)])

    def get_by_id(self, req_id: str) -> WorkItem:
        for item in DEMO_ITEMS:
            if item.id == req_id:
                return item
        return WorkItem(
            id=req_id,
            title=f"Mock item {req_id}",
            description="Implement this local mock work item and add appropriate tests.",
            type=TaskType.REQUIREMENT,
            source="mock",
        )