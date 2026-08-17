from __future__ import annotations

from req2code.config import AgentConfig
from req2code.connectors.base import SourceConnector
from req2code.connectors.feishu_connector import FeishuConnector
from req2code.connectors.mock_connector import MockConnector
from req2code.connectors.tapd_connector import TapdConnector
from req2code.source_profiles import config_for_source_profile, require_source_profile


def get_source_connector(cfg: AgentConfig, profile_id: str = "") -> SourceConnector:
    if profile_id:
        cfg = config_for_source_profile(cfg, require_source_profile(cfg, profile_id))
    source = (cfg.source or "tapd").lower()
    if source == "tapd":
        return TapdConnector(
            base_url=cfg.tapd.base_url,
            workspace_id=cfg.tapd.workspace_id,
            latest_endpoint=cfg.tapd.latest_endpoint,
            detail_endpoint=cfg.tapd.detail_endpoint,
            field_mapping=cfg.tapd.field_mapping,
            bug_latest_endpoint=cfg.tapd.bug_latest_endpoint,
            bug_detail_endpoint=cfg.tapd.bug_detail_endpoint,
            bug_field_mapping=cfg.tapd.bug_field_mapping,
            default_item_type=cfg.tapd.default_item_type,
            auth_mode=cfg.tapd.auth_mode,
            app_id=cfg.tapd.app_id,
            app_secret=cfg.tapd.app_secret,
            token_endpoint=cfg.tapd.token_endpoint,
            auth_scheme=cfg.tapd.auth_scheme,
            auth_header_name=cfg.tapd.auth_header_name,
            timeout_seconds=cfg.tapd.timeout_seconds,
            retries=cfg.tapd.retries,
            retry_backoff_seconds=cfg.tapd.retry_backoff_seconds,
            rate_limit_qps=cfg.tapd.rate_limit_qps,
            error_stats_path=cfg.tapd.error_stats_file,
        )
    if source == "feishu":
        return FeishuConnector(
            base_url=cfg.feishu.base_url,
            auth_mode=cfg.feishu.auth_mode,
            app_id=cfg.feishu.app_id,
            app_secret=cfg.feishu.app_secret,
            document_url=cfg.feishu.document_url,
            resource_type=cfg.feishu.resource_type,
            parse_mode=cfg.feishu.parse_mode,
            table_id=cfg.feishu.table_id,
            view_id=cfg.feishu.view_id,
            sheet_id=cfg.feishu.sheet_id,
            field_mapping=cfg.feishu.field_mapping,
            timeout_seconds=cfg.feishu.timeout_seconds,
            retries=cfg.feishu.retries,
            retry_backoff_seconds=cfg.feishu.retry_backoff_seconds,
        )
    if source == "mock":
        return MockConnector()
    raise ValueError(f"Unsupported source: {cfg.source}")
