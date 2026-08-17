import json
import subprocess
from pathlib import Path

from req2code.host_integration import integrate_host


def _executable(tmp_path: Path) -> Path:
    executable = tmp_path / "bin" / "req2code-mcp.exe"
    executable.parent.mkdir()
    executable.write_text("test", encoding="utf-8")
    return executable


def test_codex_integration_installs_skill_and_upserts_mcp_with_backup(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    config = tmp_path / ".req2code" / "config.yaml"
    config.parent.mkdir()
    config.write_text("source: mock\n", encoding="utf-8")
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    codex_config.write_text('[model_providers.local]\nname = "Local"\n', encoding="utf-8")

    result = integrate_host(
        "codex",
        home=tmp_path,
        config_path=config,
        executable=_executable(tmp_path),
    )

    assert result.skill_path == tmp_path / ".agents" / "skills" / "req2code-workflow"
    assert (result.skill_path / "SKILL.md").is_file()
    rendered = codex_config.read_text(encoding="utf-8")
    assert "[model_providers.local]" in rendered
    assert "[mcp_servers.req2code]" in rendered
    assert "REQ2CODE_CONFIG" in rendered
    assert str(config.resolve()).replace("\\", "\\\\") in rendered
    assert result.backup_path and result.backup_path.is_file()

    second = integrate_host(
        "codex",
        home=tmp_path,
        config_path=config,
        executable=result.mcp_executable,
        overwrite_skill=True,
    )
    assert second.backup_path is None
    assert codex_config.read_text(encoding="utf-8").count("[mcp_servers.req2code]") == 1


def test_packaged_skill_does_not_assume_tapd_before_private_source_selection(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    config = tmp_path / ".req2code" / "config.yaml"
    config.parent.mkdir()
    config.write_text("source: mock\n", encoding="utf-8")

    result = integrate_host(
        "codex",
        home=tmp_path,
        config_path=config,
        executable=_executable(tmp_path),
    )

    skill = (result.skill_path / "SKILL.md").read_text(encoding="utf-8")
    metadata = (result.skill_path / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "render_req2code_launcher" in skill
    assert "Do not assume, announce, or describe any source platform" in skill
    assert "active TAPD work" not in skill
    assert "review TAPD work" not in metadata
    assert "TAPD, Feishu, or Mock" in metadata


def test_cursor_integration_merges_existing_mcp_config(tmp_path):
    cursor_config = tmp_path / ".cursor" / "mcp.json"
    cursor_config.parent.mkdir()
    cursor_config.write_text(
        json.dumps({"mcpServers": {"existing": {"command": "existing-mcp"}}}),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("source: mock\n", encoding="utf-8")

    result = integrate_host(
        "cursor",
        home=tmp_path,
        config_path=config,
        executable=_executable(tmp_path),
    )

    payload = json.loads(cursor_config.read_text(encoding="utf-8"))
    assert payload["mcpServers"]["existing"]["command"] == "existing-mcp"
    assert payload["mcpServers"]["req2code"]["command"] == str(result.mcp_executable)
    assert payload["mcpServers"]["req2code"]["env"]["REQ2CODE_CONFIG"] == str(config.resolve())
    assert result.skill_path == tmp_path / ".cursor" / "skills" / "req2code-workflow"
    assert result.backup_path and result.backup_path.is_file()


def test_claude_integration_uses_official_cli_registration_order(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1 if args[2] == "get" else 0, "", "")

    monkeypatch.setattr("req2code.host_integration.shutil.which", lambda name: "claude.exe" if name == "claude" else None)
    config = tmp_path / "config.yaml"
    config.write_text("source: mock\n", encoding="utf-8")
    executable = _executable(tmp_path)

    result = integrate_host(
        "claude-code",
        home=tmp_path,
        config_path=config,
        executable=executable,
        run_command=fake_run,
    )

    assert result.skill_path == tmp_path / ".claude" / "skills" / "req2code-workflow"
    assert calls[0] == ["claude.exe", "mcp", "get", "req2code"]
    assert calls[1] == [
        "claude.exe",
        "mcp",
        "add",
        "--transport",
        "stdio",
        "--scope",
        "user",
        "--env",
        f"REQ2CODE_CONFIG={config.resolve()}",
        "req2code",
        "--",
        str(executable.resolve()),
    ]
