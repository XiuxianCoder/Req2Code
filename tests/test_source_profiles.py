from req2code.config import AgentConfig, ConfigManager
import pytest

from req2code.source_profiles import (
    build_source_profile,
    save_source_profile,
    source_profile_summary,
    sync_legacy_source_profile,
)


def test_build_tapd_profile_accepts_project_url_and_hides_credentials_from_summary():
    profile = build_source_profile(
        profile_name="产品研发",
        source="tapd",
        auth_mode="oauth2",
        base_url="https://www.tapd.cn/tapd_fe/12345678",
        workspace_id="",
        app_id="client-id",
        app_secret="client-secret",
    )

    assert profile.tapd.base_url == "https://api.tapd.cn"
    assert profile.tapd.workspace_id == "12345678"
    summary = source_profile_summary(profile)
    assert summary["workspace_id"] == "12345678"
    assert "app_id" not in summary
    assert "app_secret" not in summary
    assert "client-id" not in repr(summary)
    assert "client-secret" not in repr(summary)


def test_edit_profile_can_retain_existing_credentials_and_save_atomically(tmp_path):
    manager = ConfigManager(path=tmp_path / "config.yaml")
    original = build_source_profile(
        profile_name="研发 TAPD",
        source="tapd",
        auth_mode="oauth2",
        workspace_id="12345678",
        app_id="client-id",
        app_secret="client-secret",
    )
    save_source_profile(manager, original)

    edited = build_source_profile(
        profile_id=original.id,
        profile_name="研发 TAPD（主项目）",
        source="tapd",
        existing=original,
        auth_mode="oauth2",
        workspace_id="https://www.tapd.cn/12345678/prong/stories/stories_list",
        app_id="",
        app_secret="",
    )
    save_source_profile(manager, edited)

    loaded = manager.load()
    assert loaded.source_profiles[0].name == "研发 TAPD（主项目）"
    assert loaded.source_profiles[0].tapd.app_id == "client-id"
    assert loaded.source_profiles[0].tapd.app_secret == "client-secret"
    assert loaded.source_profiles[0].tapd.workspace_id == "12345678"
    assert not list(tmp_path.glob("*.tmp"))


def test_build_feishu_profile_detects_bitable_and_retains_credentials_on_edit(tmp_path):
    manager = ConfigManager(path=tmp_path / "config.yaml")
    original = build_source_profile(
        profile_name="产品缺陷表",
        source="feishu",
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret-value",
        document_url="https://example.feishu.cn/base/bascnToken?table=tblIssues&view=vewOpen",
        parse_mode="auto",
    )
    save_source_profile(manager, original)

    summary = source_profile_summary(original)
    assert summary["source_label"] == "飞书"
    assert summary["resource_type"] == "bitable"
    assert summary["table_id"] == "tblIssues"
    assert "secret-value" not in repr(summary)

    edited = build_source_profile(
        profile_id=original.id,
        profile_name="产品缺陷表（进行中）",
        source="feishu",
        existing=original,
        auth_mode="tenant",
        app_id="",
        app_secret="",
        document_url="https://example.feishu.cn/base/bascnToken?table=tblIssues",
        parse_mode="table_rows",
    )
    save_source_profile(manager, edited)
    loaded = manager.load().source_profiles[0]
    assert loaded.feishu.app_id == "cli_a123"
    assert loaded.feishu.app_secret == "secret-value"
    assert loaded.feishu.parse_mode == "table_rows"


def test_explicit_bitable_table_rewrites_url_and_drops_view_from_the_old_table():
    profile = build_source_profile(
        profile_name="测试记录",
        source="feishu",
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret-value",
        document_url="https://example.feishu.cn/base/bascnToken?table=tblGuide&view=vewGuide",
        table_id="tblIssues",
        view_id="",
    )

    assert profile.feishu.table_id == "tblIssues"
    assert profile.feishu.view_id == ""
    assert "table=tblIssues" in profile.feishu.document_url
    assert "tblGuide" not in profile.feishu.document_url
    assert "view=" not in profile.feishu.document_url


def test_feishu_profile_requires_app_credentials():
    with pytest.raises(ValueError, match="App ID/App Secret"):
        build_source_profile(
            profile_name="个人飞书需求",
            source="feishu",
            auth_mode="tenant",
            document_url="https://example.feishu.cn/docx/doxcnToken",
        )


def test_feishu_profile_accepts_spreadsheet_and_detects_sheet_id():
    profile = build_source_profile(
        profile_name="电子表格",
        source="feishu",
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret-value",
        document_url="https://example.feishu.cn/sheets/shtcnToken?sheet=giDk9k",
    )

    assert profile.feishu.resource_type == "auto"
    assert profile.feishu.sheet_id == "giDk9k"
    assert source_profile_summary(profile)["resource_type"] == "spreadsheet"


def test_terminal_feishu_configuration_is_exposed_to_ui_profiles():
    profile = build_source_profile(
        profile_name="飞书默认配置",
        source="feishu",
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret-value",
        document_url="https://example.feishu.cn/base/bascnToken",
    )
    cfg = AgentConfig(source="feishu", feishu=profile.feishu)

    sync_legacy_source_profile(cfg)

    assert len(cfg.source_profiles) == 1
    assert cfg.source_profiles[0].source == "feishu"
    assert cfg.source_profiles[0].feishu.document_url.endswith("/base/bascnToken")
