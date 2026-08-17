from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from req2code.models import WorkItem


class SourceConnector(ABC):
    @abstractmethod
    def fetch_latest(self, limit: int = 10) -> Iterable[WorkItem]:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, req_id: str) -> WorkItem:
        raise NotImplementedError
