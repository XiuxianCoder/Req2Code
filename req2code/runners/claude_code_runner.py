from __future__ import annotations

from pathlib import Path

from req2code.config import RunnerCommandConfig
from req2code.runners.engine_runner import EngineRunner


class ClaudeCodeRunner(EngineRunner):
    def __init__(self, cfg: RunnerCommandConfig, artifact_base_dir: str | Path = ".req2code/artifacts") -> None:
        super().__init__(cfg, engine_name="claude_code", artifact_base_dir=artifact_base_dir)
