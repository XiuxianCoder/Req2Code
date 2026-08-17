from click import unstyle
from typer.testing import CliRunner

from req2code import __version__
from req2code.config import AgentConfig
from req2code.connectors.mock_connector import MockConnector
from req2code.main import _configure_feishu, _configure_tapd, _workspace_id_from_tapd_url, app
from req2code.models import TaskType


def test_cli_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"Req2Code {__version__}" in result.stdout


def test_mock_source_has_actionable_story_and_bug():
    items = list(MockConnector().fetch_latest())
    assert [item.id for item in items] == ["DEMO-STORY-1", "DEMO-BUG-1"]
    assert [item.type for item in items] == [TaskType.REQUIREMENT, TaskType.BUG]
    assert "multiply" in MockConnector().get_by_id("DEMO-STORY-1").description

def test_start_help_uses_current_agent_without_engine_selection():
    result = CliRunner().invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    start_help = unstyle(result.stdout)
    assert "--agent-name" in start_help
    assert "--engine" not in start_help
    assert "--model" not in start_help

    finalize = CliRunner().invoke(app, ["finalize", "--help"])
    assert finalize.exit_code == 0
    finalize_help = unstyle(finalize.stdout)
    assert "--test-evidence" in finalize_help
    assert "--rerun-tests" in finalize_help

    verify = CliRunner().invoke(app, ["verify", "--help"])
    assert verify.exit_code == 0
    assert "--summary" in unstyle(verify.stdout)

    integrate = CliRunner().invoke(app, ["integrate", "--help"])
    assert integrate.exit_code == 0
    assert "Install the Skill and automatically register" in unstyle(integrate.stdout)


def test_tapd_workspace_page_extracts_workspace_id(monkeypatch):
    cfg = AgentConfig()

    def answer(prompt, default=None, **kwargs):
        if prompt.startswith("TAPD API"):
            return "https://www.tapd.cn/tapd_fe/12345678"
        if prompt == "TAPD 开放应用 app_id":
            return "test-app"
        if prompt == "TAPD 开放应用 app_secret":
            return "test-secret"
        if prompt.startswith("TAPD workspace_id"):
            assert default == "12345678"
            return default
        raise AssertionError(prompt)

    monkeypatch.setattr("req2code.main._prompt_choice", lambda *args, **kwargs: "oauth2")
    monkeypatch.setattr("req2code.main.typer.prompt", answer)
    assert _configure_tapd(cfg) is True
    assert cfg.tapd.auth_mode == "oauth2"
    assert cfg.tapd.base_url == "https://api.tapd.cn"
    assert cfg.tapd.workspace_id == "12345678"
    assert _workspace_id_from_tapd_url("https://www.tapd.cn/tapd_fe/12345678") == "12345678"


def test_tapd_setup_supports_basic_api_account(monkeypatch):
    cfg = AgentConfig()

    def answer(prompt, default=None, **kwargs):
        values = {
            "TAPD API 地址（不是浏览器中的工作空间页面）": "https://api.tapd.cn",
            "TAPD API 账号（api_user）": "api-user",
            "TAPD API 口令（api_password）": "api-password",
            "TAPD workspace_id（工作空间网页 URL 中 tapd_fe/ 后面的数字）": "12345678",
        }
        if prompt in values:
            return values[prompt]
        raise AssertionError(prompt)

    monkeypatch.setattr("req2code.main._prompt_choice", lambda *args, **kwargs: "basic")
    monkeypatch.setattr("req2code.main.typer.prompt", answer)

    assert _configure_tapd(cfg) is True
    assert cfg.tapd.auth_mode == "basic"
    assert cfg.tapd.app_id == "api-user"
    assert cfg.tapd.app_secret == "api-password"
    assert cfg.tapd.workspace_id == "12345678"


def test_existing_tapd_configuration_can_be_reused(monkeypatch):
    cfg = AgentConfig()
    cfg.tapd.app_id = "saved-app"
    cfg.tapd.app_secret = "saved-secret"
    cfg.tapd.workspace_id = "12345678"
    monkeypatch.setattr("req2code.main._prompt_choice", lambda *args, **kwargs: "reuse")
    monkeypatch.setattr(
        "req2code.main.typer.prompt",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prompt should not run")),
    )

    assert _configure_tapd(cfg) is False
    assert cfg.tapd.app_secret == "saved-secret"


def test_feishu_terminal_setup_uses_self_built_application(monkeypatch):
    cfg = AgentConfig(source="feishu")

    def answer(prompt, default=None, **kwargs):
        if prompt.startswith("飞书文档"):
            return "https://example.feishu.cn/sheets/shtcnToken?sheet=giDk9k"
        if prompt == "飞书 App ID":
            return "cli_a123"
        if prompt == "飞书 App Secret":
            return "secret-value"
        raise AssertionError(prompt)

    monkeypatch.setattr("req2code.main.typer.prompt", answer)

    assert _configure_feishu(cfg) is True
    assert cfg.feishu.auth_mode == "tenant"
    assert cfg.feishu.sheet_id == "giDk9k"
    assert cfg.feishu.app_id == "cli_a123"
    assert cfg.feishu.app_secret == "secret-value"
