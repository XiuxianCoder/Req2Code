from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from req2code.config import AgentConfig, RunnerCommandConfig


@dataclass(frozen=True)
class EnginePreflight:
    engine: str
    ok: bool
    installed: bool
    authenticated: bool
    executable: str
    detail: str


ENGINE_ALIASES = {"claude": "claude_code", "claude-code": "claude_code"}
AUTH_PROBES = {
    "claude_code": ("auth", "status"),
    "codex": ("login", "status"),
    "cursor": ("status",),
}
EXPECTED_EXECUTABLES = {
    "claude_code": {"claude"},
    "codex": {"codex"},
    "cursor": {"cursor-agent", "cursor_agent"},
}
LOGIN_HINTS = {
    "claude_code": "请运行 claude auth login，或设置 ANTHROPIC_API_KEY",
    "codex": "请运行 codex login，或设置 CODEX_API_KEY",
    "cursor": "请运行 cursor-agent login，或设置 CURSOR_API_KEY",
}


def normalize_engine(engine: str) -> str:
    normalized = (engine or "claude_code").strip().lower().replace("-", "_")
    return ENGINE_ALIASES.get(normalized, normalized)


def runner_config(cfg: AgentConfig, engine: str) -> RunnerCommandConfig:
    normalized = normalize_engine(engine)
    mapping = {
        "claude_code": cfg.engines.claude_code,
        "codex": cfg.engines.codex,
        "cursor": cfg.engines.cursor,
    }
    if normalized not in mapping:
        raise ValueError(f"Unsupported engine: {engine}")
    return mapping[normalized]


def command_executable(command: str) -> str:
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return ""
    return parts[0].strip('"') if parts else ""


def _credential_configured(config: RunnerCommandConfig) -> bool:
    if config.auth_token.strip():
        return True
    return bool(config.auth_env_var and os.getenv(config.auth_env_var, "").strip())


def inspect_engine(cfg: AgentConfig, engine: str, timeout_seconds: float = 10.0) -> EnginePreflight:
    normalized = normalize_engine(engine)
    config = runner_config(cfg, normalized)
    executable = command_executable(config.command)
    if not executable:
        return EnginePreflight(normalized, False, False, False, "", "引擎命令尚未配置")

    resolved = shutil.which(executable)
    if not resolved and Path(executable).is_file():
        resolved = str(Path(executable).resolve())
    if not resolved:
        return EnginePreflight(
            normalized,
            False,
            False,
            False,
            executable,
            f"未找到可执行文件：{executable}",
        )

    executable_name = Path(executable).stem.lower()
    known_executable = executable_name in EXPECTED_EXECUTABLES[normalized]
    if _credential_configured(config):
        if known_executable:
            try:
                version_result = subprocess.run(
                    [resolved, "--version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=timeout_seconds,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return EnginePreflight(
                    normalized,
                    False,
                    True,
                    False,
                    resolved,
                    f"无法运行 {executable}：{exc}",
                )
            if version_result.returncode != 0:
                output = (version_result.stderr.strip() or version_result.stdout.strip()).replace("\n", " ")[:300]
                return EnginePreflight(normalized, False, True, False, resolved, f"无法运行 {executable}：{output}")
        return EnginePreflight(
            normalized,
            True,
            True,
            True,
            resolved,
            f"可用：{resolved}；使用 {config.auth_env_var or '已配置凭据'}",
        )

    if not known_executable:
        return EnginePreflight(
            normalized,
            True,
            True,
            True,
            resolved,
            f"可用：{resolved}；自定义命令，认证由该命令负责",
        )

    probe = [resolved, *AUTH_PROBES[normalized]]
    try:
        result = subprocess.run(
            probe,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return EnginePreflight(
            normalized,
            False,
            True,
            False,
            resolved,
            f"无法运行 {executable}：{exc}",
        )

    if result.returncode == 0:
        return EnginePreflight(normalized, True, True, True, resolved, f"可用且已认证：{resolved}")
    output = (result.stderr.strip() or result.stdout.strip()).replace("\n", " ")[:300]
    detail = LOGIN_HINTS[normalized]
    if output:
        detail = f"{detail}；状态：{output}"
    return EnginePreflight(normalized, False, True, False, resolved, detail)


def ensure_engine_ready(cfg: AgentConfig, engine: str) -> EnginePreflight:
    result = inspect_engine(cfg, engine)
    if not result.ok:
        raise RuntimeError(f"{result.engine} 引擎不可用：{result.detail}")
    return result
