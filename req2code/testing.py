from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from req2code.config import AgentConfig
from req2code.logging_setup import get_logger
from req2code.models import TestResult

logger = get_logger()
COVERAGE_PCT_RE = re.compile(r"TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%")


def _split(command: str) -> list[str]:
    return shlex.split(command, posix=True)


def _run_command(command: str, cwd: str | Path | None = None) -> tuple[bool, str]:
    result = subprocess.run(
        _split(command),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    return result.returncode == 0, output.strip()


def run_unit_tests(command: str = "python -m pytest -q", cwd: str | Path | None = None) -> tuple[bool, str]:
    return _run_command(command, cwd=cwd)


def run_script_tests(command: str = "", cwd: str | Path | None = None) -> tuple[bool, str]:
    if not command:
        return True, "Script tests skipped (no script command configured)."
    return _run_command(command, cwd=cwd)


def collect_coverage(command: str = "", cwd: str | Path | None = None) -> tuple[float, str]:
    cmd = command or "python -m coverage run -m pytest -q && python -m coverage report"
    if not cmd.strip():
        return 0.0, "Coverage skipped (no command configured)."
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    match = COVERAGE_PCT_RE.search(output)
    if match:
        return float(match.group(1)), output
    fallback = re.findall(r"(\d+(?:\.\d+)?)%", output)
    return (float(fallback[-1]) if fallback else 0.0), output


def run_all_tests(config: AgentConfig | None = None, cwd: str | Path | None = None) -> TestResult:
    unit_command = config.testing.unit_command if config else "python -m pytest -q"
    script_command = config.testing.script_command if config else ""
    coverage_command = config.testing.coverage_command if config else ""

    logger.info("Running unit tests in %s: %s", cwd or Path.cwd(), unit_command)
    unit_ok, unit_log = run_unit_tests(unit_command, cwd=cwd)
    script_ok, script_log = run_script_tests(script_command, cwd=cwd)
    coverage, coverage_log = collect_coverage(coverage_command, cwd=cwd)
    details = f"[Unit]\n{unit_log}\n\n[Script]\n{script_log}\n\n[Coverage]\n{coverage_log}"
    return TestResult(unit_passed=unit_ok, script_passed=script_ok, coverage=coverage, details=details)
