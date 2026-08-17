from __future__ import annotations

from req2code.config import ConfigManager
from req2code.source_factory import get_source_connector
from req2code.workflow import WorkflowService


class ChatSession:
    def __init__(self) -> None:
        self.cfg_mgr = ConfigManager()

    def handle(self, text: str) -> str:
        cfg = self.cfg_mgr.load()
        lowered = text.strip().lower()

        if lowered.startswith("run "):
            req_id = text.split(maxsplit=1)[1].strip()
            source = get_source_connector(cfg)
            work_item = source.get_by_id(req_id)
            result = WorkflowService(cfg).run(work_item, auto_review=True)
            return f"Done: {result.status.value}, reports=({result.dev_report_path}, {result.test_report_path})"

        if lowered.startswith("use source "):
            source = text.split(maxsplit=2)[2].strip()
            self.cfg_mgr.set("source", source)
            return f"Switched source to {source}"

        if lowered.startswith("use engine "):
            engine = text.split(maxsplit=2)[2].strip()
            self.cfg_mgr.set("engines.active", engine)
            return f"Switched engine to {engine}"

        if lowered.startswith("use model "):
            model = text.split(maxsplit=2)[2].strip()
            if model.lower() in {"default", "auto", "cli-default"}:
                model = ""
            if any(character.isspace() for character in model):
                return "Model ID cannot contain whitespace"
            engine = cfg.engines.active.lower().replace("-", "_")
            if engine == "claude":
                engine = "claude_code"
            if engine not in {"cursor", "claude_code", "codex"}:
                return f"Unsupported active engine: {engine}"
            self.cfg_mgr.set(f"engines.{engine}.model", model)
            return f"Switched {engine} model to {model or 'CLI default'}"

        if lowered.startswith("approve "):
            req_id = text.split(maxsplit=1)[1].strip()
            self.cfg_mgr.set("review.mode", "manual")
            from req2code.source_factory import get_source_connector

            cfg = self.cfg_mgr.load()
            service = WorkflowService(cfg)
            service.approvals.decide(req_id, approved=True, comment="Approved from chat")
            work_item = get_source_connector(cfg).get_by_id(req_id)
            result = service.continue_after_manual_review(work_item)
            return f"Manual review continued: {result.status.value}"

        if lowered in {"help", "?"}:
            return "Commands: run <REQ_ID>, use source <tapd|mock>, use engine <cursor|claude_code|codex>, use model <MODEL|default>, approve <REQ_ID>, help, exit"

        return "Unknown command. Input 'help' for usage."
