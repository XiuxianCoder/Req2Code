from __future__ import annotations

from datetime import datetime
from pathlib import Path


class ArtifactManager:
    def __init__(self, base_dir: str = ".req2code/artifacts") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _safe(self, text: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)

    def create_run_dir(self, runner: str, phase: str, work_item_id: str) -> Path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        name = f"{ts}_{self._safe(runner)}_{self._safe(phase)}_{self._safe(work_item_id)}"
        p = self.base_dir / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def write_text(self, run_dir: Path, filename: str, content: str) -> Path:
        p = run_dir / filename
        p.write_text(content or "", encoding="utf-8")
        return p
