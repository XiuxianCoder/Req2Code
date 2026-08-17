from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from req2code.config import ConfigManager
from req2code.skill_installer import HOST_SKILL_ROOTS, install_skill


SUPPORTED_HOSTS = ("codex", "claude", "cursor")


@dataclass(frozen=True)
class HostIntegrationResult:
    host: str
    skill_path: Path
    mcp_config_path: Path
    mcp_executable: Path
    req2code_config_path: Path
    backup_path: Path | None = None
    restart_hint: str = ""


def _normalize_host(host: str) -> str:
    normalized = host.strip().lower().replace("_", "-")
    if normalized == "claude-code":
        normalized = "claude"
    if normalized not in SUPPORTED_HOSTS:
        raise ValueError("host must be codex, claude, or cursor")
    return normalized


def resolve_mcp_executable(executable: str | Path | None = None) -> Path:
    if executable:
        candidate = Path(executable).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"Req2Code MCP executable was not found: {candidate}")
        return candidate

    names = ["req2code-mcp.exe", "req2code-mcp"] if os.name == "nt" else ["req2code-mcp", "req2code-mcp.exe"]
    for name in names:
        beside_python = Path(sys.executable).resolve().parent / name
        if beside_python.is_file():
            return beside_python
        discovered = shutil.which(name)
        if discovered:
            return Path(discovered).resolve()
    raise FileNotFoundError(
        "req2code-mcp was not found beside the active Python or on PATH; install Req2Code first"
    )


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.req2code.bak")
    shutil.copy2(path, backup)
    return backup


def _toml_string(value: str | Path) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _upsert_codex_mcp(config_path: Path, executable: Path, req2code_config: Path) -> Path | None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    section_pattern = re.compile(
        r"(?ms)^\[mcp_servers\.req2code\]\s*\n.*?(?=^\[(?!mcp_servers\.req2code(?:\.|\]))|\Z)"
    )
    cleaned = section_pattern.sub("", original).rstrip()
    section = "\n".join(
        [
            "[mcp_servers.req2code]",
            f"command = {_toml_string(executable)}",
            f"cwd = {_toml_string(executable.parent)}",
            f"env = {{ REQ2CODE_CONFIG = {_toml_string(req2code_config)} }}",
            "startup_timeout_sec = 20",
            "tool_timeout_sec = 300",
        ]
    )
    updated = f"{cleaned}\n\n{section}\n" if cleaned else f"{section}\n"
    if updated == original:
        return None
    backup = _backup(config_path)
    config_path.write_text(updated, encoding="utf-8")
    return backup


def _upsert_cursor_mcp(config_path: Path, executable: Path, req2code_config: Path) -> Path | None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Cursor MCP config is not valid JSON: {config_path}: {exc}") from exc
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"Cursor MCP config must contain a JSON object: {config_path}")
    servers = payload.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"Cursor mcpServers must be a JSON object: {config_path}")
    expected = {
        "command": str(executable),
        "args": [],
        "env": {"REQ2CODE_CONFIG": str(req2code_config)},
    }
    if servers.get("req2code") == expected:
        return None
    backup = _backup(config_path)
    servers["req2code"] = expected
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup


def _register_claude_mcp(
    claude: str,
    executable: Path,
    req2code_config: Path,
    run_command: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    existing = run_command(
        [claude, "mcp", "get", "req2code"],
        capture_output=True,
        text=True,
        check=False,
    )
    if existing.returncode == 0:
        removed = run_command(
            [claude, "mcp", "remove", "--scope", "user", "req2code"],
            capture_output=True,
            text=True,
            check=False,
        )
        if removed.returncode != 0:
            raise RuntimeError(removed.stderr.strip() or removed.stdout.strip() or "Failed to update Claude MCP")
    added = run_command(
        [
            claude,
            "mcp",
            "add",
            "--transport",
            "stdio",
            "--scope",
            "user",
            "--env",
            f"REQ2CODE_CONFIG={req2code_config}",
            "req2code",
            "--",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode != 0:
        raise RuntimeError(added.stderr.strip() or added.stdout.strip() or "Failed to register Claude MCP")


def integrate_host(
    host: str,
    *,
    home: str | Path | None = None,
    config_path: str | Path | None = None,
    executable: str | Path | None = None,
    overwrite_skill: bool = False,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> HostIntegrationResult:
    """Install the Skill and register the local stdio MCP server for one coding host."""
    normalized = _normalize_host(host)
    user_home = Path(home).expanduser().resolve() if home else Path.home().resolve()
    mcp_executable = resolve_mcp_executable(executable)
    req2code_config = (
        Path(config_path).expanduser().resolve()
        if config_path
        else ConfigManager().path.expanduser().resolve()
    )

    claude_command = ""
    if normalized == "claude":
        claude_command = shutil.which("claude") or ""
        if not claude_command:
            raise FileNotFoundError(
                "Claude Code CLI was not found on PATH; install/login to Claude Code before integration"
            )

    skill_root = user_home / HOST_SKILL_ROOTS[normalized]
    skill_path = install_skill(normalized, destination=skill_root, overwrite=overwrite_skill)
    backup: Path | None = None

    if normalized == "codex":
        codex_home = Path(os.getenv("CODEX_HOME", "")).expanduser() if os.getenv("CODEX_HOME") else user_home / ".codex"
        mcp_config = codex_home.resolve() / "config.toml"
        backup = _upsert_codex_mcp(mcp_config, mcp_executable, req2code_config)
        restart_hint = "Restart Codex or open a new task so it reloads the Skill and MCP server."
    elif normalized == "claude":
        _register_claude_mcp(claude_command, mcp_executable, req2code_config, run_command)
        mcp_config = user_home / ".claude.json"
        restart_hint = "Open a new Claude Code session so the MCP connection is initialized."
    else:
        mcp_config = user_home / ".cursor" / "mcp.json"
        backup = _upsert_cursor_mcp(mcp_config, mcp_executable, req2code_config)
        restart_hint = "Restart Cursor or open a new Agent chat so it reloads the Skill and MCP server."

    return HostIntegrationResult(
        host=normalized,
        skill_path=skill_path,
        mcp_config_path=mcp_config,
        mcp_executable=mcp_executable,
        req2code_config_path=req2code_config,
        backup_path=backup,
        restart_hint=restart_hint,
    )
