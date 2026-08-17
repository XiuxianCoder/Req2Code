from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from req2code.config import RunnerCommandConfig
from req2code.logging_setup import get_logger
from req2code.models import WorkItem
from req2code.runners.base import BaseRunner
from req2code.runners.cli_runner_mixin import CliRunnerMixin

logger = get_logger()

ANALYZE_PROMPT = """Analyze the following requirement or defect inside the current repository.

Work item ID: {work_item_id}
Title: {title}
Type: {item_type}
Description:
{description}

Verified project memory (it is a summary, so confirm critical details against code):
{project_context}

Return a concise implementation plan containing risks, files to change, implementation steps, and tests.
Do not edit files during this analysis phase."""

DEVELOP_PROMPT = """Implement the following requirement or defect in the current repository.

Work item ID: {work_item_id}
Title: {title}
Type: {item_type}
Description:
{description}

Approved implementation analysis:
{analysis}

Verified project memory (confirm critical details against current code):
{project_context}

Requirements:
- Follow the repository's existing instructions and conventions.
- Add or update tests for every behavior change.
- Do not modify unrelated files.
- Do not commit, push, merge, reset, or rewrite Git history.
- Leave all code changes in the working tree for Req2Code to review.
- Run useful local checks when safe, but Req2Code will run the configured verification suite afterwards."""

FIX_PROMPT = """Fix the implementation for the following work item because verification failed.

Work item ID: {work_item_id}
Title: {title}
Description:
{description}

Verification failures:
{test_details}

Relevant project memory:
{project_context}

Fix only the relevant code. Do not weaken tests. Do not commit, push, merge, reset, or rewrite Git history."""

REVIEW_PROMPT = """Review the following code changes for correctness, security, and quality.

Work item ID: {work_item_id}
Title: {title}
Description:
{description}

Relevant project memory:
{project_context}

Git diff:
{diff}

Output PASS or FAIL followed by concrete findings. Do not edit files."""

PROJECT_UNDERSTANDING_PROMPT = """Inspect the current Git repository and produce concise, durable project memory for future coding agents.
The repository is at baseline commit {source_sha}. Read the code and existing instructions; do not edit any files.

Return Markdown using exactly these top-level sections:
## OVERVIEW
Project purpose, business boundaries, primary stack, entry points, and external dependencies.
## ARCHITECTURE
Directory layout, major call paths, data flow, persistence, APIs, and integration boundaries.
## MODULES
Important modules and their responsibilities. Include paths and relationships, not full source code.
## DEVELOPMENT
Build/start commands, conventions, generated files, migration rules, and safe modification patterns.
## TESTING
Exact unit, integration, lint, coverage, and security commands discovered in the repository.
## RISKS
High-risk code, security boundaries, compatibility constraints, and facts future agents must verify.

Keep the result factual and below 12,000 characters. Do not include secrets or large code excerpts."""

PROJECT_REFRESH_PROMPT = """Refresh the existing project memory against the current repository at commit {source_sha}.
The previous memory was generated at {previous_sha}. These files changed since then:
{changed_files}

Existing memory:
{existing_memory}

Inspect the changed files and any directly affected code. Do not edit files. Return a complete replacement using exactly:
## OVERVIEW
## ARCHITECTURE
## MODULES
## DEVELOPMENT
## TESTING
## RISKS

Preserve still-correct facts, update affected facts, remove stale statements, and keep the result below 12,000 characters."""

PROJECT_CANDIDATE_PROMPT = """Prepare a candidate update to project memory after this run's uncommitted implementation passed verification.
Do not edit files and do not assume the change will be approved. Return a complete replacement using exactly:
## OVERVIEW
## ARCHITECTURE
## MODULES
## DEVELOPMENT
## TESTING
## RISKS

Current project memory:
{existing_memory}

Implemented work item:
{work_item}

Changed files:
{changed_files}

Git diff:
{diff}

Verification summary:
{test_details}

Reflect only facts supported by the repository and diff. Keep the result below 12,000 characters and never include secrets."""


class EngineRunner(CliRunnerMixin, BaseRunner):
    def __init__(
        self,
        cfg: RunnerCommandConfig,
        engine_name: str = "claude_code",
        artifact_base_dir: str | Path = ".req2code/artifacts",
    ) -> None:
        self.cfg = cfg
        self.engine_name = engine_name
        self.artifact_base_dir = artifact_base_dir
        self.project_context = ""
        self.session_id = ""
        self.resume_sessions = True
        self.model = (cfg.model or "").strip()

    def set_project_context(self, context: str) -> None:
        self.project_context = (context or "").strip()[:14000]

    def _context(self) -> str:
        return self.project_context or "(no stored project memory; inspect the repository directly)"

    def _build_analyze_prompt(self, work_item: WorkItem) -> str:
        return ANALYZE_PROMPT.format(
            work_item_id=work_item.id,
            title=work_item.title,
            item_type=work_item.type.value,
            description=work_item.description or "(no description)",
            project_context=self._context(),
        )

    def _build_develop_prompt(self, work_item: WorkItem, analysis: str) -> str:
        return DEVELOP_PROMPT.format(
            work_item_id=work_item.id,
            title=work_item.title,
            item_type=work_item.type.value,
            description=work_item.description or "(no description)",
            analysis=analysis or "(no separate analysis output)",
            project_context=self._context(),
        )

    def _build_fix_prompt(self, work_item: WorkItem, test_details: str) -> str:
        return FIX_PROMPT.format(
            work_item_id=work_item.id,
            title=work_item.title,
            description=work_item.description or "(no description)",
            test_details=test_details[:12000],
            project_context=self._context(),
        )

    def _build_review_prompt(self, work_item: WorkItem, diff: str) -> str:
        return REVIEW_PROMPT.format(
            work_item_id=work_item.id,
            title=work_item.title,
            description=work_item.description or "(no description)",
            diff=diff[:16000],
            project_context=self._context(),
        )

    def _extract_session_id(self, output: str) -> str:
        def visit(value: Any) -> str:
            if isinstance(value, dict):
                for key in ("thread_id", "session_id", "conversation_id"):
                    candidate = value.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()
                for child in value.values():
                    found = visit(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = visit(child)
                    if found:
                        return found
            return ""

        for line in output.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                found = visit(json.loads(line))
            except json.JSONDecodeError:
                continue
            if found:
                return found
        try:
            return visit(json.loads(output))
        except (json.JSONDecodeError, TypeError):
            return ""

    def _command_with_model(self, rendered_command: str, command_template: str) -> Sequence[str]:
        args = self._split_command(rendered_command)
        if not self.model:
            return args
        for index, argument in enumerate(args):
            if argument in {"--model", "-m"}:
                if index + 1 >= len(args):
                    raise ValueError(f"{argument} requires a model value")
                args[index + 1] = self.model
                return args
            if argument.startswith("--model="):
                args[index] = f"--model={self.model}"
                return args
        if "{model}" in command_template:
            return args

        executable = Path(args[0]).stem.lower() if args else ""
        known_executables = {
            "codex": {"codex"},
            "claude_code": {"claude"},
            "cursor": {"cursor-agent", "cursor"},
        }
        if executable not in known_executables.get(self.engine_name, set()):
            raise ValueError(
                f"Model {self.model!r} cannot be applied to custom {self.engine_name} command; "
                "add {model} to the command template or include --model explicitly"
            )

        insert_at = 2 if self.engine_name == "codex" and len(args) >= 2 and args[1] == "exec" else 1
        return [*args[:insert_at], "--model", self.model, *args[insert_at:]]

    def _resume_command(self, rendered_command: str | Sequence[str]) -> Sequence[str] | None:
        if not self.resume_sessions or not self.session_id or not self.cfg.prompt_via_stdin:
            return None
        args = self._split_command(rendered_command)
        if not args:
            return None
        if self.engine_name == "codex" and len(args) >= 2 and args[1] == "exec":
            command = [args[0], "exec"]
            if "--json" in args:
                command.append("--json")
            if "--sandbox" in args:
                index = args.index("--sandbox")
                if index + 1 < len(args):
                    command.extend(["--sandbox", args[index + 1]])
            if self.model:
                command.extend(["--model", self.model])
            command.extend(["resume", self.session_id, "-"])
            return command
        if self.engine_name == "claude_code" and "--resume" not in args:
            return [*args, "--resume", self.session_id]
        # Cursor CLI has no stable documented non-interactive resume contract.
        return None

    def _run_command(self, command: str | Sequence[str], work_item: WorkItem, target_dir: str, prompt: str, phase: str):
        env: dict[str, str] = {}
        if self.cfg.auth_env_var and self.cfg.auth_token:
            env[self.cfg.auth_env_var] = self.cfg.auth_token
        return self._run_with_retry(
            command,
            timeout_seconds=self.cfg.timeout_seconds,
            retries=self.cfg.retries,
            runner_name=self.engine_name,
            phase=phase,
            work_item_id=work_item.id,
            cwd=target_dir,
            input_text=prompt if self.cfg.prompt_via_stdin else "",
            env=env,
            artifact_base_dir=self.artifact_base_dir,
        )

    def _execute(self, work_item: WorkItem, target_dir: str, prompt: str, phase: str) -> str:
        variables = {
            "prompt": prompt,
            "target_dir": target_dir,
            "title": work_item.title,
            "description": work_item.description or "",
            "model": self.model,
        }
        rendered = self._render_command(self.cfg.command, variables)
        command = self._command_with_model(rendered, self.cfg.command)
        resume = self._resume_command(command)
        result = self._run_command(resume or command, work_item, target_dir, prompt, phase)
        if not result.ok and resume is not None:
            logger.warning("[%s] session resume failed; retrying %s in a new session", self.engine_name, phase)
            self.session_id = ""
            result = self._run_command(command, work_item, target_dir, prompt, f"{phase}_new_session")
        if not result.ok:
            logger.error("[%s] %s failed", self.engine_name, phase)
            return f"[{phase.replace('_', ' ').title()} Failed] {result.stderr or result.stdout}"
        discovered = self._extract_session_id(result.stdout)
        if discovered:
            self.session_id = discovered
        return f"[{phase.replace('_', ' ').title()} OK]\n{result.stdout.strip()}"

    def analyze(self, work_item: WorkItem, target_dir: str) -> str:
        return self._execute(work_item, target_dir, self._build_analyze_prompt(work_item), "analyze")

    def develop(self, work_item: WorkItem, target_dir: str, analysis: str = "") -> str:
        return self._execute(work_item, target_dir, self._build_develop_prompt(work_item, analysis), "develop")

    def fix(self, work_item: WorkItem, target_dir: str, test_details: str) -> str:
        return self._execute(work_item, target_dir, self._build_fix_prompt(work_item, test_details), "fix")

    def review(self, work_item: WorkItem, target_dir: str, diff: str) -> str:
        return self._execute(work_item, target_dir, self._build_review_prompt(work_item, diff), "review")

    def _extract_memory_markdown(self, output: str) -> str:
        if " Failed]" in output:
            return output
        candidates: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, str) and "## OVERVIEW" in value.upper():
                candidates.append(value)
            elif isinstance(value, dict):
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for line in output.splitlines():
            try:
                visit(json.loads(line))
            except json.JSONDecodeError:
                continue
        if candidates:
            result = candidates[-1]
        else:
            index = output.upper().find("## OVERVIEW")
            result = output[index:] if index >= 0 else output
        return result.strip()[:14000]
    def understand_project(
        self,
        work_item: WorkItem,
        target_dir: str,
        source_sha: str,
        existing_memory: str = "",
        previous_sha: str = "",
        changed_files: list[str] | None = None,
    ) -> str:
        if existing_memory and previous_sha:
            prompt = PROJECT_REFRESH_PROMPT.format(
                source_sha=source_sha,
                previous_sha=previous_sha,
                changed_files="\n".join(f"- {name}" for name in (changed_files or [])) or "- (unknown; perform a full refresh)",
                existing_memory=existing_memory[:14000],
            )
            phase = "project_memory_refresh"
        else:
            prompt = PROJECT_UNDERSTANDING_PROMPT.format(source_sha=source_sha)
            phase = "project_memory_analyze"
        return self._extract_memory_markdown(self._execute(work_item, target_dir, prompt, phase))

    def candidate_project_memory(
        self,
        work_item: WorkItem,
        target_dir: str,
        existing_memory: str,
        changed_files: list[str],
        diff: str,
        test_details: str,
    ) -> str:
        prompt = PROJECT_CANDIDATE_PROMPT.format(
            existing_memory=existing_memory[:14000] or "(no existing memory)",
            work_item=f"{work_item.id}: {work_item.title}\n{work_item.description or ''}",
            changed_files="\n".join(f"- {name}" for name in changed_files),
            diff=diff[:20000],
            test_details=test_details[:12000],
        )
        return self._extract_memory_markdown(self._execute(work_item, target_dir, prompt, "project_memory_candidate"))