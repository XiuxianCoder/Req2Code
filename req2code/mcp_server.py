from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from req2code.config import ConfigManager, FeishuFieldMappingConfig
from req2code.connectors.feishu_connector import FeishuConnector
from req2code.feishu_analysis import FeishuTableAnalysisStore, build_analysis_prompt
from req2code.models import WorkItem
from req2code.repository import RepositorySpec
from req2code.selection import WorkItemSelection, WorkItemSelectionStore
from req2code.source_factory import get_source_connector
from req2code.source_profiles import (
    build_source_profile,
    config_for_source_profile,
    delete_source_profile,
    require_source_profile,
    save_source_profile,
    source_profile_summary,
)
from req2code.workflow import WorkflowService

mcp = FastMCP("Req2Code")
WORK_ITEM_SELECTOR_URI = "ui://req2code/workflow-launcher-v8.html"
WORK_ITEM_SELECTOR_META_KEY = "req2code/selection"
WORKFLOW_LAUNCHER_META_KEY = "req2code/launcher"
FEISHU_ANALYSIS_META_KEY = "req2code/feishu-analysis"
DEVELOPMENT_REVIEW_URI = "ui://req2code/development-review-v1.html"
DEVELOPMENT_REVIEW_META_KEY = "req2code/development-review"
TERMINAL_WORK_ITEM_STATUSES = {
    "resolved",
    "verified",
    "closed",
    "rejected",
    "done",
    "completed",
    "cancelled",
    "canceled",
    "fixed",
    "已解决",
    "已验证",
    "已关闭",
    "已拒绝",
    "已完成",
    "已取消",
    "完成",
    "关闭",
    "解决",
    "废弃",
    "终止",
}


def _item_payload(item: WorkItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type.value,
        "title": item.title,
        "description": item.description,
        "source": item.source,
        "metadata": item.metadata,
    }


def _source_record(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    normalized = metadata.get("normalized_fields")
    if isinstance(normalized, dict):
        return normalized
    for wrapper in ("Bug", "Story"):
        wrapped = metadata.get(wrapper)
        if isinstance(wrapped, dict):
            return wrapped
    return metadata


def _tapd_record(metadata: Any) -> dict[str, Any]:
    """Backward-compatible alias for integrations importing the old helper."""
    return _source_record(metadata)


def _display_value(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value in (None, "", "0", 0, [], {}):
            continue
        if isinstance(value, list):
            value = ", ".join(str(part) for part in value if part not in (None, ""))
        text = str(value).strip().strip(";").strip()
        if text:
            return text
    return ""


def _plain_excerpt(value: Any, limit: int = 180) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    return f"{text[:limit].rstrip()}…" if len(text) > limit else text


def _validate_work_item_table_schema(
    field_names: list[str],
    *,
    table_name: str = "",
    available_tables: list[dict[str, Any]] | None = None,
) -> None:
    """Reject obvious instructions/cover sheets before asking an agent to map them."""
    normalized = [re.sub(r"[\s_\-]+", "", str(name)).lower() for name in field_names if str(name).strip()]
    signal_groups = (
        ("问题", "缺陷", "需求", "标题", "描述", "内容", "事项", "用例", "issue", "bug", "title", "description"),
        ("状态", "结果", "进度", "status", "result"),
        ("分类", "类型", "类别", "type", "category"),
        ("负责人", "责任人", "处理人", "经办人", "角色", "owner", "assignee"),
        ("优先", "严重", "priority", "severity"),
        ("验收", "期望", "预期", "复现", "步骤", "acceptance", "expected", "reproduce"),
    )
    signal_count = sum(any(token in field for field in normalized for token in group) for group in signal_groups)
    if signal_count >= 2:
        return

    current_name = table_name or "当前数据表"
    suggestions = [
        str(table.get("name") or "").strip()
        for table in (available_tables or [])
        if str(table.get("name") or "").strip()
        and str(table.get("name") or "").strip() != current_name
        and any(token in str(table.get("name") or "").lower() for token in ("需求", "缺陷", "问题", "测试", "用例", "bug", "issue"))
    ]
    suggestion = f" 建议改选：{'、'.join(suggestions[:5])}。" if suggestions else ""
    fields = "、".join(field_names[:12]) or "无"
    raise ValueError(
        f"当前选择的数据表“{current_name}”只有这些字段：{fields}；它不像需求、缺陷或测试问题表，"
        f"Req2Code 已停止 AI 解析，避免把说明文字误判成工作项。{suggestion}请编辑该飞书配置并选择正确的数据表后重试。"
    )


def _nonempty_source_value(value: Any) -> Any:
    """Recursively retain source fields that contain useful confirmed-item data."""
    if isinstance(value, dict):
        cleaned = {str(key): _nonempty_source_value(child) for key, child in value.items()}
        return {key: child for key, child in cleaned.items() if child not in (None, "", [], {})}
    if isinstance(value, list):
        cleaned = [_nonempty_source_value(child) for child in value]
        return [child for child in cleaned if child not in (None, "", [], {})]
    return value.strip() if isinstance(value, str) else value


def _is_selectable_item(item: WorkItem) -> bool:
    record = _source_record(item.metadata)
    status_bucket = _display_value(record, "status_bucket").strip().lower()
    if status_bucket == "active":
        return True
    if status_bucket in {"terminal", "other"}:
        return False
    status = _display_value(record, "status_name", "status").strip().lower().replace("-", "_").replace(" ", "_")
    return status not in TERMINAL_WORK_ITEM_STATUSES


def _selection_ui_item(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata")
    record = _source_record(metadata)
    inferred_type = "bug" if (
        item.get("type") == "bug" or isinstance(metadata, dict) and isinstance(metadata.get("Bug"), dict)
    ) else "requirement"
    source_fields = metadata.get("source_fields") if isinstance(metadata, dict) else {}
    schema = metadata.get("feishu_schema") if isinstance(metadata, dict) else {}
    display_fields = {}
    if isinstance(source_fields, dict) and isinstance(schema, dict):
        display_fields = {
            str(field_name): source_fields.get(field_name)
            for field_name in schema.get("display_fields") or []
            if source_fields.get(field_name) not in (None, "", [], {})
        }
    return {
        "key": item.get("key", ""),
        "spec": item.get("spec", ""),
        "id": item.get("id", ""),
        "display_id": _display_value(record, "business_id") or item.get("id", ""),
        "type": inferred_type,
        "title": item.get("title", ""),
        "source": item.get("source", "tapd"),
        "status": _display_value(record, "status_name", "status"),
        "priority": _display_value(record, "priority_label", "priority"),
        "severity": _display_value(record, "severity_label", "severity"),
        "owner": _display_value(record, "current_owner", "owner", "de", "developer", "fixer"),
        "reporter": _display_value(record, "reporter", "creator"),
        "iteration": _display_value(record, "iteration_name", "iteration_id"),
        "module": _display_value(record, "module_name", "module"),
        "updated_at": _display_value(record, "modified", "lastmodify", "updated"),
        "source_url": _display_value(record, "source_url"),
        "description_excerpt": _plain_excerpt(item.get("description")),
        "display_fields": display_fields,
    }


def _resolve_items(source, item_specs: list[str]) -> list[WorkItem]:
    if not item_specs:
        raise ValueError("item_specs must contain at least one story:<id> or bug:<id>")
    selected: list[WorkItem] = []
    for spec in item_specs:
        kind, separator, item_id = spec.partition(":")
        if not separator:
            kind, item_id = "story", kind
        kind = kind.strip().lower()
        item_id = item_id.strip()
        if kind not in {"story", "bug"} or not item_id:
            raise ValueError(f"Invalid item spec: {spec}; use story:<id> or bug:<id>")
        if hasattr(source, "get_by_id_with_type"):
            selected.append(source.get_by_id_with_type(item_id, item_type=kind))
        else:
            selected.append(source.get_by_id(item_id))
    return selected


def _default_branch(item_specs: list[str], prefix: str) -> str:
    ids = [spec.partition(":")[2] or spec for spec in item_specs]
    safe_ids = ["".join(ch.lower() if ch.isalnum() else "-" for ch in item_id).strip("-") for item_id in ids]
    suffix = safe_ids[0] if len(safe_ids) == 1 else f"batch-{safe_ids[0]}-{len(safe_ids)}"
    return f"{prefix}/{suffix}"[:120]


def _record_payload(service: WorkflowService, run_id: str, include_report: bool = False) -> dict[str, Any]:
    record = service.runs.require(run_id)
    result: dict[str, Any] = {
        "run_id": record.run_id,
        "status": record.status,
        "work_items": record.work_items,
        "execution_mode": record.execution_mode,
        "engine": record.engine,
        "model": record.model,
        "engine_session_id": record.engine_session_id,
        "project_id": record.project_id,
        "project_memory_revision": record.project_memory_revision,
        "project_memory_source_sha": record.project_memory_source_sha,
        "repo_path": record.repo_path,
        "base_branch": record.base_branch,
        "work_branch": record.work_branch,
        "branch_mode": record.branch_mode,
        "push_locked_until_approval": record.status not in {"committing", "pushing", "completed"},
        "changed_files": record.changed_files,
        "task_brief": record.task_brief,
        "test_result": record.test_result,
        "finalization_count": record.verification_count,
        "verification_count": record.verification_count,
        "preparation_stage": record.preparation_stage,
        "sync_before_start": record.sync_before_start,
        "report_path": record.report_path,
        "commit_sha": record.commit_sha,
        "error": record.error,
    }
    if record.status == "completed":
        result["published_target"] = f"{record.remote_name}/{record.push_branch}"
    if record.status == "preparing":
        result["next_action"] = (
            "Repository preparation is still in progress. Do not create another task session; query this run again."
        )
    elif record.status == "waiting_approval":
        result["next_action"] = (
            "Req2Code 审核界面应已自动打开。不要在聊天中重复粘贴整份报告；明确当前没有提交或推送，"
            "然后停止并等待用户在审核界面中操作。发布分支只在审核通过后的第二次确认中显示。"
        )
    elif record.status == "developing":
        result["next_action"] = (
            "Implement the task brief in this repository, run and record relevant tests, then call "
            "finalize_development_run."
        )
    elif record.status == "changes_requested":
        result["next_action"] = (
            "Fix the reported problem, rerun relevant tests, then call finalize_development_run again."
        )
    if include_report and record.report_path and Path(record.report_path).is_file():
        result["report"] = Path(record.report_path).read_text(encoding="utf-8")
    return result


def _review_ui_payload(service: WorkflowService, run_id: str) -> dict[str, Any]:
    record = service.ensure_publish_nonce(run_id)
    work_items = []
    for item in record.work_items:
        description = html.unescape(re.sub(r"<[^>]+>", "\n", str(item.get("description") or "")))
        description = re.sub(r"[ \t]+", " ", description)
        description = re.sub(r"\n\s*\n+", "\n\n", description).strip()
        work_items.append({**item, "description": description})
    return {
        "run_id": record.run_id,
        "status": record.status,
        "work_items": work_items,
        "item_results": record.item_results,
        "implementation_plan": record.analysis,
        "implementation_summary": record.development,
        "changed_files": record.changed_files,
        "test_result": dict(record.test_result or {}),
        "verification_count": record.verification_count,
        "report_path": record.report_path,
        "diff_hash": record.diff_hash,
        "work_branch": record.work_branch,
        "planned_publication_target": f"{record.remote_name}/{record.push_branch}",
        "protected_branch_warning": record.push_branch.strip().lower() in {"main", "master"},
        "push_locked": record.status not in {"committing", "pushing", "completed"},
        "publish_nonce": record.publish_nonce,
        "commit_sha": record.commit_sha,
        "error": record.error,
        "approval_comment": record.approval_comment,
    }


def _development_review_result(service: WorkflowService, run_id: str) -> CallToolResult:
    payload = _review_ui_payload(service, run_id)
    waiting = payload["status"] == "waiting_approval"
    summary = {
        "run_id": payload["run_id"],
        "status": payload["status"],
        "work_item_count": len(payload["work_items"]),
        "changed_file_count": len(payload["changed_files"]),
        "tests_passed": bool(payload["test_result"].get("passed")),
        "push_locked": payload["push_locked"],
        "ui_state": "waiting_for_human_review" if waiting else "not_ready_for_approval",
        "next_action": (
            "停止并等待用户在 Req2Code 审核界面中操作；不要提交、推送或在聊天中重复整份报告。"
            if waiting
            else "根据界面和工具结果继续修复，重新测试后再次调用 finalize_development_run。"
        ),
    }
    message = (
        "开发与测试结果已固化，中文审核界面已打开。当前没有提交或推送；请等待用户审核。"
        if waiting
        else f"本次收尾状态为 {payload['status']}，尚未进入人工发布审核。"
    )
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        structuredContent=summary,
        _meta={DEVELOPMENT_REVIEW_META_KEY: payload},
    )


def _selection_store(cfg) -> WorkItemSelectionStore:
    return WorkItemSelectionStore(cfg.system.state_dir)


def _analysis_store(cfg) -> FeishuTableAnalysisStore:
    return FeishuTableAnalysisStore(cfg.system.state_dir)


def _normalize_selection_request(item_type: str, limit: int) -> tuple[str, int]:
    normalized = (item_type or "all").strip().lower()
    if normalized not in {"all", "story", "bug"}:
        raise ValueError("item_type must be all, story, or bug")
    normalized_limit = int(limit)
    if not 1 <= normalized_limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    return normalized, normalized_limit


def _launcher_payload(cfg, item_type: str = "all", limit: int = 200) -> dict[str, Any]:
    normalized_type, normalized_limit = _normalize_selection_request(item_type, limit)
    profiles = [source_profile_summary(profile) for profile in cfg.source_profiles]
    return {
        "ui_state": "choose_source_profile" if profiles else "configuration_required",
        "profiles": profiles,
        "profile_count": len(profiles),
        "providers": [
            {"id": "tapd", "label": "TAPD", "description": "读取真实需求和缺陷"},
            {"id": "feishu", "label": "飞书", "description": "读取文档表格、标题段落和多维表格"},
            {"id": "mock", "label": "Mock", "description": "本地演示，无需凭据"},
        ],
        "item_type": normalized_type,
        "limit": normalized_limit,
    }


def _apply_feishu_analysis(cfg, source, profile_id: str, analysis_id: str):
    if not analysis_id:
        return source
    analysis = _analysis_store(cfg).require(analysis_id)
    if analysis.profile_id != profile_id:
        raise ValueError("飞书字段分析与当前配置不匹配")
    if analysis.status != "completed":
        raise ValueError("飞书字段分析尚未完成")
    if not isinstance(source, FeishuConnector):
        raise ValueError("飞书字段分析只能用于飞书配置")
    source.schema_analysis = {"analysis_id": analysis.analysis_id, **analysis.mapping}
    return source


def _create_profile_selection(
    cfg,
    profile_id: str,
    item_type: str,
    limit: int,
    analysis_id: str = "",
) -> WorkItemSelection:
    normalized_type, normalized_limit = _normalize_selection_request(item_type, limit)
    profile = require_source_profile(cfg, profile_id)
    source = _apply_feishu_analysis(
        cfg,
        get_source_connector(cfg, profile_id=profile.id),
        profile.id,
        analysis_id,
    )
    items = [_item_payload(item) for item in _fetch_work_items(source, normalized_type, normalized_limit)]
    return _selection_store(cfg).create(
        items,
        source_profile_id=profile.id,
        source_profile_name=profile.name,
        source=profile.source,
        source_analysis_id=analysis_id,
    )


def _validate_source_profile_connection(cfg, profile) -> None:
    if profile.source == "mock":
        return
    profile_cfg = config_for_source_profile(cfg, profile)
    source = get_source_connector(profile_cfg)
    try:
        if hasattr(source, "validate"):
            source.validate()
            return
        # Selection reads both endpoints, so validate both before persisting a
        # profile and surface a bounded connector error without credentials.
        list(source.fetch_latest_by_type(limit=1, item_type="story"))
        list(source.fetch_latest_by_type(limit=1, item_type="bug"))
    except Exception as exc:
        label = "飞书" if profile.source == "feishu" else "TAPD"
        raise ValueError(f"{label} 连接验证失败：{exc}") from exc


def _fetch_work_items(source, item_type: str, limit: int) -> list[WorkItem]:
    normalized, limit = _normalize_selection_request(item_type, limit)
    # Fetch a broad server-side candidate window before excluding terminal
    # items. Otherwise a page filled with old resolved bugs can hide newer
    # actionable work even though the selector itself has room for it.
    fetch_limit = 200
    if normalized == "all" and hasattr(source, "fetch_latest_all"):
        candidates = list(source.fetch_latest_all(limit=fetch_limit))
    elif normalized in {"story", "bug"} and hasattr(source, "fetch_latest_by_type"):
        candidates = list(source.fetch_latest_by_type(limit=fetch_limit, item_type=normalized))
    elif normalized in {"all", "story"}:
        candidates = list(source.fetch_latest(limit=fetch_limit))
    else:
        raise ValueError("item_type must be all, story, or bug")
    return [item for item in candidates if _is_selectable_item(item)][:limit]


def _selection_ui_payload(selection: WorkItemSelection) -> dict[str, Any]:
    selected = {key.upper() for key in selection.selected_keys}
    ui_items = [_selection_ui_item(item) for item in selection.items]
    return {
        "selection_id": selection.selection_id,
        "status": selection.status,
        "source_profile_id": selection.source_profile_id,
        "source_profile_name": selection.source_profile_name,
        "source": selection.source,
        "source_analysis_id": selection.source_analysis_id,
        # Keep the full description and source metadata server-side until the
        # human confirms. The selector only needs these compact display fields.
        "items": ui_items,
        "selected_keys": selection.selected_keys,
        "selected_specs": selection.selected_specs,
        "selected_items": [item for item in ui_items if str(item["key"]).upper() in selected],
        "text_fallback": "Reply with one or more short keys, for example: B0151,S0102.",
    }


def _selection_summary_payload(selection: WorkItemSelection) -> dict[str, Any]:
    """Return only session state; unconfirmed candidates belong to the selector UI."""
    return {
        "selection_id": selection.selection_id,
        "status": selection.status,
        "item_count": len(selection.items),
        "source_profile_name": selection.source_profile_name,
        "source": selection.source,
        "source_analysis_id": selection.source_analysis_id,
        "ui_state": "awaiting_user_selection" if selection.status == "open" else "selection_confirmed",
    }


def _confirmed_selection_payload(selection: WorkItemSelection) -> dict[str, Any]:
    selected = {key.upper() for key in selection.selected_keys}
    selected_items: list[dict[str, Any]] = []
    for item in selection.items:
        if str(item["key"]).upper() not in selected:
            continue
        agent_item = _selection_ui_item(item)
        agent_item["description"] = item.get("description", "")
        metadata = item.get("metadata")
        raw_fields = metadata.get("source_fields") if isinstance(metadata, dict) else None
        source_fields = _nonempty_source_value(raw_fields or _source_record(metadata))
        agent_item["source_fields"] = source_fields
        if item.get("source") == "tapd":
            agent_item["tapd_fields"] = source_fields
        schema = metadata.get("feishu_schema") if isinstance(metadata, dict) else None
        if isinstance(schema, dict) and schema:
            agent_item["analysis_notes"] = list(schema.get("notes") or [])
            agent_item["field_analysis_id"] = str(schema.get("analysis_id") or "")
        selected_items.append(agent_item)
    return {
        **_selection_summary_payload(selection),
        "selected_keys": selection.selected_keys,
        "selected_specs": selection.selected_specs,
        # Give the coding agent the complete description and relevant source
        # fields without injecting hundreds of empty custom-field columns.
        "selected_items": selected_items,
    }


def _development_handoff_prompt(result: dict[str, Any]) -> str:
    """Build the self-contained message the selector sends to the coding agent."""
    selected_items = result.get("selected_items") or []
    selected_keys = result.get("selected_keys") or []
    return "\n".join(
        [
            "Req2Code 已确认开发任务。",
            f"selection_id={result.get('selection_id', '')}",
            f"selected_keys={','.join(str(key) for key in selected_keys)}",
            "selected_items=" + json.dumps(selected_items, ensure_ascii=False, separators=(",", ":")),
            "以上 selected_items 是已由用户确认的工作项完整数据，仅用于确定开发和测试范围。",
            "请立即继续当前 req2code-workflow。除非用户在打开选择器前明确指定了其他选项，否则使用当前代码项目根目录、保持当前已检出分支且不执行 pull。",
            "调用 prepare_development_run 一次并传入 selection_id，严格执行返回的完整 task_brief：实现全部已选工作项，补充或修改测试，运行并修复相关检查，然后调用 finalize_development_run 生成审核报告。",
            "完成后必须停在 waiting_approval，等待人工审核；未经明确批准不得提交或推送。",
        ]
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=False,
    meta={
        "ui": {"resourceUri": WORK_ITEM_SELECTOR_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": WORK_ITEM_SELECTOR_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "正在打开 Req2Code…",
        "openai/toolInvocation/invoked": "Req2Code 已打开",
    },
)
def render_req2code_launcher(item_type: str = "all", limit: int = 200) -> CallToolResult:
    """Open the private configuration/profile/work-item wizard without requiring prior setup."""
    cfg = ConfigManager().load()
    launcher = _launcher_payload(cfg, item_type=item_type, limit=limit)
    summary = {
        "ui_state": launcher["ui_state"],
        "profile_count": launcher["profile_count"],
        "next_action": "Wait for the human to configure/select a source and confirm work items in the UI.",
    }
    return CallToolResult(
        content=[TextContent(type="text", text="Req2Code 已打开。请等待用户在界面中完成配置和工作项选择。")],
        structuredContent=summary,
        _meta={WORKFLOW_LAUNCHER_META_KEY: launcher},
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def get_req2code_launcher_for_ui(item_type: str = "all", limit: int = 200) -> CallToolResult:
    """Hydrate source profiles for the mounted UI without exposing them to the coding model."""
    cfg = ConfigManager().load()
    launcher = _launcher_payload(cfg, item_type=item_type, limit=limit)
    return CallToolResult(
        content=[TextContent(type="text", text="Req2Code 配置档案已发送到本地界面。")],
        structuredContent={"ui_state": launcher["ui_state"], "profile_count": launcher["profile_count"]},
        _meta={WORKFLOW_LAUNCHER_META_KEY: launcher},
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def inspect_feishu_bitable_for_ui(
    document_url: str,
    profile_id: str = "",
    app_id: str = "",
    app_secret: str = "",
    table_id: str = "",
    view_id: str = "",
) -> dict[str, Any]:
    """List Bitable tables/views for the private configuration component."""
    manager = ConfigManager()
    cfg = manager.load()
    existing = None
    if profile_id:
        existing = next((profile for profile in cfg.source_profiles if profile.id == profile_id), None)
        if existing is None:
            raise KeyError(f"未找到需要检查的配置：{profile_id}")
        if existing.source != "feishu":
            raise ValueError("只能检查飞书配置")
    profile = build_source_profile(
        profile_id=profile_id,
        profile_name=existing.name if existing else "飞书多维表格检查",
        source="feishu",
        existing=existing,
        auth_mode="tenant",
        app_id=app_id,
        app_secret=app_secret,
        document_url=document_url,
        resource_type="auto",
        table_id=table_id,
        view_id=view_id,
    )
    source = get_source_connector(config_for_source_profile(cfg, profile))
    if not isinstance(source, FeishuConnector):
        raise RuntimeError("未能创建飞书连接器")
    result = source.inspect_bitable(table_id=table_id, view_id=view_id)
    return {"ui_state": "feishu_bitable_inspected", **result}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def create_feishu_table_analysis_for_ui(profile_id: str, sample_limit: int = 60) -> dict[str, Any]:
    """Create a private schema-analysis request after explicit human action in the UI."""
    cfg = ConfigManager().load()
    profile = require_source_profile(cfg, profile_id)
    if profile.source != "feishu" or not profile.feishu:
        raise ValueError("AI 字段分析只适用于飞书配置")
    bounded_limit = max(5, min(int(sample_limit), 100))
    source = get_source_connector(cfg, profile_id=profile.id)
    if not isinstance(source, FeishuConnector):
        raise RuntimeError("未能创建飞书连接器")
    inspection = source.inspect_bitable(table_id=profile.feishu.table_id, view_id=profile.feishu.view_id)
    table_id = str(inspection.get("selected_table_id") or profile.feishu.table_id)
    view_id = str(inspection.get("selected_view_id") or profile.feishu.view_id)
    field_definitions = source.bitable_field_definitions(table_id=table_id)
    defined_field_names = [
        str(definition.get("field_name") or "").strip()
        for definition in field_definitions
        if str(definition.get("field_name") or "").strip()
    ]
    _validate_work_item_table_schema(
        defined_field_names,
        table_name=str(inspection.get("selected_table_name") or ""),
        available_tables=inspection.get("tables") if isinstance(inspection.get("tables"), list) else [],
    )
    # Full records remain local. The agent only receives schema, configured
    # choices, and a bounded set of short sample values.
    items = list(source.fetch_latest_all(limit=bounded_limit))
    field_names: list[str] = []
    field_samples: dict[str, list[str]] = {}
    for item in items:
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        fields = metadata.get("source_fields") if isinstance(metadata.get("source_fields"), dict) else {}
        resource = metadata.get("feishu") if isinstance(metadata.get("feishu"), dict) else {}
        table_id = str(resource.get("table_id") or table_id)
        view_id = str(resource.get("view_id") or view_id)
        for field_name, value in fields.items():
            name = str(field_name).strip()
            text = _plain_excerpt(value, limit=180)
            if not name:
                continue
            if name not in field_names:
                field_names.append(name)
            samples = field_samples.setdefault(name, [])
            if text and text not in samples and len(samples) < 6:
                samples.append(text)
    # The field-definition endpoint includes columns and configured select
    # choices that may not occur in the bounded record sample. Keep them in
    # the authorized schema so the agent can still map and classify them.
    for definition in field_definitions:
        name = str(definition.get("field_name") or "").strip()
        if name and name not in field_names:
            field_names.append(name)
            field_samples[name] = []
    analysis = _analysis_store(cfg).create(
        profile_id=profile.id,
        profile_name=profile.name,
        table_id=table_id,
        view_id=view_id,
        field_names=field_names,
        field_samples=field_samples,
        field_definitions=field_definitions,
    )
    return {
        "ui_state": "awaiting_feishu_schema_analysis",
        "analysis_id": analysis.analysis_id,
        "field_count": len(analysis.field_names),
        "sampled_record_count": len(items),
        "message": "字段名和样例值已准备好，等待当前代码智能体返回结构化分析。",
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def get_feishu_table_analysis_for_ui(analysis_id: str) -> dict[str, Any]:
    """Poll schema-analysis state from the private launcher component."""
    cfg = ConfigManager().load()
    analysis = _analysis_store(cfg).require(analysis_id)
    return {
        "ui_state": "feishu_schema_analysis_ready" if analysis.status == "completed" else "awaiting_feishu_schema_analysis",
        "analysis_id": analysis.analysis_id,
        "status": analysis.status,
        "mapping": analysis.mapping if analysis.status == "completed" else {},
        "message": "字段分析已完成。" if analysis.status == "completed" else "等待当前代码智能体分析字段…",
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def get_feishu_table_analysis_task(analysis_id: str) -> dict[str, Any]:
    """Load one explicitly authorized Feishu schema-analysis task for the current coding agent."""
    cfg = ConfigManager().load()
    analysis = _analysis_store(cfg).require(analysis_id)
    if analysis.status != "awaiting_agent":
        raise ValueError("飞书字段分析任务已经完成，请勿重复分析")
    return {
        "analysis_id": analysis.analysis_id,
        "status": analysis.status,
        "analysis_prompt": build_analysis_prompt(analysis),
        "next_action": "Analyze this schema and call submit_feishu_table_analysis exactly once. Do not repeat samples in chat.",
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    structured_output=False,
    meta={
        "ui": {"resourceUri": WORK_ITEM_SELECTOR_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": WORK_ITEM_SELECTOR_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "正在分析飞书字段…",
        "openai/toolInvocation/invoked": "字段分析完成，正在打开工作项选择器",
    },
)
def submit_feishu_table_analysis(
    analysis_id: str,
    title_field: str,
    description_fields: list[str] | None = None,
    id_field: str = "",
    type_field: str = "",
    status_field: str = "",
    priority_field: str = "",
    severity_field: str = "",
    owner_field: str = "",
    reporter_field: str = "",
    acceptance_field: str = "",
    updated_field: str = "",
    bug_values: list[str] | None = None,
    requirement_values: list[str] | None = None,
    active_statuses: list[str] | None = None,
    terminal_statuses: list[str] | None = None,
    display_fields: list[str] | None = None,
    notes: list[str] | None = None,
) -> CallToolResult:
    """Return the coding agent's JSON schema interpretation to Req2Code."""
    cfg = ConfigManager().load()
    analysis = _analysis_store(cfg).complete(
        analysis_id,
        {
            "id_field": id_field,
            "title_field": title_field,
            "description_fields": description_fields or [],
            "type_field": type_field,
            "status_field": status_field,
            "priority_field": priority_field,
            "severity_field": severity_field,
            "owner_field": owner_field,
            "reporter_field": reporter_field,
            "acceptance_field": acceptance_field,
            "updated_field": updated_field,
            "bug_values": bug_values or [],
            "requirement_values": requirement_values or [],
            "active_statuses": active_statuses or [],
            "terminal_statuses": terminal_statuses or [],
            "display_fields": display_fields or [],
            "notes": notes or [],
        },
    )
    summary = {
        "ui_state": "feishu_schema_analysis_ready",
        "analysis_id": analysis.analysis_id,
        "status": analysis.status,
        "profile_id": analysis.profile_id,
        "message": "飞书字段分析已完成，工作项选择器将在当前对话位置打开。",
    }
    return CallToolResult(
        content=[TextContent(type="text", text="飞书字段分析已完成。请等待用户在下方选择工作项，不要在聊天中复述表格数据。")],
        structuredContent=summary,
        _meta={
            FEISHU_ANALYSIS_META_KEY: {
                "analysis_id": analysis.analysis_id,
                "profile_id": analysis.profile_id,
                "profile_name": analysis.profile_name,
                "status": analysis.status,
            }
        },
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def save_source_profile_for_ui(
    profile_name: str,
    source: str,
    profile_id: str = "",
    auth_mode: str = "",
    base_url: str = "https://api.tapd.cn",
    workspace_id: str = "",
    app_id: str = "",
    app_secret: str = "",
    document_url: str = "",
    resource_type: str = "auto",
    parse_mode: str = "auto",
    table_id: str = "",
    view_id: str = "",
    sheet_id: str = "",
    feishu_base_url: str = "https://open.feishu.cn",
    feishu_id_field: str = "",
    feishu_title_field: str = "",
    feishu_description_field: str = "",
    feishu_type_field: str = "",
    feishu_status_field: str = "",
    feishu_priority_field: str = "",
    feishu_severity_field: str = "",
    feishu_owner_field: str = "",
    feishu_reporter_field: str = "",
    feishu_acceptance_field: str = "",
    feishu_updated_field: str = "",
) -> dict[str, Any]:
    """Validate and save a named source profile from the app-only configuration form."""
    manager = ConfigManager()
    cfg = manager.load()
    existing = None
    if profile_id:
        existing = next((profile for profile in cfg.source_profiles if profile.id == profile_id), None)
        if existing is None:
            raise KeyError(f"未找到需要更新的配置：{profile_id}")
    field_mapping = None
    if source.strip().lower() == "feishu":
        field_mapping = FeishuFieldMappingConfig(
            id_field=feishu_id_field,
            title_field=feishu_title_field,
            description_field=feishu_description_field,
            type_field=feishu_type_field,
            status_field=feishu_status_field,
            priority_field=feishu_priority_field,
            severity_field=feishu_severity_field,
            owner_field=feishu_owner_field,
            reporter_field=feishu_reporter_field,
            acceptance_field=feishu_acceptance_field,
            updated_field=feishu_updated_field,
        )
    profile = build_source_profile(
        profile_id=profile_id,
        profile_name=profile_name,
        source=source,
        existing=existing,
        auth_mode=auth_mode,
        base_url=base_url,
        workspace_id=workspace_id,
        app_id=app_id,
        app_secret=app_secret,
        document_url=document_url,
        resource_type=resource_type,
        parse_mode=parse_mode,
        table_id=table_id,
        view_id=view_id,
        sheet_id=sheet_id,
        feishu_base_url=feishu_base_url,
        field_mapping=field_mapping,
    )
    _validate_source_profile_connection(cfg, profile)
    updated = save_source_profile(manager, profile)
    return {
        "ui_state": "source_profile_saved",
        "message": "连接验证成功，配置已保存在本机。",
        "profile": source_profile_summary(profile),
        "profile_count": len(updated.source_profiles),
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def delete_source_profile_for_ui(profile_id: str) -> dict[str, Any]:
    """Delete one named local source profile from the private launcher UI."""
    manager = ConfigManager()
    updated = delete_source_profile(manager, profile_id)
    return {
        "ui_state": "source_profile_deleted",
        "message": "配置已从本机删除。",
        "profile_count": len(updated.source_profiles),
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def create_work_item_selection_for_ui(
    profile_id: str,
    item_type: str = "all",
    limit: int = 200,
    analysis_id: str = "",
) -> CallToolResult:
    """Fetch candidates with an explicit source profile and deliver them only to the mounted UI."""
    cfg = ConfigManager().load()
    selection = _create_profile_selection(cfg, profile_id, item_type, limit, analysis_id=analysis_id)
    return CallToolResult(
        content=[TextContent(type="text", text="候选工作项已发送到本地选择器。")],
        structuredContent=_selection_summary_payload(selection),
        _meta={WORK_ITEM_SELECTOR_META_KEY: _selection_ui_payload(selection)},
    )


@mcp.tool()
def list_work_items(item_type: str = "all", limit: int = 20, profile_id: str = "") -> list[dict[str, Any]]:
    """List selectable requirements and defects from the configured source."""
    cfg = ConfigManager().load()
    source = get_source_connector(cfg, profile_id=profile_id) if profile_id else get_source_connector(cfg)
    items = _fetch_work_items(source, item_type, limit)
    return [_item_payload(item) for item in items]


@mcp.tool()
def create_work_item_selection(item_type: str = "all", limit: int = 20, profile_id: str = "") -> dict[str, Any]:
    """Create a selector session; unconfirmed candidate details are not returned to the model."""
    cfg = ConfigManager().load()
    if profile_id:
        selection = _create_profile_selection(cfg, profile_id, item_type, limit)
    else:
        source = get_source_connector(cfg)
        items = [_item_payload(item) for item in _fetch_work_items(source, item_type, limit)]
        selection = _selection_store(cfg).create(items, source=cfg.source)
    return {
        **_selection_summary_payload(selection),
        "next_action": (
            "Call render_work_item_selector with this selection_id, then wait for the human to confirm in the UI. "
            "Do not enumerate or infer candidate work items in chat."
        ),
    }


@mcp.tool(
    structured_output=False,
    meta={
        "ui": {"resourceUri": WORK_ITEM_SELECTOR_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": WORK_ITEM_SELECTOR_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "正在打开工作项选择器…",
        "openai/toolInvocation/invoked": "工作项选择器已打开",
    }
)
def render_work_item_selector(selection_id: str) -> CallToolResult:
    """Render candidates in the checkbox UI while exposing only session state to the model."""
    cfg = ConfigManager().load()
    selection = _selection_store(cfg).require(selection_id)
    summary = {
        **_selection_summary_payload(selection),
        "next_action": "Wait for the selector UI to send the human's confirmed selection. Do not print candidates.",
    }
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text="工作项选择器已打开。请等待用户在界面中确认；不要在对话中输出候选列表。",
            )
        ],
        structuredContent=summary,
        _meta={WORK_ITEM_SELECTOR_META_KEY: _selection_ui_payload(selection)},
    )


@mcp.tool(
    meta={
        "ui": {"visibility": ["app"]},
        "openai/visibility": "private",
        "openai/widgetAccessible": True,
    }
)
def get_work_item_selection_for_ui(selection_id: str) -> CallToolResult:
    """Return selector candidates to the mounted UI only; this tool is hidden from the model."""
    cfg = ConfigManager().load()
    selection = _selection_store(cfg).require(selection_id)
    return CallToolResult(
        content=[TextContent(type="text", text="选择器候选数据已发送到审核组件。")],
        structuredContent=_selection_summary_payload(selection),
        _meta={WORK_ITEM_SELECTOR_META_KEY: _selection_ui_payload(selection)},
    )


@mcp.tool(
    meta={
        "ui": {"visibility": ["app"]},
        "openai/visibility": "private",
        "openai/widgetAccessible": True,
    }
)
def confirm_work_item_selection(selection_id: str, selected_keys: list[str]) -> dict[str, Any]:
    """Persist the human-confirmed items and return only those items to the coding agent."""
    cfg = ConfigManager().load()
    selection = _selection_store(cfg).confirm(selection_id, selected_keys)
    result = _confirmed_selection_payload(selection)
    result["next_action"] = (
        "Continue immediately with the current coding project root, its currently checked-out branch, and no pull, "
        "unless the human already specified different repository, branch, or sync choices. Call "
        "prepare_development_run once with this selection_id, then follow its complete task_brief through "
        "implementation, tests, report generation, and the waiting_approval gate."
    )
    result["handoff_prompt"] = _development_handoff_prompt(result)
    return result


@mcp.resource(
    WORK_ITEM_SELECTOR_URI,
    name="Req2Code workflow launcher",
    title="Req2Code 配置与工作项选择器",
    description="Configure or choose a work-item source, then select one or more requirements and defects.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}}},
)
def work_item_selector_resource() -> str:
    return (Path(__file__).parent / "resources" / "work_item_selector.html").read_text(encoding="utf-8")


@mcp.resource(
    DEVELOPMENT_REVIEW_URI,
    name="Req2Code development review",
    title="Req2Code 开发与测试审核",
    description="Review every selected work item, its implementation, changes, tests, and gated publication.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}}},
)
def development_review_resource() -> str:
    return (Path(__file__).parent / "resources" / "development_review.html").read_text(encoding="utf-8")


@mcp.tool()
def get_work_item(item_id: str, item_type: str = "story", profile_id: str = "") -> dict[str, Any]:
    """Get one requirement or defect from the configured source, including its description."""
    cfg = ConfigManager().load()
    source = get_source_connector(cfg, profile_id=profile_id) if profile_id else get_source_connector(cfg)
    normalized = item_type.strip().lower()
    if normalized not in {"story", "bug"}:
        raise ValueError("item_type must be story or bug")
    item = (
        source.get_by_id_with_type(item_id, item_type=normalized)
        if hasattr(source, "get_by_id_with_type")
        else source.get_by_id(item_id)
    )
    return _item_payload(item)


def _prepare_development_run(
    item_specs: list[str] | None = None,
    selection_id: str = "",
    local_path: str = "",
    repo_url: str = "",
    base_branch: str = "",
    work_branch: str = "",
    push_branch: str = "",
    remote_name: str = "",
    agent_name: str = "current_agent",
    sync_before_start: bool = False,
) -> dict[str, Any]:
    cfg = ConfigManager().load()
    specs = list(item_specs or [])
    source_profile_id = ""
    source_analysis_id = ""
    if selection_id:
        selection = _selection_store(cfg).require(selection_id)
        if selection.status != "confirmed" or not selection.selected_specs:
            raise ValueError("Confirm the work-item selection before preparing a task")
        if specs and specs != selection.selected_specs:
            raise ValueError("Pass either selection_id or matching item_specs, not conflicting work items")
        specs = selection.selected_specs
        source_profile_id = selection.source_profile_id
        source_analysis_id = selection.source_analysis_id
    source = (
        get_source_connector(cfg, profile_id=source_profile_id)
        if source_profile_id
        else get_source_connector(cfg)
    )
    if source_analysis_id:
        source = _apply_feishu_analysis(cfg, source, source_profile_id, source_analysis_id)
    selected = _resolve_items(source, specs)
    if not local_path and not repo_url:
        local_path = "."
    service = WorkflowService(cfg)
    record = service.begin_agent_run(
        selected,
        RepositorySpec(
            local_path=local_path,
            repo_url=repo_url,
            remote_name=remote_name or cfg.git.remote_name,
            base_branch=base_branch,
            work_branch=work_branch,
            push_branch=push_branch,
            sync_before_start=sync_before_start,
        ),
        agent_name=agent_name,
    )
    return _record_payload(service, record.run_id)


@mcp.tool()
def prepare_development_run(
    item_specs: list[str] | None = None,
    selection_id: str = "",
    local_path: str = "",
    repo_url: str = "",
    base_branch: str = "",
    work_branch: str = "",
    push_branch: str = "",
    remote_name: str = "",
    agent_name: str = "current_agent",
    sync_before_start: bool = False,
) -> dict[str, Any]:
    """Prepare selected work items for the current coding agent; does not launch another agent CLI."""
    return _prepare_development_run(
        item_specs=item_specs,
        selection_id=selection_id,
        local_path=local_path,
        repo_url=repo_url,
        base_branch=base_branch,
        work_branch=work_branch,
        push_branch=push_branch,
        remote_name=remote_name,
        agent_name=agent_name,
        sync_before_start=sync_before_start,
    )


@mcp.tool()
def start_development_run(
    item_specs: list[str] | None = None,
    selection_id: str = "",
    local_path: str = "",
    repo_url: str = "",
    base_branch: str = "",
    work_branch: str = "",
    push_branch: str = "",
    remote_name: str = "",
    agent_name: str = "current_agent",
    sync_before_start: bool = False,
) -> dict[str, Any]:
    """Compatibility alias for prepare_development_run; it never launches a nested coding agent."""
    return _prepare_development_run(
        item_specs=item_specs,
        selection_id=selection_id,
        local_path=local_path,
        repo_url=repo_url,
        base_branch=base_branch,
        work_branch=work_branch,
        push_branch=push_branch,
        remote_name=remote_name,
        agent_name=agent_name,
        sync_before_start=sync_before_start,
    )


@mcp.tool(
    structured_output=False,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    meta={
        "ui": {"resourceUri": DEVELOPMENT_REVIEW_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": DEVELOPMENT_REVIEW_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "正在固化开发与测试结果…",
        "openai/toolInvocation/invoked": "开发审核界面已打开",
    },
)
def finalize_development_run(
    run_id: str,
    implementation_summary: str,
    implementation_plan: str = "",
    test_evidence: str = "",
    tests_passed: bool = True,
    coverage: float | None = None,
    rerun_configured_tests: bool = False,
    item_results: list[dict[str, Any]] | None = None,
) -> CallToolResult:
    """Save the current agent's development/test report, validate Git state, and wait for human approval.

    By default Req2Code trusts and records the current coding agent's test evidence instead of
    executing the configured test suite a second time. Set rerun_configured_tests only when a
    project policy or human explicitly requires an independent strict rerun.
    """
    service = WorkflowService(ConfigManager().load())
    record = service.finalize_agent_run(
        run_id,
        implementation_plan=implementation_plan,
        implementation_summary=implementation_summary,
        test_evidence=test_evidence,
        tests_passed=tests_passed,
        coverage=coverage,
        rerun_configured_tests=rerun_configured_tests,
        item_results=item_results,
    )
    return _development_review_result(service, record.run_id)


@mcp.tool(
    structured_output=False,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    meta={
        "ui": {"resourceUri": DEVELOPMENT_REVIEW_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": DEVELOPMENT_REVIEW_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "正在打开开发审核界面…",
        "openai/toolInvocation/invoked": "开发审核界面已打开",
    },
)
def render_development_review(run_id: str) -> CallToolResult:
    """Open the structured Chinese review UI for an existing development run."""
    service = WorkflowService(ConfigManager().load())
    return _development_review_result(service, run_id)


@mcp.tool(meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True})
def get_development_review_for_ui(run_id: str) -> CallToolResult:
    """Hydrate the mounted review component; hidden from the coding model."""
    service = WorkflowService(ConfigManager().load())
    payload = _review_ui_payload(service, run_id)
    return CallToolResult(
        content=[TextContent(type="text", text="开发审核数据已发送到审核组件。")],
        structuredContent={
            "run_id": payload["run_id"],
            "status": payload["status"],
            "ui_state": "review_data_ready",
        },
        _meta={DEVELOPMENT_REVIEW_META_KEY: payload},
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def publish_reviewed_run_for_ui(
    run_id: str,
    publish_nonce: str,
    confirmation: str,
    comment: str = "",
) -> dict[str, Any]:
    """Commit and push only from the review component's explicit second confirmation."""
    service = WorkflowService(ConfigManager().load())
    record = service.approve_and_publish_from_ui(run_id, publish_nonce, confirmation, comment)
    return {
        "run_id": record.run_id,
        "status": record.status,
        "commit_sha": record.commit_sha,
        "published_target": f"{record.remote_name}/{record.push_branch}",
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
def request_development_changes_for_ui(
    run_id: str,
    publish_nonce: str,
    comment: str = "",
) -> dict[str, Any]:
    """Return the run to changes_requested while keeping commit and push locked."""
    service = WorkflowService(ConfigManager().load())
    record = service.request_changes_from_ui(run_id, publish_nonce, comment)
    return {
        "run_id": record.run_id,
        "status": record.status,
        "comment": record.approval_comment,
        "push_locked": True,
    }


@mcp.tool()
def verify_development_run(
    run_id: str,
    implementation_summary: str,
    implementation_plan: str = "",
    test_evidence: str = "",
) -> dict[str, Any]:
    """Compatibility strict mode: rerun configured checks, report, and stop for human approval."""
    service = WorkflowService(ConfigManager().load())
    record = service.verify_agent_run(
        run_id,
        implementation_plan=implementation_plan,
        implementation_summary=implementation_summary,
        test_evidence=test_evidence,
    )
    return _record_payload(service, record.run_id, include_report=True)


@mcp.tool()
def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    """List recent Req2Code runs and their approval state."""
    service = WorkflowService(ConfigManager().load())
    return [_record_payload(service, record.run_id) for record in service.runs.list(limit=limit)]


@mcp.tool()
def get_run(run_id: str, include_report: bool = True) -> dict[str, Any]:
    """Get a run, Chinese report, approval URL, changes, tests, and post-approval planned push branch."""
    service = WorkflowService(ConfigManager().load())
    return _record_payload(service, run_id, include_report=include_report)


@mcp.tool()
def list_projects(limit: int = 50) -> list[dict[str, Any]]:
    """List repositories with Req2Code project memory and their analyzed Git revision."""
    service = WorkflowService(ConfigManager().load())
    return [project.__dict__ for project in service.projects.list(limit=limit)]


@mcp.tool()
def get_project_memory(project_id: str) -> dict[str, Any]:
    """Read generated project understanding documents; this tool cannot modify or publish code."""
    service = WorkflowService(ConfigManager().load())
    project = service.projects.require(project_id)
    return {"project": project.__dict__, "documents": service.projects.read_documents(project_id)}

def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
