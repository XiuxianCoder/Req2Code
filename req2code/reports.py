from __future__ import annotations

from datetime import datetime
from pathlib import Path

from req2code.models import TestResult, WorkItem


class ReportManager:
    def __init__(self, report_dir: Path | None = None) -> None:
        self.report_dir = report_dir or Path("reports")
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def write_dev_report(self, work_item: WorkItem, analyze_text: str, develop_text: str) -> Path:
        path = self.report_dir / f"dev_{work_item.id}.md"
        path.write_text(
            "\n".join(
                [
                    f"# Development Report - {work_item.id}",
                    f"- Title: {work_item.title}",
                    f"- Time: {datetime.utcnow().isoformat()}",
                    "",
                    "## Analysis",
                    analyze_text,
                    "",
                    "## Development",
                    develop_text,
                ]
            ),
            encoding="utf-8",
        )
        return path

    def write_test_report(self, work_item: WorkItem, test_result: TestResult) -> Path:
        path = self.report_dir / f"test_{work_item.id}.md"
        path.write_text(
            "\n".join(
                [
                    f"# Test Report - {work_item.id}",
                    f"- Time: {datetime.utcnow().isoformat()}",
                    f"- Unit Passed: {test_result.unit_passed}",
                    f"- Script Passed: {test_result.script_passed}",
                    f"- Coverage: {test_result.coverage}",
                    "",
                    "## Details",
                    test_result.details,
                ]
            ),
            encoding="utf-8",
        )
        return path
