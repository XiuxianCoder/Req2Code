from pathlib import Path

import pytest
from mcp.types import CallToolResult

from req2code.config import AgentConfig, SourceProfileConfig
from req2code.mcp_server import (
    DEVELOPMENT_REVIEW_META_KEY,
    DEVELOPMENT_REVIEW_URI,
    FEISHU_ANALYSIS_META_KEY,
    WORK_ITEM_SELECTOR_META_KEY,
    WORK_ITEM_SELECTOR_URI,
    WORKFLOW_LAUNCHER_META_KEY,
    _validate_work_item_table_schema,
    _default_branch,
    _prepare_development_run,
    _resolve_items,
    confirm_work_item_selection,
    create_work_item_selection,
    create_work_item_selection_for_ui,
    development_review_resource,
    get_development_review_for_ui,
    get_feishu_table_analysis_task,
    get_work_item_selection_for_ui,
    get_req2code_launcher_for_ui,
    mcp,
    render_development_review,
    render_req2code_launcher,
    render_work_item_selector,
    save_source_profile_for_ui,
    submit_feishu_table_analysis,
    work_item_selector_resource,
)
from req2code.models import TaskType, WorkItem
from req2code.repository import PreparedRepository, RepositoryWorkspace
from req2code.run_state import RunRecord, RunStatus
from req2code.selection import WorkItemSelectionStore
from req2code.workflow import WorkflowService


class TypedSource:
    def get_by_id_with_type(self, item_id: str, item_type: str):
        kind = TaskType.BUG if item_type == "bug" else TaskType.REQUIREMENT
        return WorkItem(id=item_id, title=item_id, description="", type=kind)


class SelectableSource:
    def fetch_latest_all(self, limit: int):
        return [
            WorkItem(
                id="DEMO-0001",
                title="Already fixed",
                description="Do not offer this item.",
                type=TaskType.BUG,
                metadata={"Bug": {"status": "resolved"}},
            ),
            WorkItem(
                id="DEMO-0151",
                title="Card layout",
                description='Move the checkbox and add single delete.<img src="/tfl/card-layout.png" />',
                type=TaskType.BUG,
                metadata={
                    "Bug": {
                        "status": "in_progress",
                        "priority": "high",
                        "severity": "serious",
                        "current_owner": "Developer;",
                        "reporter": "Reporter",
                        "modified": "2026-08-15 12:00:00",
                        "custom_field_one": "custom-value",
                        "empty_custom_field": "",
                        "attachments": [{"name": "card-layout.png", "url": "/tfl/card-layout.png"}],
                    }
                },
            ),
            WorkItem(
                id="DEMO-0102",
                title="New flow",
                description="Build and test the new flow.",
                type=TaskType.REQUIREMENT,
            ),
        ][:limit]


class AnalyzedFeishuSource:
    def fetch_latest_all(self, limit: int):
        return [
            WorkItem(
                id="rec-active",
                title="保存失败",
                description="点击保存没有响应",
                type=TaskType.BUG,
                source="feishu",
                metadata={
                    "normalized_fields": {"status": "未解决", "status_bucket": "active", "priority": "严重"},
                    "source_fields": {"问题分类": "问题", "状态": "未解决", "角色": "PM"},
                    "feishu_schema": {
                        "analysis_id": "analysis-1",
                        "display_fields": ["问题分类", "状态", "角色"],
                        "notes": ["问题分类决定工作项类型"],
                    },
                },
            ),
            WorkItem(
                id="rec-done",
                title="已经验证",
                description="不应出现在选择器",
                type=TaskType.BUG,
                source="feishu",
                metadata={"normalized_fields": {"status": "已验证", "status_bucket": "terminal"}},
            ),
        ][:limit]


def test_mcp_exposes_model_workflow_and_private_review_actions():
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert "prepare_development_run" in names
    assert "start_development_run" in names
    assert "finalize_development_run" in names
    assert "verify_development_run" in names
    assert "get_run" in names
    assert "list_projects" in names
    assert "get_project_memory" in names
    assert "create_work_item_selection" in names
    assert "render_req2code_launcher" in names
    assert "get_req2code_launcher_for_ui" in names
    assert "inspect_feishu_bitable_for_ui" in names
    assert "create_feishu_table_analysis_for_ui" in names
    assert "get_feishu_table_analysis_for_ui" in names
    assert "get_feishu_table_analysis_task" in names
    assert "submit_feishu_table_analysis" in names
    assert "save_source_profile_for_ui" in names
    assert "create_work_item_selection_for_ui" in names
    assert "render_work_item_selector" in names
    assert "get_work_item_selection_for_ui" in names
    assert "confirm_work_item_selection" in names
    assert "render_development_review" in names
    assert "get_development_review_for_ui" in names
    assert "publish_reviewed_run_for_ui" in names
    assert "request_development_changes_for_ui" in names
    assert not any("approve" in name or "forget" in name for name in names)

    resources = {str(resource.uri): resource for resource in mcp._resource_manager.list_resources()}
    assert resources[WORK_ITEM_SELECTOR_URI].mime_type == "text/html;profile=mcp-app"
    assert resources[DEVELOPMENT_REVIEW_URI].mime_type == "text/html;profile=mcp-app"
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    assert tools["render_req2code_launcher"].meta["ui"]["resourceUri"] == WORK_ITEM_SELECTOR_URI
    assert tools["render_work_item_selector"].meta["ui"]["resourceUri"] == WORK_ITEM_SELECTOR_URI
    assert tools["render_work_item_selector"].meta["openai/widgetAccessible"] is True
    assert tools["render_work_item_selector"].meta["openai/outputTemplate"] == WORK_ITEM_SELECTOR_URI
    assert tools["render_work_item_selector"].output_schema is None
    assert tools["submit_feishu_table_analysis"].meta["ui"]["resourceUri"] == WORK_ITEM_SELECTOR_URI
    assert tools["submit_feishu_table_analysis"].meta["openai/outputTemplate"] == WORK_ITEM_SELECTOR_URI
    assert tools["submit_feishu_table_analysis"].meta["openai/widgetAccessible"] is True
    for name in (
        "get_req2code_launcher_for_ui",
        "inspect_feishu_bitable_for_ui",
        "create_feishu_table_analysis_for_ui",
        "get_feishu_table_analysis_for_ui",
        "save_source_profile_for_ui",
        "create_work_item_selection_for_ui",
        "get_work_item_selection_for_ui",
        "confirm_work_item_selection",
    ):
        assert tools[name].meta["ui"]["visibility"] == ["app"]
        assert tools[name].meta["openai/visibility"] == "private"
        assert tools[name].meta["openai/widgetAccessible"] is True
    assert "openai/visibility" not in tools["submit_feishu_table_analysis"].meta
    assert tools["finalize_development_run"].meta["ui"]["resourceUri"] == DEVELOPMENT_REVIEW_URI
    assert tools["finalize_development_run"].output_schema is None
    assert tools["render_development_review"].meta["openai/widgetAccessible"] is True
    for name in (
        "get_development_review_for_ui",
        "publish_reviewed_run_for_ui",
        "request_development_changes_for_ui",
    ):
        assert tools[name].meta["ui"]["visibility"] == ["app"]
        assert tools[name].meta["openai/visibility"] == "private"
        assert tools[name].meta["openai/widgetAccessible"] is True


def test_selector_hides_candidates_until_human_confirmation(tmp_path, monkeypatch):
    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path / "state")
    monkeypatch.setattr("req2code.mcp_server.ConfigManager.load", lambda self: cfg)
    monkeypatch.setattr("req2code.mcp_server.get_source_connector", lambda config: SelectableSource())

    created = create_work_item_selection(limit=20)
    assert created["item_count"] == 2
    assert created["ui_state"] == "awaiting_user_selection"
    assert "items" not in created

    rendered = render_work_item_selector(created["selection_id"])
    assert isinstance(rendered, CallToolResult)
    assert rendered.structuredContent["ui_state"] == "awaiting_user_selection"
    assert "items" not in rendered.structuredContent
    assert [item["key"] for item in rendered.meta[WORK_ITEM_SELECTOR_META_KEY]["items"]] == ["B0151", "S0102"]

    ui_result = get_work_item_selection_for_ui(created["selection_id"])
    assert isinstance(ui_result, CallToolResult)
    assert "items" not in ui_result.structuredContent
    ui_payload = ui_result.meta[WORK_ITEM_SELECTOR_META_KEY]
    assert [item["key"] for item in ui_payload["items"]] == ["B0151", "S0102"]
    assert ui_payload["items"][0]["status"] == "in_progress"
    assert ui_payload["items"][0]["priority"] == "high"
    assert ui_payload["items"][0]["severity"] == "serious"
    assert ui_payload["items"][0]["owner"] == "Developer"
    assert ui_payload["items"][0]["description_excerpt"] == "Move the checkbox and add single delete."
    assert "metadata" not in ui_payload["items"][0]
    assert "description" not in ui_payload["items"][0]

    confirmed = confirm_work_item_selection(created["selection_id"], ["B0151"])
    assert confirmed["selected_keys"] == ["B0151"]
    assert [item["key"] for item in confirmed["selected_items"]] == ["B0151"]
    assert all(item["key"] != "S0102" for item in confirmed["selected_items"])
    assert confirmed["selected_items"][0]["tapd_fields"]["custom_field_one"] == "custom-value"
    assert "empty_custom_field" not in confirmed["selected_items"][0]["tapd_fields"]
    assert "task_brief" in confirmed["next_action"]
    assert f"selection_id={created['selection_id']}" in confirmed["handoff_prompt"]
    assert "Move the checkbox and add single delete." in confirmed["handoff_prompt"]
    assert '<img src=\\"/tfl/card-layout.png\\"' in confirmed["handoff_prompt"]
    assert '"custom_field_one":"custom-value"' in confirmed["handoff_prompt"]
    assert '"attachments":[{"name":"card-layout.png","url":"/tfl/card-layout.png"}]' in confirmed["handoff_prompt"]
    assert "prepare_development_run" in confirmed["handoff_prompt"]
    assert "waiting_approval" in confirmed["handoff_prompt"]
    assert "Story item" not in confirmed["handoff_prompt"]


def test_launcher_keeps_profiles_and_credentials_out_of_model_result(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("REQ2CODE_CONFIG", str(config_path))
    monkeypatch.setattr("req2code.mcp_server._validate_source_profile_connection", lambda cfg, profile: None)

    initial = render_req2code_launcher()
    assert initial.structuredContent["profile_count"] == 0
    assert "profiles" not in initial.structuredContent
    assert initial.meta[WORKFLOW_LAUNCHER_META_KEY]["ui_state"] == "configuration_required"

    saved = save_source_profile_for_ui(
        profile_name="产品研发",
        source="tapd",
        auth_mode="oauth2",
        workspace_id="12345678",
        app_id="private-client",
        app_secret="private-secret",
    )
    assert saved["profile"]["name"] == "产品研发"
    assert "private-client" not in repr(saved)
    assert "private-secret" not in repr(saved)

    hydrated = get_req2code_launcher_for_ui()
    assert "profiles" not in hydrated.structuredContent
    private_launcher = hydrated.meta[WORKFLOW_LAUNCHER_META_KEY]
    assert private_launcher["profiles"][0]["name"] == "产品研发"
    assert "private-client" not in repr(private_launcher)
    assert "private-secret" not in repr(private_launcher)


def test_saved_feishu_profile_is_returned_when_launcher_is_opened_again(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("REQ2CODE_CONFIG", str(config_path))
    monkeypatch.setattr("req2code.mcp_server._validate_source_profile_connection", lambda cfg, profile: None)

    saved = save_source_profile_for_ui(
        profile_name="飞书测试记录",
        source="feishu",
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="private-secret",
        document_url="https://example.feishu.cn/base/bascnApp?table=tblIssues&view=vewOpen",
    )
    reopened = render_req2code_launcher()
    profiles = reopened.meta[WORKFLOW_LAUNCHER_META_KEY]["profiles"]

    assert saved["profile"]["id"] == profiles[0]["id"]
    assert profiles[0]["source"] == "feishu"
    assert profiles[0]["table_id"] == "tblIssues"
    assert profiles[0]["view_id"] == "vewOpen"
    assert "private-secret" not in repr(reopened)


def test_private_profile_selection_records_the_chosen_project(tmp_path, monkeypatch):
    cfg = AgentConfig(
        source_profiles=[SourceProfileConfig(id="mock-team", name="演示项目", source="mock")]
    )
    cfg.system.state_dir = str(tmp_path / "state")
    monkeypatch.setattr("req2code.mcp_server.ConfigManager.load", lambda self: cfg)
    monkeypatch.setattr(
        "req2code.mcp_server.get_source_connector",
        lambda config, profile_id="": SelectableSource(),
    )

    result = create_work_item_selection_for_ui("mock-team", limit=20)

    assert "items" not in result.structuredContent
    payload = result.meta[WORK_ITEM_SELECTOR_META_KEY]
    assert payload["source_profile_id"] == "mock-team"
    assert payload["source_profile_name"] == "演示项目"
    assert [item["key"] for item in payload["items"]] == ["B0151", "S0102"]


def test_selector_excludes_terminal_work_items(tmp_path, monkeypatch):
    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path / "state")
    monkeypatch.setattr("req2code.mcp_server.ConfigManager.load", lambda self: cfg)
    monkeypatch.setattr("req2code.mcp_server.get_source_connector", lambda config: SelectableSource())

    created = create_work_item_selection(limit=20)
    ui_payload = get_work_item_selection_for_ui(created["selection_id"]).meta[WORK_ITEM_SELECTOR_META_KEY]

    assert created["item_count"] == 2
    assert all(item["title"] != "Already fixed" for item in ui_payload["items"])


def test_feishu_analysis_filters_terminal_rows_and_renders_key_fields(tmp_path, monkeypatch):
    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path / "state")
    monkeypatch.setattr("req2code.mcp_server.ConfigManager.load", lambda self: cfg)
    monkeypatch.setattr("req2code.mcp_server.get_source_connector", lambda config: AnalyzedFeishuSource())

    created = create_work_item_selection(limit=20)
    ui_payload = get_work_item_selection_for_ui(created["selection_id"]).meta[WORK_ITEM_SELECTOR_META_KEY]

    assert created["item_count"] == 1
    assert ui_payload["items"][0]["display_fields"] == {"问题分类": "问题", "状态": "未解决", "角色": "PM"}
    confirmed = confirm_work_item_selection(created["selection_id"], [ui_payload["items"][0]["key"]])
    assert confirmed["selected_items"][0]["analysis_notes"] == ["问题分类决定工作项类型"]
    assert confirmed["selected_items"][0]["field_analysis_id"] == "analysis-1"


def test_obvious_instruction_table_is_rejected_before_agent_analysis():
    with pytest.raises(ValueError, match="使用说明") as exc_info:
        _validate_work_item_table_schema(
            ["序号", "内容"],
            table_name="使用说明",
            available_tables=[
                {"table_id": "tblHelp", "name": "使用说明"},
                {"table_id": "tblIssues", "name": "⭐️测试用例执行记录表"},
            ],
        )

    assert "测试用例执行记录表" in str(exc_info.value)
    _validate_work_item_table_schema(["问题描述", "问题分类", "状态", "负责人"])


def test_submitted_feishu_analysis_opens_selector_at_tool_result(tmp_path, monkeypatch):
    from req2code.feishu_analysis import FeishuTableAnalysisStore

    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path / "state")
    monkeypatch.setattr("req2code.mcp_server.ConfigManager.load", lambda self: cfg)
    analysis = FeishuTableAnalysisStore(cfg.system.state_dir).create(
        profile_id="feishu-product",
        profile_name="飞书问题库",
        table_id="tblIssues",
        view_id="vewOpen",
        field_names=["问题描述", "问题分类", "状态", "负责人"],
        field_samples={},
    )

    task = get_feishu_table_analysis_task(analysis.analysis_id)
    assert task["analysis_id"] == analysis.analysis_id
    assert "analysis_payload=" in task["analysis_prompt"]
    assert "App Secret" not in repr(task)

    result = submit_feishu_table_analysis(
        analysis.analysis_id,
        title_field="问题描述",
        description_fields=["问题描述"],
        type_field="问题分类",
        status_field="状态",
        owner_field="负责人",
        bug_values=["问题"],
        active_statuses=["未解决"],
        terminal_statuses=["已解决"],
        display_fields=["问题分类", "状态", "负责人"],
    )

    assert isinstance(result, CallToolResult)
    assert result.structuredContent["status"] == "completed"
    launch = result.meta[FEISHU_ANALYSIS_META_KEY]
    assert launch == {
        "analysis_id": analysis.analysis_id,
        "profile_id": "feishu-product",
        "profile_name": "飞书问题库",
        "status": "completed",
    }


def test_selector_resource_initializes_mcp_apps_before_waiting_for_tool_result():
    html = work_item_selector_resource()
    assert "[hidden] { display: none !important; }" in html
    assert 'activeProvider = source || "tapd"' not in html
    assert 'activeProvider || data?.source || "tapd"' not in html
    assert 'request("ui/initialize"' in html
    assert 'notify("ui/notifications/initialized")' in html
    assert 'message.method === "ui/notifications/tool-result"' in html
    assert 'const selectionMetaKey = "req2code/selection"' in html
    assert 'const launcherMetaKey = "req2code/launcher"' in html
    assert 'const analysisMetaKey = "req2code/feishu-analysis"' in html
    assert 'window.addEventListener("openai:set_globals"' in html
    assert '"mcp_tool_result", "call_tool_result"' in html
    assert 'callMcpTool("get_work_item_selection_for_ui"' in html
    assert 'callMcpTool("save_source_profile_for_ui"' in html
    assert 'callMcpTool("inspect_feishu_bitable_for_ui"' in html
    assert 'callMcpTool("create_feishu_table_analysis_for_ui"' in html
    assert 'callMcpTool("delete_source_profile_for_ui"' in html
    assert 'callMcpTool("create_work_item_selection_for_ui"' in html
    assert 'id="configForm"' in html
    assert 'id="platformScreen"' in html
    assert 'id="chooseFeishu"' in html
    assert 'id="documentUrl"' in html
    assert 'id="refreshProfiles"' in html
    assert 'id="inspectFeishuBitable"' in html
    assert 'type="password"' in html
    assert 'id="typeFilter"' in html
    assert 'id="retryAnalysis"' in html
    assert "需求 ${storyCount} · 缺陷 ${bugCount}" in html
    assert 'request("ui/update-model-context"' not in html
    assert "sendFollowUp(developmentHandoff(result))" in html
    assert "get_feishu_table_analysis_task(analysis_id=" in html
    assert "不要复述表格字段或样例" in html
    assert "void createSelectionForProfile(analysisLaunch.profile_id, analysisLaunch.analysis_id)" in html
    assert 'request("ui/message"' in html
    assert "sendFollowUpMessage({ prompt: message, title, scrollToBottom: true })" in html
    assert "profile.resource_type === \"bitable\"" in html
    assert "全部选择项" in html
    assert "selected_items=${JSON.stringify(selectedItems)}" in html


def test_review_resource_requires_two_distinct_human_actions():
    html = development_review_resource()
    assert 'id="approve"' in html
    assert "审核通过，进入发布确认" in html
    assert 'id="publishDialog"' in html
    assert 'id="publishCheck"' in html
    assert "确认提交并推送" in html
    assert 'callMcpTool("publish_reviewed_run_for_ui"' in html
    assert 'callMcpTool("request_development_changes_for_ui"' in html
    assert "data.planned_publication_target" in html
    assert "当前没有提交或推送" in html


def test_review_nonce_and_full_report_are_component_only(tmp_path, monkeypatch):
    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path / "state")
    cfg.message.webhook = ""
    service = WorkflowService(cfg)
    record = RunRecord(
        run_id="review-only",
        work_items=[{"id": "BUG-1", "type": "bug", "title": "Review", "description": "Details"}],
        engine="codex",
        repo_path=str(tmp_path),
        repo_url="https://example.test/repo.git",
        push_url="https://example.test/repo.git",
        remote_name="origin",
        base_branch="main",
        work_branch="main",
        push_branch="main",
        baseline_sha="a" * 40,
        remote_branch_sha="a" * 40,
        execution_mode="current_agent",
        status=RunStatus.WAITING_APPROVAL.value,
        changed_files=["src/review.py"],
        item_results=[{"item_id": "BUG-1", "solution": "fix", "changes": "changed"}],
        test_result={"passed": True, "details": "2 passed"},
    )
    service.runs.save(record)
    monkeypatch.setattr("req2code.mcp_server.ConfigManager.load", lambda self: cfg)

    result = get_development_review_for_ui(record.run_id)
    assert isinstance(result, CallToolResult)
    assert "publish_nonce" not in result.structuredContent
    assert "work_items" not in result.structuredContent
    private_payload = result.meta[DEVELOPMENT_REVIEW_META_KEY]
    assert private_payload["publish_nonce"]
    assert private_payload["work_items"][0]["description"] == "Details"

    rendered = render_development_review(record.run_id)
    assert "publish_nonce" not in rendered.structuredContent
    assert rendered.structuredContent["ui_state"] == "waiting_for_human_review"


def test_mcp_resolves_mixed_work_items():
    items = _resolve_items(TypedSource(), ["story:101", "bug:202"])
    assert [item.id for item in items] == ["101", "202"]
    assert [item.type for item in items] == [TaskType.REQUIREMENT, TaskType.BUG]


def test_legacy_default_branch_helper_still_batches_items():
    assert _default_branch(["story:101", "bug:202"], "req2code") == "req2code/batch-101-2"


def test_confirmed_selection_id_prepares_current_agent_task(tmp_path, monkeypatch):
    cfg = AgentConfig()
    cfg.system.state_dir = str(tmp_path / "state")
    cfg.message.webhook = ""
    store = WorkItemSelectionStore(cfg.system.state_dir)
    selection = store.create(
        [{"id": "DEMO-0151", "type": "bug", "title": "Card", "description": "Fix card"}]
    )
    store.confirm(selection.selection_id, ["B0151"])

    monkeypatch.setattr("req2code.mcp_server.ConfigManager.load", lambda self: cfg)
    monkeypatch.setattr("req2code.mcp_server.get_source_connector", lambda config: TypedSource())

    def prepare(self, spec, run_id):
        return PreparedRepository(
            path=Path(tmp_path),
            repo_url="https://example.test/repo.git",
            push_url="https://example.test/repo.git",
            remote_name="origin",
            base_branch="main",
            work_branch="main",
            push_branch="main",
            baseline_sha="a" * 40,
            remote_branch_sha="a" * 40,
            branch_mode="current",
        )

    monkeypatch.setattr(RepositoryWorkspace, "prepare", prepare)
    result = _prepare_development_run(selection_id=selection.selection_id, local_path=str(tmp_path))

    assert result["status"] == "developing"
    assert result["work_items"][0]["id"] == "DEMO-0151"
    assert "finalize_development_run" in result["task_brief"]
    assert result["push_locked_until_approval"] is True
    assert "post_approval_push_target" not in result
    assert "push_target" not in result
    assert "第二次发布确认" in result["task_brief"]
    development_review_resource,
    get_development_review_for_ui,
    render_development_review,
