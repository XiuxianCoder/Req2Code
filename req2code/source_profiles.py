from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from req2code.config import (
    AgentConfig,
    ConfigManager,
    FeishuFieldMappingConfig,
    FeishuSourceConfig,
    SourceProfileConfig,
    TapdSourceConfig,
)


SUPPORTED_SOURCES = {"tapd", "feishu", "mock"}
SUPPORTED_TAPD_AUTH_MODES = {"oauth2", "basic"}
SUPPORTED_FEISHU_AUTH_MODES = {"tenant"}
SUPPORTED_FEISHU_RESOURCE_TYPES = {"auto", "docx", "wiki", "bitable", "spreadsheet"}
SUPPORTED_FEISHU_PARSE_MODES = {"auto", "table_rows", "headings", "whole_document"}


def is_placeholder(value: str | None) -> bool:
    text = str(value or "").strip()
    return not text or "REPLACE_ME" in text


def tapd_configured(tapd: TapdSourceConfig | None) -> bool:
    return bool(
        tapd
        and tapd.auth_mode in SUPPORTED_TAPD_AUTH_MODES
        and all(not is_placeholder(value) for value in (tapd.app_id, tapd.app_secret, tapd.workspace_id))
    )


def feishu_configured(feishu: FeishuSourceConfig | None) -> bool:
    return bool(
        feishu
        and feishu.auth_mode in SUPPORTED_FEISHU_AUTH_MODES
        and all(not is_placeholder(value) for value in (feishu.app_id, feishu.app_secret, feishu.document_url))
    )


def _normalize_feishu_document_url(value: str) -> tuple[str, str, str, str, str]:
    raw = (value or "").strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    allowed_host = host == "feishu.cn" or host.endswith(".feishu.cn") or host == "larksuite.com" or host.endswith(".larksuite.com")
    if parsed.scheme != "https" or not allowed_host or parsed.username or parsed.password:
        raise ValueError("飞书文档链接必须是 feishu.cn 或 larksuite.com 的 HTTPS 地址")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("无法从飞书文档链接识别资源类型和 token")
    raw_type, token = parts[0].lower(), parts[1].strip()
    type_map = {"docx": "docx", "wiki": "wiki", "base": "bitable", "sheets": "spreadsheet"}
    resource_type = type_map.get(raw_type, "")
    if not resource_type or not token:
        raise ValueError("当前仅支持飞书 /docx/、/wiki/、/base/ 和 /sheets/ 链接")
    query = parse_qs(parsed.query)
    table_id = str((query.get("table") or [""])[0]).strip()
    view_id = str((query.get("view") or [""])[0]).strip()
    sheet_id = str((query.get("sheet") or [""])[0]).strip()
    return raw, resource_type, table_id, view_id, sheet_id


def _with_feishu_resource_selection(
    document_url: str,
    resource_type: str,
    *,
    table_id: str = "",
    view_id: str = "",
    sheet_id: str = "",
) -> str:
    """Keep the saved URL aligned with an explicit table, view, or sheet choice."""
    parsed = urlparse(document_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if resource_type == "bitable":
        if table_id:
            query["table"] = [table_id]
        else:
            query.pop("table", None)
        if view_id:
            query["view"] = [view_id]
        else:
            query.pop("view", None)
    elif resource_type == "spreadsheet":
        if sheet_id:
            query["sheet"] = [sheet_id]
        else:
            query.pop("sheet", None)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _workspace_from_tapd_url(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.netloc.lower() not in {"tapd.cn", "www.tapd.cn"}:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "tapd_fe" and parts[1].isdigit():
        return parts[1]
    if parts and parts[0].isdigit():
        return parts[0]
    return ""


def _normalize_tapd_location(base_url: str, workspace_id: str) -> tuple[str, str]:
    raw_base = (base_url or "https://api.tapd.cn").strip()
    raw_workspace = (workspace_id or "").strip()
    detected = _workspace_from_tapd_url(raw_base) or _workspace_from_tapd_url(raw_workspace)
    if detected:
        raw_base = "https://api.tapd.cn"
        raw_workspace = detected
    parsed = urlparse(raw_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TAPD API 地址必须是有效的 http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("TAPD API 地址不能包含用户名或密码")
    if not raw_workspace:
        raise ValueError("TAPD workspace_id 不能为空")
    return raw_base.rstrip("/"), raw_workspace


def build_source_profile(
    *,
    profile_name: str,
    source: str,
    profile_id: str = "",
    existing: SourceProfileConfig | None = None,
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
    field_mapping: FeishuFieldMappingConfig | None = None,
) -> SourceProfileConfig:
    name = (profile_name or "").strip()
    if not name:
        raise ValueError("配置名称不能为空")
    if len(name) > 80:
        raise ValueError("配置名称不能超过 80 个字符")

    normalized_source = (source or "").strip().lower()
    if normalized_source not in SUPPORTED_SOURCES:
        raise ValueError(f"暂不支持数据平台：{source}")

    resolved_id = (profile_id or (existing.id if existing else "") or uuid.uuid4().hex[:12]).strip()
    if not resolved_id or any(not (ch.isalnum() or ch in {"-", "_"}) for ch in resolved_id):
        raise ValueError("配置 ID 无效")

    if normalized_source == "mock":
        return SourceProfileConfig(id=resolved_id, name=name, source="mock", tapd=None, feishu=None)

    if normalized_source == "feishu":
        normalized_auth = (auth_mode or "tenant").strip().lower()
        if normalized_auth not in SUPPORTED_FEISHU_AUTH_MODES:
            raise ValueError("飞书认证方式仅支持 tenant（自建应用身份）")
        existing_feishu = existing.feishu if existing and existing.source == "feishu" else None
        resolved_app_id = (app_id or (existing_feishu.app_id if existing_feishu else "")).strip()
        resolved_secret = app_secret or (existing_feishu.app_secret if existing_feishu else "")
        if is_placeholder(resolved_app_id) or is_placeholder(resolved_secret):
            raise ValueError("飞书 App ID/App Secret 不能为空")
        resolved_document_url = document_url or (existing_feishu.document_url if existing_feishu else "")
        normalized_url, detected_type, detected_table, detected_view, detected_sheet = _normalize_feishu_document_url(
            resolved_document_url
        )
        normalized_resource_type = (resource_type or "auto").strip().lower()
        if normalized_resource_type not in SUPPORTED_FEISHU_RESOURCE_TYPES:
            raise ValueError("飞书资源类型必须是 auto、docx、wiki、bitable 或 spreadsheet")
        if normalized_resource_type != "auto" and normalized_resource_type != detected_type and detected_type != "wiki":
            raise ValueError("选择的飞书资源类型与文档链接不匹配")
        normalized_parse_mode = (parse_mode or "auto").strip().lower()
        if normalized_parse_mode not in SUPPORTED_FEISHU_PARSE_MODES:
            raise ValueError("飞书解析方式必须是 auto、table_rows、headings 或 whole_document")
        parsed_base = urlparse((feishu_base_url or "https://open.feishu.cn").strip())
        if parsed_base.scheme != "https" or not parsed_base.netloc or parsed_base.username or parsed_base.password:
            raise ValueError("飞书 API 地址必须是有效的 HTTPS URL")
        feishu = existing_feishu.model_copy(deep=True) if existing_feishu else FeishuSourceConfig()
        feishu.enabled = True
        feishu.base_url = f"{parsed_base.scheme}://{parsed_base.netloc}".rstrip("/")
        feishu.auth_mode = normalized_auth
        feishu.app_id = resolved_app_id
        feishu.app_secret = resolved_secret
        explicit_table = (table_id or "").strip()
        resolved_table = (explicit_table or detected_table or (existing_feishu.table_id if existing_feishu else "")).strip()
        explicit_view = (view_id or "").strip()
        if explicit_table and explicit_table != detected_table:
            # A view belongs to one table. Do not carry the old URL's view to
            # a different table selected from the same Bitable application.
            resolved_view = explicit_view
        else:
            resolved_view = (
                explicit_view or detected_view or (existing_feishu.view_id if existing_feishu else "")
            ).strip()
        resolved_sheet = (
            (sheet_id or "").strip() or detected_sheet or (existing_feishu.sheet_id if existing_feishu else "")
        ).strip()
        feishu.document_url = _with_feishu_resource_selection(
            normalized_url,
            detected_type,
            table_id=resolved_table,
            view_id=resolved_view,
            sheet_id=resolved_sheet,
        )
        feishu.resource_type = normalized_resource_type
        feishu.parse_mode = normalized_parse_mode
        feishu.table_id = resolved_table
        feishu.view_id = resolved_view
        feishu.sheet_id = resolved_sheet
        if field_mapping is not None:
            feishu.field_mapping = field_mapping.model_copy(deep=True)
        return SourceProfileConfig(id=resolved_id, name=name, source="feishu", tapd=None, feishu=feishu)

    normalized_auth = (auth_mode or "oauth2").strip().lower()
    if normalized_auth not in SUPPORTED_TAPD_AUTH_MODES:
        raise ValueError("TAPD 认证方式必须是 oauth2 或 basic")

    existing_tapd = existing.tapd if existing and existing.source == "tapd" else None
    can_reuse_credentials = bool(existing_tapd and existing_tapd.auth_mode == normalized_auth)
    resolved_app_id = (app_id or (existing_tapd.app_id if can_reuse_credentials else "")).strip()
    resolved_secret = app_secret or (existing_tapd.app_secret if can_reuse_credentials else "")
    if is_placeholder(resolved_app_id) or is_placeholder(resolved_secret):
        account_label = "app_id/app_secret" if normalized_auth == "oauth2" else "API 账号/API 口令"
        raise ValueError(f"TAPD {account_label} 不能为空")

    resolved_base, resolved_workspace = _normalize_tapd_location(base_url, workspace_id)
    tapd = existing_tapd.model_copy(deep=True) if existing_tapd else TapdSourceConfig()
    tapd.enabled = True
    tapd.base_url = resolved_base
    tapd.workspace_id = resolved_workspace
    tapd.auth_mode = normalized_auth
    tapd.app_id = resolved_app_id
    tapd.app_secret = resolved_secret
    return SourceProfileConfig(id=resolved_id, name=name, source="tapd", tapd=tapd, feishu=None)


def source_profile_summary(profile: SourceProfileConfig) -> dict[str, object]:
    tapd = profile.tapd
    feishu = profile.feishu
    detected_feishu_type = ""
    if feishu and feishu.document_url:
        try:
            _, detected_feishu_type, _, _, _ = _normalize_feishu_document_url(feishu.document_url)
        except ValueError:
            detected_feishu_type = ""
    source_labels = {"tapd": "TAPD", "feishu": "飞书", "mock": "Mock"}
    return {
        "id": profile.id,
        "name": profile.name,
        "source": profile.source,
        "source_label": source_labels.get(profile.source, profile.source),
        "base_url": tapd.base_url if tapd else "",
        "workspace_id": tapd.workspace_id if tapd else "",
        "auth_mode": tapd.auth_mode if tapd else (feishu.auth_mode if feishu else ""),
        "document_url": feishu.document_url if feishu else "",
        "resource_type": (
            detected_feishu_type if feishu and feishu.resource_type == "auto" else (feishu.resource_type if feishu else "")
        ),
        "parse_mode": feishu.parse_mode if feishu else "",
        "table_id": feishu.table_id if feishu else "",
        "view_id": feishu.view_id if feishu else "",
        "sheet_id": feishu.sheet_id if feishu else "",
        "field_mapping": feishu.field_mapping.model_dump() if feishu else {},
        "configured": profile.source == "mock" or tapd_configured(tapd) or feishu_configured(feishu),
    }


def require_source_profile(cfg: AgentConfig, profile_id: str) -> SourceProfileConfig:
    normalized = (profile_id or "").strip()
    for profile in cfg.source_profiles:
        if profile.id == normalized:
            if profile.source == "tapd" and not tapd_configured(profile.tapd):
                raise ValueError(f"TAPD 配置不完整：{profile.name}")
            if profile.source == "feishu" and not feishu_configured(profile.feishu):
                raise ValueError(f"飞书配置不完整：{profile.name}")
            return profile
    raise KeyError(f"未找到需求源配置：{profile_id}")


def config_for_source_profile(cfg: AgentConfig, profile: SourceProfileConfig) -> AgentConfig:
    resolved = cfg.model_copy(deep=True)
    resolved.source = profile.source
    if profile.source == "tapd":
        if not profile.tapd:
            raise ValueError(f"TAPD 配置不完整：{profile.name}")
        resolved.tapd = profile.tapd.model_copy(deep=True)
    elif profile.source == "feishu":
        if not profile.feishu:
            raise ValueError(f"飞书配置不完整：{profile.name}")
        resolved.feishu = profile.feishu.model_copy(deep=True)
    return resolved


def save_source_profile(manager: ConfigManager, profile: SourceProfileConfig) -> AgentConfig:
    cfg = manager.load()
    for current in cfg.source_profiles:
        if current.id != profile.id and current.name.casefold() == profile.name.casefold():
            raise ValueError(f"配置名称已存在：{profile.name}")

    replaced = False
    updated: list[SourceProfileConfig] = []
    for current in cfg.source_profiles:
        if current.id == profile.id:
            updated.append(profile)
            replaced = True
        else:
            updated.append(current)
    if not replaced:
        updated.append(profile)
    cfg.source_profiles = updated

    # Preserve existing CLI compatibility without using this mutable default
    # for UI selections. Every UI-created selection records an explicit profile ID.
    cfg.source = profile.source
    if profile.source == "tapd" and profile.tapd:
        cfg.tapd = profile.tapd.model_copy(deep=True)
    elif profile.source == "feishu" and profile.feishu:
        cfg.feishu = profile.feishu.model_copy(deep=True)
    manager.save(cfg)
    return cfg


def delete_source_profile(manager: ConfigManager, profile_id: str) -> AgentConfig:
    cfg = manager.load()
    normalized = (profile_id or "").strip()
    if not normalized or not any(profile.id == normalized for profile in cfg.source_profiles):
        raise KeyError(f"未找到需要删除的配置：{profile_id}")
    cfg.source_profiles = [profile for profile in cfg.source_profiles if profile.id != normalized]
    manager.save(cfg)
    return cfg


def sync_legacy_source_profile(cfg: AgentConfig, profile_name: str = "") -> None:
    """Expose CLI setup values to the UI profile chooser."""
    if cfg.source == "mock":
        profile = SourceProfileConfig(id="mock-default", name=profile_name or "Mock 演示", source="mock")
    elif cfg.source == "tapd" and tapd_configured(cfg.tapd):
        workspace = cfg.tapd.workspace_id.strip()
        safe_workspace = "".join(ch for ch in workspace if ch.isalnum() or ch in {"-", "_"})
        profile = SourceProfileConfig(
            id=f"tapd-{safe_workspace or 'default'}",
            name=profile_name or f"TAPD {workspace or '默认配置'}",
            source="tapd",
            tapd=cfg.tapd.model_copy(deep=True),
        )
    elif cfg.source == "feishu" and feishu_configured(cfg.feishu):
        parsed = urlparse(cfg.feishu.document_url)
        token = next((part for part in parsed.path.split("/") if part), "feishu")
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) > 1:
            token = path_parts[1]
        safe_token = "".join(ch for ch in token if ch.isalnum() or ch in {"-", "_"})[-32:]
        profile = SourceProfileConfig(
            id=f"feishu-{safe_token or 'default'}",
            name=profile_name or "飞书默认配置",
            source="feishu",
            feishu=cfg.feishu.model_copy(deep=True),
        )
    else:
        return

    for index, current in enumerate(cfg.source_profiles):
        if current.id == profile.id:
            cfg.source_profiles[index] = profile
            return
    cfg.source_profiles.append(profile)
