from types import SimpleNamespace

import pytest

from req2code.config import AgentConfig
from req2code.engine_preflight import ensure_engine_ready, inspect_engine


def test_missing_engine_executable_is_rejected(monkeypatch):
    cfg = AgentConfig()
    cfg.engines.active = "codex"
    monkeypatch.setattr("req2code.engine_preflight.shutil.which", lambda executable: None)
    monkeypatch.setattr("req2code.engine_preflight.Path.is_file", lambda path: False)

    result = inspect_engine(cfg, "codex")

    assert result.ok is False
    assert result.installed is False
    with pytest.raises(RuntimeError, match="未找到可执行文件"):
        ensure_engine_ready(cfg, "codex")


def test_codex_api_key_skips_cli_login_probe(monkeypatch):
    cfg = AgentConfig()
    monkeypatch.setenv("CODEX_API_KEY", "test-key")
    monkeypatch.setattr("req2code.engine_preflight.shutil.which", lambda executable: "C:/tools/codex.exe")
    probes = []

    def version_probe(args, **kwargs):
        probes.append(args)
        return SimpleNamespace(returncode=0, stdout="codex 1.0", stderr="")

    monkeypatch.setattr("req2code.engine_preflight.subprocess.run", version_probe)
    result = inspect_engine(cfg, "codex")

    assert result.ok is True
    assert result.authenticated is True
    assert "CODEX_API_KEY" in result.detail
    assert probes == [["C:/tools/codex.exe", "--version"]]


def test_codex_without_login_is_rejected(monkeypatch):
    cfg = AgentConfig()
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setattr("req2code.engine_preflight.shutil.which", lambda executable: "C:/tools/codex.exe")
    monkeypatch.setattr(
        "req2code.engine_preflight.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="Not logged in"),
    )

    result = inspect_engine(cfg, "codex")

    assert result.installed is True
    assert result.authenticated is False
    assert "codex login" in result.detail


def test_inaccessible_engine_binary_is_rejected(monkeypatch):
    cfg = AgentConfig()
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setattr("req2code.engine_preflight.shutil.which", lambda executable: "C:/tools/codex.exe")

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr("req2code.engine_preflight.subprocess.run", denied)
    result = inspect_engine(cfg, "codex")

    assert result.ok is False
    assert result.installed is True
    assert "access denied" in result.detail


def test_api_key_does_not_hide_inaccessible_binary(monkeypatch):
    cfg = AgentConfig()
    monkeypatch.setenv("CODEX_API_KEY", "test-key")
    monkeypatch.setattr("req2code.engine_preflight.shutil.which", lambda executable: "C:/tools/codex.exe")

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr("req2code.engine_preflight.subprocess.run", denied)
    result = inspect_engine(cfg, "codex")

    assert result.ok is False
    assert result.installed is True
    assert "access denied" in result.detail


def test_custom_engine_wrapper_owns_authentication(monkeypatch):
    cfg = AgentConfig()
    cfg.engines.codex.command = "company-codex-wrapper --run"
    monkeypatch.setattr(
        "req2code.engine_preflight.shutil.which",
        lambda executable: "C:/tools/company-codex-wrapper.exe",
    )

    result = inspect_engine(cfg, "codex")

    assert result.ok is True
    assert "自定义命令" in result.detail
