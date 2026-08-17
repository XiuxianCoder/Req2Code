from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from req2code.logging_setup import get_logger

if TYPE_CHECKING:
    from req2code.models import TestResult, WorkItem
    from req2code.runners.engine_runner import EngineRunner

logger = get_logger()


class ReviewService:
    def _run_command(self, command: str, cwd: str | Path | None = None) -> tuple[bool, str]:
        if not command.strip():
            return True, ""
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        return result.returncode == 0, output.strip()

    def _ai_code_review(
        self,
        runner: "EngineRunner",
        work_item: "WorkItem",
        target_dir: str,
    ) -> tuple[bool, str]:
        status = subprocess.run(
            ["git", "status", "--short"], cwd=target_dir, capture_output=True, text=True, check=False
        ).stdout
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"], cwd=target_dir, capture_output=True, text=True, check=False
        ).stdout
        review_output = runner.review(work_item, target_dir, f"Git status:\n{status}\n\n{diff}")
        passed = "[Review Failed]" not in review_output and "fail" not in review_output[:80].lower()
        return passed, review_output

    def ai_review(
        self,
        test_result: "TestResult",
        min_coverage: float = 80.0,
        lint_command: str = "",
        security_command: str = "",
        ai_review_enabled: bool = False,
        runner: "EngineRunner | None" = None,
        work_item: "WorkItem | None" = None,
        target_dir: str = ".",
    ) -> tuple[bool, str]:
        reasons: list[str] = []
        if not test_result.unit_passed:
            reasons.append("Unit tests failed")
        if not test_result.script_passed:
            reasons.append("Script tests failed")
        if test_result.coverage < min_coverage:
            reasons.append(f"Coverage {test_result.coverage:.1f}% < {min_coverage}% threshold")

        lint_ok, lint_output = self._run_command(lint_command, cwd=target_dir)
        if not lint_ok:
            reasons.append(f"Lint checks failed:\n{lint_output[:1000]}")
        security_ok, security_output = self._run_command(security_command, cwd=target_dir)
        if not security_ok:
            reasons.append(f"Security scan failed:\n{security_output[:1000]}")

        if ai_review_enabled and runner and work_item:
            ai_ok, ai_output = self._ai_code_review(runner, work_item, target_dir)
            if not ai_ok:
                reasons.append(f"AI code review flagged issues:\n{ai_output[:1000]}")

        if reasons:
            return False, "Verification rejected:\n- " + "\n- ".join(reasons)
        return True, "Automated verification approved; human approval is still required before commit and push."
