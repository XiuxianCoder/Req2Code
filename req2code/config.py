from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

SENSITIVE_KEY_PARTS = ("token", "secret", "password", "webhook", "key", "auth", "app_id", "client_id")

CURRENT_SCHEMA_VERSION = 8

CONFIG_HEADER_COMMENTS = """# Req2Code configuration (schema_version=8)
#
# source_profiles.* 可在对话内 UI 中选择的命名需求源配置
# tapd.*        需求源配置 (TAPD)
# feishu.*      需求源配置 (飞书文档/多维表格)
# message.*     通知配置 (企业微信/钉钉/webhook)
# review.*      审批配置
# engines.*     兼容模式的嵌套执行引擎配置 (默认 Skill/MCP 流程不使用)
# testing.*     测试与覆盖率配置
# project_memory.* 项目理解、增量记忆、镜像缓存与会话复用
# system.*      系统配置 (日志)
#
# token/secret/webhook 等敏感值会在 config list 中自动脱敏。
# 不要把真实密钥提交到代码仓库。
"""


class TapdFieldMappingConfig(BaseModel):
    list_path: str = Field(default="data")
    detail_path: str = Field(default="data")
    id_field: str = Field(default="Story.id")
    title_field: str = Field(default="Story.name")
    description_field: str = Field(default="Story.description")
    type_field: str = Field(default="Story.type")


class TapdSourceConfig(BaseModel):
    enabled: bool = Field(default=True)
    base_url: str = Field(default="https://api.tapd.cn")
    auth_mode: str = Field(default="oauth2")
    app_id: str = Field(default="REPLACE_ME_TAPD_APP_ID")
    app_secret: str = Field(default="REPLACE_ME_TAPD_APP_SECRET")
    workspace_id: str = Field(default="REPLACE_ME_WORKSPACE_ID")
    token_endpoint: str = Field(default="/tokens/request_token")
    latest_endpoint: str = Field(default="/stories")
    detail_endpoint: str = Field(default="/stories")
    field_mapping: TapdFieldMappingConfig = Field(default_factory=TapdFieldMappingConfig)
    bug_latest_endpoint: str = Field(default="/bugs")
    bug_detail_endpoint: str = Field(default="/bugs")
    bug_field_mapping: TapdFieldMappingConfig = Field(
        default_factory=lambda: TapdFieldMappingConfig(
            id_field="Bug.id",
            title_field="Bug.title",
            description_field="Bug.description",
            type_field="Bug.type",
        )
    )
    default_item_type: str = Field(default="story")
    auth_scheme: str = Field(default="Bearer")
    auth_header_name: str = Field(default="Authorization")
    timeout_seconds: int = Field(default=20)
    retries: int = Field(default=2)
    retry_backoff_seconds: float = Field(default=1.0)
    rate_limit_qps: float = Field(default=5.0)
    error_stats_file: str = Field(default=".req2code/tapd_error_stats.yaml")


class MockSourceConfig(BaseModel):
    enabled: bool = Field(default=True)


class FeishuFieldMappingConfig(BaseModel):
    """Optional field-name overrides for tables with project-specific columns."""

    id_field: str = Field(default="")
    title_field: str = Field(default="")
    description_field: str = Field(default="")
    type_field: str = Field(default="")
    status_field: str = Field(default="")
    priority_field: str = Field(default="")
    severity_field: str = Field(default="")
    owner_field: str = Field(default="")
    reporter_field: str = Field(default="")
    acceptance_field: str = Field(default="")
    updated_field: str = Field(default="")


class FeishuSourceConfig(BaseModel):
    enabled: bool = Field(default=True)
    base_url: str = Field(default="https://open.feishu.cn")
    auth_mode: str = Field(default="tenant")
    app_id: str = Field(default="REPLACE_ME_FEISHU_APP_ID")
    app_secret: str = Field(default="REPLACE_ME_FEISHU_APP_SECRET")
    document_url: str = Field(default="")
    resource_type: str = Field(default="auto")
    parse_mode: str = Field(default="auto")
    table_id: str = Field(default="")
    view_id: str = Field(default="")
    sheet_id: str = Field(default="")
    field_mapping: FeishuFieldMappingConfig = Field(default_factory=FeishuFieldMappingConfig)
    timeout_seconds: int = Field(default=20, ge=5, le=120)
    retries: int = Field(default=2, ge=1, le=5)
    retry_backoff_seconds: float = Field(default=1.0, ge=0, le=10)


class SourceProfileConfig(BaseModel):
    """A named work-item source selected by the human before a development run."""

    id: str
    name: str
    source: str = Field(default="tapd")
    tapd: TapdSourceConfig | None = Field(default=None)
    feishu: FeishuSourceConfig | None = Field(default=None)


class GitConfig(BaseModel):
    repo_url: str = Field(default="")
    base_branch: str = Field(default="test")
    target_branch: str = Field(default="test")
    remote_name: str = Field(default="origin")
    branch_prefix: str = Field(default="req2code")
    commit_author: str = Field(default="req2code-bot")
    commit_email: str = Field(default="req2code-bot@localhost")
    auto_init_if_missing: bool = Field(default=False)
    command_timeout_seconds: int = Field(default=120, ge=5, le=1800)


class MessageTemplateConfig(BaseModel):
    normal: str = Field(default="[{level}] {content}")
    warning: str = Field(default="[{level}] {content}")
    critical: str = Field(default="[{level}] {content}\nartifact={artifact}")


class MessageConfig(BaseModel):
    provider: str = Field(default="wechat_work")
    webhook: str = Field(default="REPLACE_ME_MESSAGE_WEBHOOK")
    reviewer: str = Field(default="qa_reviewer")
    timeout_seconds: int = Field(default=10)
    default_level: str = Field(default="normal")
    templates: MessageTemplateConfig = Field(default_factory=MessageTemplateConfig)


class RunnerCommandConfig(BaseModel):
    command: str = Field(default="")
    model: str = Field(default="")
    auth_token: str = Field(default="")
    auth_env_var: str = Field(default="")
    prompt_via_stdin: bool = Field(default=True)
    working_dir: str = Field(default=".")
    timeout_seconds: int = Field(default=1800)
    retries: int = Field(default=1)


class EngineConfig(BaseModel):
    active: str = Field(default="claude_code")
    cursor_enabled: bool = Field(default=True)
    claude_code_enabled: bool = Field(default=True)
    codex_enabled: bool = Field(default=True)
    cursor: RunnerCommandConfig = Field(
        default_factory=lambda: RunnerCommandConfig(
            command="cursor-agent -p --force --output-format stream-json {prompt}",
            prompt_via_stdin=False,
        )
    )
    claude_code: RunnerCommandConfig = Field(
        default_factory=lambda: RunnerCommandConfig(
            command="claude -p --output-format stream-json",
            auth_env_var="ANTHROPIC_API_KEY",
            prompt_via_stdin=True,
        )
    )
    codex: RunnerCommandConfig = Field(
        default_factory=lambda: RunnerCommandConfig(
            command="codex exec --json --sandbox workspace-write -",
            auth_env_var="CODEX_API_KEY",
            prompt_via_stdin=True,
        )
    )


class TestingConfig(BaseModel):
    script_command: str = Field(default="")
    unit_command: str = Field(default="python -m pytest -q")
    min_coverage: float = Field(default=80.0)
    max_fix_attempts: int = Field(default=2)
    coverage_command: str = Field(default="python -m coverage run -m pytest -q && python -m coverage report")


class ReviewConfig(BaseModel):
    mode: str = Field(default="auto")
    approvals_file: str = Field(default="approvals.yaml")
    callback_secret: str = Field(default="REPLACE_ME_APPROVAL_CALLBACK_SECRET")
    signature_header: str = Field(default="X-Req2Code-Signature")
    timestamp_header: str = Field(default="X-Req2Code-Timestamp")
    nonce_header: str = Field(default="X-Req2Code-Nonce")
    timestamp_tolerance_seconds: int = Field(default=300)
    replay_store_file: str = Field(default="replay_nonces.yaml")
    ip_allowlist: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"])
    lint_command: str = Field(default="")
    security_scan_command: str = Field(default="")
    ai_review_enabled: bool = Field(default=False)
    require_human_approval: bool = Field(default=True)
    approval_base_url: str = Field(default="http://127.0.0.1:8088")


class ProjectMemoryConfig(BaseModel):
    enabled: bool = Field(default=True)
    max_context_chars: int = Field(default=14000, ge=2000, le=50000)
    generate_candidate: bool = Field(default=True)
    promote_after_approval: bool = Field(default=True)
    use_mirror_cache: bool = Field(default=True)
    resume_engine_sessions: bool = Field(default=True)


class SystemConfig(BaseModel):
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="")
    state_dir: str = Field(default="~/.req2code")


class AgentConfig(BaseModel):
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION)
    source: str = Field(default="tapd")
    source_profiles: list[SourceProfileConfig] = Field(default_factory=list)
    tapd: TapdSourceConfig = Field(default_factory=TapdSourceConfig)
    feishu: FeishuSourceConfig = Field(default_factory=FeishuSourceConfig)
    mock: MockSourceConfig = Field(default_factory=MockSourceConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    message: MessageConfig = Field(default_factory=MessageConfig)
    engines: EngineConfig = Field(default_factory=EngineConfig)
    testing: TestingConfig = Field(default_factory=TestingConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    project_memory: ProjectMemoryConfig = Field(default_factory=ProjectMemoryConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        if path is not None:
            self.path = path
        else:
            configured = os.getenv("REQ2CODE_CONFIG", "").strip()
            local_path = Path(".req2code/config.yaml")
            self.path = Path(configured).expanduser() if configured else (
                local_path if local_path.exists() else Path.home() / ".req2code" / "config.yaml"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _to_dict(self, config: AgentConfig) -> dict[str, Any]:
        return config.model_dump() if hasattr(config, "model_dump") else config.dict()

    def _is_sensitive_path(self, key_path: str) -> bool:
        path_lower = key_path.lower()
        return any(part in path_lower for part in SENSITIVE_KEY_PARTS)

    def mask_value(self, key_path: str, value: Any) -> str:
        if isinstance(value, (dict, list)):
            def sanitize(node: Any, path: str) -> Any:
                if isinstance(node, dict):
                    return {
                        str(key): sanitize(child, f"{path}.{key}" if path else str(key))
                        for key, child in node.items()
                    }
                if isinstance(node, list):
                    return [sanitize(child, f"{path}.{index}") for index, child in enumerate(node)]
                if self._is_sensitive_path(path):
                    return self.mask_value(path, node)
                return node

            return yaml.safe_dump(
                sanitize(value, key_path),
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=True,
            ).strip()
        text = "" if value is None else str(value)
        if not self._is_sensitive_path(key_path):
            return text
        if not text:
            return ""
        if len(text) <= 6:
            return "*" * len(text)
        return f"{text[:3]}***{text[-3:]}"

    def _migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply all migrations to bring raw config dict up to current schema."""
        version = data.get("schema_version", 0)
        data = dict(data)

        if version < 1:
            tapd = dict(data.get("tapd") or {})
            message = dict(data.get("message") or {})
            git = dict(data.get("git") or {})
            engines = dict(data.get("engines") or {})
            if data.get("tapd_api_token") and not tapd.get("api_token"):
                tapd["api_token"] = data["tapd_api_token"]
            if data.get("tapd_base_url") and not tapd.get("base_url"):
                tapd["base_url"] = data["tapd_base_url"]
            if data.get("message_webhook") and not message.get("webhook"):
                message["webhook"] = data["message_webhook"]
            if data.get("engine") and not engines.get("active"):
                engines["active"] = data["engine"]
            if data.get("default_target_branch") and not git.get("target_branch"):
                git["target_branch"] = data["default_target_branch"]
            if data.get("reviewer") and not message.get("reviewer"):
                message["reviewer"] = data["reviewer"]
            data["tapd"] = tapd
            data["message"] = message
            data["git"] = git
            data["engines"] = engines
            for key in (
                "tapd_api_token", "tapd_base_url", "message_webhook",
                "engine", "default_target_branch", "reviewer",
            ):
                data.pop(key, None)
            data["schema_version"] = 1

        if version < 2:
            git = dict(data.get("git") or {})
            git.setdefault("base_branch", git.get("target_branch") or "test")
            git.setdefault("remote_name", "origin")
            git.setdefault("branch_prefix", "req2code")
            git.setdefault("commit_email", "req2code-bot@localhost")
            git["auto_init_if_missing"] = False

            engines = dict(data.get("engines") or {})
            cursor = dict(engines.get("cursor") or {})
            if "--auth" in str(cursor.get("command") or "") or "--task" in str(cursor.get("command") or ""):
                cursor["command"] = "cursor-agent -p --force --output-format stream-json {prompt}"
            cursor.setdefault("prompt_via_stdin", False)
            cursor.setdefault("auth_env_var", "")

            claude = dict(engines.get("claude_code") or {})
            if str(claude.get("command") or "").startswith("claude-code"):
                claude["command"] = "claude -p --output-format stream-json"
            claude.setdefault("prompt_via_stdin", True)
            claude.setdefault("auth_env_var", "ANTHROPIC_API_KEY")

            codex = dict(engines.get("codex") or {})
            codex.setdefault("command", "codex exec --json --sandbox workspace-write -")
            codex.setdefault("prompt_via_stdin", True)
            codex.setdefault("auth_env_var", "CODEX_API_KEY")
            engines.setdefault("codex_enabled", True)
            engines["cursor"] = cursor
            engines["claude_code"] = claude
            engines["codex"] = codex

            tapd = dict(data.get("tapd") or {})
            if tapd.get("detail_endpoint") == "/stories/{id}":
                tapd["detail_endpoint"] = "/stories"
            if tapd.get("bug_detail_endpoint") == "/bugs/{id}":
                tapd["bug_detail_endpoint"] = "/bugs"

            review = dict(data.get("review") or {})
            review.setdefault("require_human_approval", True)
            review.setdefault("approval_base_url", "http://127.0.0.1:8088")
            system = dict(data.get("system") or {})
            system.setdefault("state_dir", "~/.req2code")

            data["git"] = git
            data["engines"] = engines
            data["tapd"] = tapd
            data["review"] = review
            data["system"] = system
            data["schema_version"] = 2

        if version < 3:
            review = dict(data.get("review") or {})
            if review.get("approvals_file") in {None, "", ".req2code/approvals.yaml", "~/.req2code/approvals.yaml"}:
                review["approvals_file"] = "approvals.yaml"
            if review.get("replay_store_file") in {None, "", ".req2code/replay_nonces.yaml", "~/.req2code/replay_nonces.yaml"}:
                review["replay_store_file"] = "replay_nonces.yaml"
            system = dict(data.get("system") or {})
            system.setdefault("state_dir", "~/.req2code")
            data["review"] = review
            data["system"] = system
            data["schema_version"] = 3

        if version < 4:
            project_memory = dict(data.get("project_memory") or {})
            project_memory.setdefault("enabled", True)
            project_memory.setdefault("max_context_chars", 14000)
            project_memory.setdefault("generate_candidate", True)
            project_memory.setdefault("promote_after_approval", True)
            project_memory.setdefault("use_mirror_cache", True)
            project_memory.setdefault("resume_engine_sessions", True)
            data["project_memory"] = project_memory
            data["schema_version"] = 4

        if version < 5:
            engines = dict(data.get("engines") or {})
            for name in ("cursor", "claude_code", "codex"):
                runner = dict(engines.get(name) or {})
                runner.setdefault("model", "")
                engines[name] = runner
            data["engines"] = engines
            data["schema_version"] = 5

        if version < 6:
            git = dict(data.get("git") or {})
            git.setdefault("command_timeout_seconds", 120)
            data["git"] = git
            data["schema_version"] = 6

        if version < 7:
            profiles = list(data.get("source_profiles") or [])
            source = str(data.get("source") or "tapd").strip().lower()
            tapd = dict(data.get("tapd") or {})

            def configured(value: Any) -> bool:
                text = str(value or "").strip()
                return bool(text) and "REPLACE_ME" not in text

            if not profiles and source == "tapd" and all(
                configured(tapd.get(key)) for key in ("app_id", "app_secret", "workspace_id")
            ):
                workspace_id = str(tapd.get("workspace_id") or "").strip()
                safe_workspace = "".join(ch for ch in workspace_id if ch.isalnum() or ch in {"-", "_"})
                profiles.append(
                    {
                        "id": f"tapd-{safe_workspace or 'default'}",
                        "name": f"TAPD {workspace_id or '默认配置'}",
                        "source": "tapd",
                        "tapd": tapd,
                    }
                )
            elif not profiles and source == "mock":
                profiles.append({"id": "mock-default", "name": "Mock 演示", "source": "mock"})
            data["source_profiles"] = profiles
            data["schema_version"] = 7

        if version < 8:
            data.setdefault("feishu", {})
            data["schema_version"] = 8
        return data

    def load(self) -> AgentConfig:
        if not self.path.exists():
            cfg = AgentConfig()
            self.save(cfg)
            return cfg

        with self.path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        raw = self._migrate(raw)
        cfg = AgentConfig(**raw)
        if raw.get("schema_version") != self._load_raw_schema_version():
            self.save(cfg)
        return cfg

    def _load_raw_schema_version(self) -> int:
        if not self.path.exists():
            return CURRENT_SCHEMA_VERSION
        with self.path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return raw.get("schema_version", 0)

    def save(self, config: AgentConfig) -> None:
        payload = yaml.safe_dump(
            self._to_dict(config), allow_unicode=True, sort_keys=False
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(CONFIG_HEADER_COMMENTS)
                f.write("\n")
                f.write(payload)
            try:
                os.chmod(tmp_name, 0o600)
            except OSError:
                pass
            os.replace(tmp_name, self.path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def list_available_keys(self) -> list[str]:
        cfg = self.load()
        data = self._to_dict(cfg)
        keys: list[str] = []

        def walk(node: Any, prefix: str = "") -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    p = f"{prefix}.{k}" if prefix else k
                    if isinstance(v, dict):
                        walk(v, p)
                    else:
                        keys.append(p)

        walk(data)
        return sorted(keys)

    def set(self, key: str, value: Any) -> AgentConfig:
        cfg = self.load()
        data = self._to_dict(cfg)
        keys = key.split(".")
        cursor: dict[str, Any] = data
        for k in keys[:-1]:
            if k not in cursor or not isinstance(cursor[k], dict):
                raise ValueError(f"Unknown config key: {key}")
            cursor = cursor[k]
        if keys[-1] not in cursor:
            raise ValueError(f"Unknown config key: {key}")
        cursor[keys[-1]] = value
        new_cfg = AgentConfig(**data)
        self.save(new_cfg)
        return new_cfg

    def get(self, key: str) -> Any:
        cfg = self.load()
        data = self._to_dict(cfg)
        keys = key.split(".")
        cursor: Any = data
        for k in keys:
            if not isinstance(cursor, dict) or k not in cursor:
                raise ValueError(f"Unknown config key: {key}")
            cursor = cursor[k]
        return cursor
