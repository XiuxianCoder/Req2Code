from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from req2code.models import WorkItem


@dataclass
class RunnerResult:
    ok: bool
    stdout: str
    stderr: str
    command: str


class BaseRunner(ABC):
    @abstractmethod
    def develop(self, work_item: WorkItem, target_dir: str, analysis: str = "") -> str:
        raise NotImplementedError

    @abstractmethod
    def analyze(self, work_item: WorkItem, target_dir: str) -> str:
        raise NotImplementedError
