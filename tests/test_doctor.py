from req2code.config import AgentConfig
from req2code.doctor import run_doctor


def test_doctor_reports_missing_placeholders():
    cfg = AgentConfig()
    checks = run_doctor(cfg, approval_host="127.0.0.1", approval_port=65530)
    by_name = {c.name: c for c in checks}

    assert by_name["tapd.auth_mode"].ok is True
    assert by_name["tapd.oauth2_credentials"].ok is False
    assert "engine.executable" not in by_name
    assert "engine.authentication" not in by_name
    assert by_name["review.callback_secret"].ok is False
    assert by_name["review.ip_allowlist"].ok is True


def test_doctor_names_basic_api_account_credentials():
    cfg = AgentConfig()
    cfg.tapd.auth_mode = "basic"
    cfg.tapd.app_id = "api-user"
    cfg.tapd.app_secret = "api-password"
    cfg.tapd.workspace_id = "12345678"

    checks = run_doctor(cfg, approval_host="127.0.0.1", approval_port=65530)
    by_name = {c.name: c for c in checks}

    assert by_name["tapd.auth_mode"].detail == "API account Basic"
    assert by_name["tapd.api_account_credentials"].ok is True


def test_doctor_can_check_legacy_nested_engine():
    cfg = AgentConfig()
    checks = run_doctor(
        cfg,
        approval_host="127.0.0.1",
        approval_port=65530,
        check_legacy_engine=True,
    )
    by_name = {c.name: c for c in checks}
    assert "engine.executable" in by_name
    assert "engine.authentication" in by_name


def test_doctor_checks_feishu_application_and_document():
    cfg = AgentConfig(source="feishu")
    cfg.feishu.auth_mode = "tenant"
    cfg.feishu.app_id = "cli_a123"
    cfg.feishu.app_secret = "secret-value"
    cfg.feishu.document_url = "https://example.feishu.cn/base/bascnToken"

    checks = run_doctor(cfg, approval_host="127.0.0.1", approval_port=65530)
    by_name = {c.name: c for c in checks}

    assert by_name["feishu.auth_mode"].ok is True
    assert by_name["feishu.application_credentials"].ok is True
    assert by_name["feishu.document_url"].ok is True
    assert "tapd.auth_mode" not in by_name
