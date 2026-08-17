from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


class TapdErrorStats:
    def __init__(self, path: str = ".req2code/tapd_error_stats.yaml") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"counts": {}}
        with self.path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "counts" not in data or not isinstance(data["counts"], dict):
            data["counts"] = {}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def inc(self, category: str) -> None:
        data = self._load()
        counts = data["counts"]
        counts[category] = int(counts.get(category, 0)) + 1
        self._save(data)

    def summary(self) -> dict[str, int]:
        data = self._load()
        return {k: int(v) for k, v in data.get("counts", {}).items()}

    def write_reports(self, report_dir: str = "reports") -> tuple[Path, Path]:
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)
        summary = self.summary()

        md_path = report_path / "tapd_error_stats.md"
        md_lines = [
            "# TAPD Error Stats",
            f"- Time: {datetime.utcnow().isoformat()}",
            "",
            "| Category | Count |",
            "|---|---:|",
        ]
        for k, v in sorted(summary.items()):
            md_lines.append(f"| {k} | {v} |")
        if not summary:
            md_lines.append("| (none) | 0 |")
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        json_path = report_path / "tapd_error_stats.json"
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return md_path, json_path
