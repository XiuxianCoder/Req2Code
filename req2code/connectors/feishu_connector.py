from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import requests

from req2code.config import FeishuFieldMappingConfig
from req2code.connectors.base import SourceConnector
from req2code.models import TaskType, WorkItem


@dataclass(frozen=True)
class FeishuResource:
    resource_type: str
    token: str
    table_id: str = ""
    view_id: str = ""
    sheet_id: str = ""


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("编号", "id", "需求id", "缺陷id", "bugid", "任务id"),
    "title": ("标题", "名称", "需求名称", "需求标题", "缺陷标题", "bug标题", "问题", "任务"),
    "description": ("描述", "说明", "需求说明", "需求描述", "缺陷描述", "问题描述", "问题现象", "实际结果", "测试结果", "当前结果", "详细内容", "内容"),
    "type": ("类型", "工作项类型", "需求类型", "问题类型", "问题分类", "类别"),
    "status": ("状态", "处理状态", "当前状态", "进度"),
    "priority": ("优先级", "优先程度", "紧急程度", "紧急度"),
    "severity": ("严重程度", "严重性", "影响程度"),
    "owner": ("负责人", "处理人", "开发人员", "经办人", "责任人"),
    "reporter": ("报告人", "提出人", "创建人", "提交人"),
    "acceptance": ("验收标准", "预期结果", "完成标准", "验收条件"),
    "updated": ("更新时间", "修改时间", "最后更新时间", "更新日期"),
}

BUG_TERMS = ("bug", "缺陷", "故障", "报错", "异常", "失败", "无法", "错误", "修复", "崩溃", "闪退")


class FeishuConnector(SourceConnector):
    """Read Feishu docx tables/headings and Bitable records as work items."""

    def __init__(
        self,
        *,
        base_url: str = "https://open.feishu.cn",
        auth_mode: str = "tenant",
        app_id: str = "",
        app_secret: str = "",
        document_url: str = "",
        resource_type: str = "auto",
        parse_mode: str = "auto",
        table_id: str = "",
        view_id: str = "",
        sheet_id: str = "",
        field_mapping: FeishuFieldMappingConfig | None = None,
        schema_analysis: dict[str, Any] | None = None,
        timeout_seconds: int = 20,
        retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or "https://open.feishu.cn").rstrip("/")
        self.auth_mode = (auth_mode or "tenant").lower()
        self.app_id = app_id
        self.app_secret = app_secret
        self.document_url = document_url
        self.resource_type = (resource_type or "auto").lower()
        self.parse_mode = (parse_mode or "auto").lower()
        self.table_id = table_id
        self.view_id = view_id
        self.sheet_id = sheet_id
        self.field_mapping = field_mapping or FeishuFieldMappingConfig()
        self.schema_analysis = dict(schema_analysis or {})
        self.timeout_seconds = timeout_seconds
        self.retries = max(1, retries)
        self.retry_backoff_seconds = retry_backoff_seconds
        self.session = session or requests.Session()
        self._access_token = ""
        self._cached_items: list[WorkItem] | None = None

    # -- Authentication and HTTP ------------------------------------------

    def _tenant_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        if self.auth_mode != "tenant":
            raise RuntimeError(f"飞书暂不支持认证方式：{self.auth_mode}")
        if not self.app_id or not self.app_secret:
            raise RuntimeError("飞书 App ID/App Secret 未配置")
        url = f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal"
        try:
            response = self.session.post(
                url,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"获取飞书 tenant_access_token 失败：{type(exc).__name__}") from exc
        if not isinstance(payload, dict) or int(payload.get("code", -1)) != 0:
            message = str(payload.get("msg") or "未知错误")[:300] if isinstance(payload, dict) else "响应格式错误"
            raise RuntimeError(f"获取飞书 tenant_access_token 失败：{message}")
        token = str(payload.get("tenant_access_token") or "").strip()
        if not token:
            raise RuntimeError("飞书凭证响应缺少 tenant_access_token")
        self._access_token = token
        return token

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.auth_mode != "tenant":
            raise RuntimeError(f"飞书暂不支持认证方式：{self.auth_mode}")
        token = self._tenant_access_token()
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                    params=params,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("飞书响应不是 JSON 对象")
                if int(payload.get("code", 0)) != 0:
                    raise RuntimeError(f"飞书 API 错误 {payload.get('code')}：{str(payload.get('msg') or '')[:300]}")
                return payload
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
        raise RuntimeError(f"飞书 API 请求失败：{last_error}") from last_error

    # -- Resource resolution ----------------------------------------------

    def _resource_from_url(self) -> FeishuResource:
        parsed = urlparse((self.document_url or "").strip())
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("无法从飞书链接识别文档 token")
        raw_type, token = parts[0].lower(), parts[1]
        query = parse_qs(parsed.query)
        table_id = self.table_id or str((query.get("table") or [""])[0])
        view_id = self.view_id or str((query.get("view") or [""])[0])
        sheet_id = self.sheet_id or str((query.get("sheet") or [""])[0])
        type_map = {"docx": "docx", "wiki": "wiki", "base": "bitable", "sheets": "spreadsheet"}
        resource_type = type_map.get(raw_type, "")
        if not resource_type:
            raise ValueError("当前仅支持飞书 /docx/、/wiki/、/base/ 和 /sheets/ 链接")
        return FeishuResource(resource_type, token, table_id, view_id, sheet_id)

    def _resolve_resource(self) -> FeishuResource:
        resource = self._resource_from_url()
        if resource.resource_type != "wiki":
            if self.resource_type not in {"", "auto", resource.resource_type}:
                raise ValueError("飞书资源类型与链接不匹配")
            return resource
        payload = self._request_json(
            "GET",
            "/open-apis/wiki/v2/spaces/get_node",
            params={"token": resource.token},
        )
        node = ((payload.get("data") or {}).get("node") or {}) if isinstance(payload.get("data"), dict) else {}
        obj_type = str(node.get("obj_type") or "").lower()
        obj_token = str(node.get("obj_token") or "").strip()
        normalized_type = {"doc": "docx", "docx": "docx", "bitable": "bitable", "sheet": "spreadsheet"}.get(obj_type, "")
        if not normalized_type or not obj_token:
            raise ValueError(f"知识库节点类型 {obj_type or 'unknown'} 暂不支持")
        return FeishuResource(normalized_type, obj_token, resource.table_id, resource.view_id, resource.sheet_id)

    def validate(self) -> dict[str, str]:
        resource = self._resolve_resource()
        if resource.resource_type == "bitable":
            table_id = resource.table_id or self._first_bitable_table(resource.token)
            self._request_json(
                "GET",
                f"/open-apis/bitable/v1/apps/{resource.token}/tables/{table_id}/records",
                # Validate the table itself. A configured Feishu view may hide
                # records through its own filters; Req2Code always performs
                # actionable-status filtering locally after schema analysis.
                params={"page_size": 1},
            )
            return {"resource_type": "bitable", "table_id": table_id}
        if resource.resource_type == "spreadsheet":
            sheet_id = str(self._spreadsheet_sheet_info(resource.token, resource.sheet_id)["sheet_id"])
            return {"resource_type": "spreadsheet", "table_id": sheet_id}
        self._request_json(
            "GET",
            f"/open-apis/docx/v1/documents/{resource.token}/blocks",
            params={"page_size": 1, "document_revision_id": -1},
        )
        return {"resource_type": "docx", "table_id": ""}

    # -- Normalization -----------------------------------------------------

    @staticmethod
    def _stringify(value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            parts = [FeishuConnector._stringify(part) for part in value]
            return ", ".join(dict.fromkeys(part for part in parts if part))
        if isinstance(value, dict):
            for key in ("text", "name", "title", "link", "url", "value"):
                if key in value:
                    text = FeishuConnector._stringify(value.get(key))
                    if text:
                        return text
            parts = [FeishuConnector._stringify(part) for part in value.values()]
            compact = ", ".join(dict.fromkeys(part for part in parts if part))
            return compact or json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value).strip()

    @staticmethod
    def _normalized_key(value: str) -> str:
        return re.sub(r"[\s_\-:：/（）()]+", "", str(value or "")).casefold()

    def _field(self, fields: dict[str, Any], canonical: str) -> str:
        override = str(getattr(self.field_mapping, f"{canonical}_field", "") or "").strip()
        candidates = (override,) if override else FIELD_ALIASES.get(canonical, ())
        normalized = {self._normalized_key(key): self._stringify(value) for key, value in fields.items()}
        for candidate in candidates:
            key = self._normalized_key(candidate)
            if key in normalized and normalized[key]:
                return normalized[key]
        for candidate in candidates:
            key = self._normalized_key(candidate)
            if not key:
                continue
            for field_key, value in normalized.items():
                if value and (key in field_key or field_key in key):
                    return value
        return ""

    def _analyzed_field(self, fields: dict[str, Any], canonical: str) -> str:
        field_name = str(self.schema_analysis.get(f"{canonical}_field") or "").strip()
        if field_name and field_name in fields:
            return self._stringify(fields.get(field_name))
        return self._field(fields, canonical)

    def _status_bucket(self, status: str) -> str:
        if not status or not self.schema_analysis:
            return ""
        normalized = self._normalized_key(status)
        active = {self._normalized_key(value) for value in self.schema_analysis.get("active_statuses") or []}
        terminal = {self._normalized_key(value) for value in self.schema_analysis.get("terminal_statuses") or []}
        if normalized in active:
            return "active"
        if normalized in terminal:
            return "terminal"
        return "other" if active else ""

    def _item_from_fields(
        self,
        *,
        item_id: str,
        fields: dict[str, Any],
        source_url: str,
        resource_metadata: dict[str, Any],
    ) -> WorkItem | None:
        compact_fields = {str(key).strip(): self._stringify(value) for key, value in fields.items()}
        compact_fields = {key: value for key, value in compact_fields.items() if key and value}
        if not compact_fields:
            return None
        business_id = self._analyzed_field(compact_fields, "id")
        title = self._analyzed_field(compact_fields, "title")
        description_fields = [
            str(field_name)
            for field_name in self.schema_analysis.get("description_fields") or []
            if str(field_name) in compact_fields
        ]
        description = "\n".join(
            f"{field_name}：{compact_fields[field_name]}" for field_name in description_fields if compact_fields[field_name]
        ) or self._analyzed_field(compact_fields, "description")
        item_type_text = self._analyzed_field(compact_fields, "type")
        normalized_type = item_type_text.casefold()
        bug_values = {self._normalized_key(value) for value in self.schema_analysis.get("bug_values") or []}
        requirement_values = {
            self._normalized_key(value) for value in self.schema_analysis.get("requirement_values") or []
        }
        normalized_type_value = self._normalized_key(item_type_text)
        explicit_bug = normalized_type_value in bug_values or any(
            term in normalized_type for term in ("bug", "缺陷", "问题", "故障")
        )
        explicit_requirement = normalized_type_value in requirement_values or any(
            term in normalized_type for term in ("需求", "story", "requirement")
        )
        combined = f"{title} {description}".casefold()
        inferred_bug = any(term in combined for term in BUG_TERMS)
        item_type = TaskType.BUG if explicit_bug or (not explicit_requirement and inferred_bug) else TaskType.REQUIREMENT
        if not title:
            title = next(iter(compact_fields.values()), f"飞书工作项 {business_id or item_id}")[:120]
        details = "\n".join(f"{key}：{value}" for key, value in compact_fields.items())
        if description:
            description = f"{description}\n\n原始字段：\n{details}"
        else:
            description = details
        status = self._analyzed_field(compact_fields, "status")
        normalized_fields = {
            "status": status,
            "status_bucket": self._status_bucket(status),
            "priority": self._analyzed_field(compact_fields, "priority"),
            "severity": self._analyzed_field(compact_fields, "severity"),
            "owner": self._analyzed_field(compact_fields, "owner"),
            "reporter": self._analyzed_field(compact_fields, "reporter"),
            "acceptance_criteria": self._analyzed_field(compact_fields, "acceptance"),
            "updated": self._analyzed_field(compact_fields, "updated"),
            "source_url": source_url,
            "business_id": business_id,
        }
        return WorkItem(
            id=str(item_id),
            title=title,
            description=description,
            type=item_type,
            source="feishu",
            metadata={
                "normalized_fields": {key: value for key, value in normalized_fields.items() if value},
                "source_fields": compact_fields,
                "feishu": resource_metadata,
                "feishu_schema": {
                    "analysis_id": str(self.schema_analysis.get("analysis_id") or ""),
                    "display_fields": [
                        field_name
                        for field_name in self.schema_analysis.get("display_fields") or []
                        if field_name in compact_fields
                    ],
                    "notes": list(self.schema_analysis.get("notes") or []),
                } if self.schema_analysis else {},
            },
        )

    # -- Bitable -----------------------------------------------------------

    def _first_bitable_table(self, app_token: str) -> str:
        payload = self._request_json(
            "GET",
            f"/open-apis/bitable/v1/apps/{app_token}/tables",
            params={"page_size": 100},
        )
        items = ((payload.get("data") or {}).get("items") or []) if isinstance(payload.get("data"), dict) else []
        if not items or not isinstance(items[0], dict) or not items[0].get("table_id"):
            raise ValueError("飞书多维表格中没有可读取的数据表")
        return str(items[0]["table_id"])

    def inspect_bitable(self, *, table_id: str = "", view_id: str = "") -> dict[str, Any]:
        """List tables and views without returning records or credentials."""
        resource = self._resolve_resource()
        if resource.resource_type != "bitable":
            raise ValueError("当前飞书链接不是多维表格")
        payload = self._request_json(
            "GET",
            f"/open-apis/bitable/v1/apps/{resource.token}/tables",
            params={"page_size": 100},
        )
        raw_tables = ((payload.get("data") or {}).get("items") or []) if isinstance(payload.get("data"), dict) else []
        tables = [
            {"table_id": str(item.get("table_id") or ""), "name": str(item.get("name") or "未命名数据表")}
            for item in raw_tables
            if isinstance(item, dict) and item.get("table_id")
        ]
        if not tables:
            raise ValueError("飞书多维表格中没有可读取的数据表")

        requested_table = (table_id or "").strip()
        selected_table = requested_table or resource.table_id or tables[0]["table_id"]
        selected_entry = next((item for item in tables if item["table_id"] == selected_table), None)
        if selected_entry is None:
            raise ValueError(f"多维表格中不存在数据表：{selected_table}")

        views_payload = self._request_json(
            "GET",
            f"/open-apis/bitable/v1/apps/{resource.token}/tables/{selected_table}/views",
            params={"page_size": 100},
        )
        raw_views = (
            ((views_payload.get("data") or {}).get("items") or [])
            if isinstance(views_payload.get("data"), dict)
            else []
        )
        views = [
            {
                "view_id": str(item.get("view_id") or ""),
                "name": str(item.get("view_name") or "未命名视图"),
                "view_type": str(item.get("view_type") or ""),
            }
            for item in raw_views
            if isinstance(item, dict) and item.get("view_id")
        ]
        requested_view = (view_id or "").strip()
        selected_view = requested_view or (resource.view_id if selected_table == resource.table_id else "")
        if selected_view and not any(item["view_id"] == selected_view for item in views):
            selected_view = ""
        return {
            "resource_type": "bitable",
            "selected_table_id": selected_table,
            "selected_table_name": selected_entry["name"],
            "selected_view_id": selected_view,
            "tables": tables,
            "views": views,
        }

    def bitable_field_definitions(self, *, table_id: str = "") -> list[dict[str, Any]]:
        """Return field types and configured select options for schema analysis."""
        resource = self._resolve_resource()
        if resource.resource_type != "bitable":
            raise ValueError("当前飞书链接不是多维表格")
        selected_table = (table_id or resource.table_id).strip() or self._first_bitable_table(resource.token)
        definitions: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            payload = self._request_json(
                "GET",
                f"/open-apis/bitable/v1/apps/{resource.token}/tables/{selected_table}/fields",
                params=params,
            )
            data = payload.get("data") or {}
            fields = data.get("items") or [] if isinstance(data, dict) else []
            for field in fields:
                if not isinstance(field, dict) or not field.get("field_name"):
                    continue
                property_data = field.get("property") if isinstance(field.get("property"), dict) else {}
                raw_options = property_data.get("options") if isinstance(property_data, dict) else []
                options = [
                    self._stringify(option.get("name"))
                    for option in (raw_options or [])
                    if isinstance(option, dict) and self._stringify(option.get("name"))
                ]
                definitions.append(
                    {
                        "field_id": str(field.get("field_id") or ""),
                        "field_name": str(field.get("field_name") or ""),
                        "type": field.get("type"),
                        "ui_type": str(field.get("ui_type") or ""),
                        "options": list(dict.fromkeys(options)),
                    }
                )
            if not isinstance(data, dict) or not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        return definitions

    def _bitable_items(self, resource: FeishuResource, limit: int) -> list[WorkItem]:
        table_id = resource.table_id or self._first_bitable_table(resource.token)
        items: list[WorkItem] = []
        page_token = ""
        while len(items) < limit:
            params: dict[str, Any] = {"page_size": min(500, max(1, limit - len(items))), "automatic_fields": True}
            if page_token:
                params["page_token"] = page_token
            # Deliberately omit view_id. View filters are presentation state in
            # Feishu and can hide unresolved rows. Fetch the complete table,
            # then apply the agent-mapped active/terminal status rules locally.
            payload = self._request_json(
                "GET",
                f"/open-apis/bitable/v1/apps/{resource.token}/tables/{table_id}/records",
                params=params,
            )
            data = payload.get("data") or {}
            rows = data.get("items") or [] if isinstance(data, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                record_id = str(row.get("record_id") or f"row-{len(items) + 1}")
                item = self._item_from_fields(
                    item_id=record_id,
                    fields=row.get("fields") if isinstance(row.get("fields"), dict) else {},
                    source_url=self.document_url,
                    resource_metadata={
                        "resource_type": "bitable",
                        "app_token": resource.token,
                        "table_id": table_id,
                        "view_id": resource.view_id,
                        "view_filter_applied": False,
                        "record_id": record_id,
                    },
                )
                if item:
                    items.append(item)
                    if len(items) >= limit:
                        break
            if not isinstance(data, dict) or not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        return items

    # -- Docx blocks and tables -------------------------------------------

    def _spreadsheet_sheet_info(self, spreadsheet_token: str, sheet_id: str = "") -> dict[str, Any]:
        if sheet_id:
            payload = self._request_json(
                "GET",
                f"/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/{sheet_id}",
            )
            data = payload.get("data") or {}
            sheet = data.get("sheet") if isinstance(data, dict) else None
            if not isinstance(sheet, dict) or not sheet.get("sheet_id"):
                raise ValueError(f"飞书电子表格中找不到工作表：{sheet_id}")
            return sheet
        payload = self._request_json("GET", f"/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query")
        sheets = ((payload.get("data") or {}).get("sheets") or []) if isinstance(payload.get("data"), dict) else []
        visible = [sheet for sheet in sheets if isinstance(sheet, dict) and not sheet.get("hidden") and sheet.get("sheet_id")]
        candidates = visible or [sheet for sheet in sheets if isinstance(sheet, dict) and sheet.get("sheet_id")]
        if not candidates:
            raise ValueError("飞书电子表格中没有可读取的工作表")
        return candidates[0]

    def _first_spreadsheet_sheet(self, spreadsheet_token: str) -> str:
        return str(self._spreadsheet_sheet_info(spreadsheet_token)["sheet_id"])

    @staticmethod
    def _spreadsheet_column_name(index: int) -> str:
        value = max(1, index)
        result = ""
        while value:
            value, remainder = divmod(value - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def _spreadsheet_items(self, resource: FeishuResource, limit: int) -> list[WorkItem]:
        sheet = self._spreadsheet_sheet_info(resource.token, resource.sheet_id)
        sheet_id = str(sheet["sheet_id"])
        grid = sheet.get("grid_properties") if isinstance(sheet.get("grid_properties"), dict) else {}
        column_count = min(100, max(1, int(grid.get("column_count") or 20)))
        requested_rows = min(501, max(2, limit + 1))
        # Sheets limits one range response to 5,000 cells. Read wide work-item
        # tables in bounded column chunks and merge them locally by row.
        columns_per_request = max(1, min(column_count, 5000 // requested_rows))
        rows: list[list[Any]] = []
        columns_read = 0
        for start_column in range(1, column_count + 1, columns_per_request):
            end_column_index = min(column_count, start_column + columns_per_request - 1)
            start_column_name = self._spreadsheet_column_name(start_column)
            end_column_name = self._spreadsheet_column_name(end_column_index)
            cell_range = f"{sheet_id}!{start_column_name}1:{end_column_name}{requested_rows}"
            payload = self._request_json(
                "GET",
                f"/open-apis/sheets/v2/spreadsheets/{resource.token}/values/{cell_range}",
            )
            data = payload.get("data") or {}
            value_range = data.get("valueRange") or data.get("value_range") or {} if isinstance(data, dict) else {}
            values = value_range.get("values") or [] if isinstance(value_range, dict) else []
            while len(rows) < len(values):
                rows.append([""] * columns_read)
            chunk_width = end_column_index - start_column + 1
            for row_index in range(len(rows)):
                raw_row = values[row_index] if row_index < len(values) else []
                chunk = raw_row if isinstance(raw_row, list) else [raw_row]
                rows[row_index].extend([*chunk, *([""] * max(0, chunk_width - len(chunk)))][:chunk_width])
            columns_read += chunk_width
        header_index = next((index for index, row in enumerate(rows) if any(self._stringify(cell) for cell in row)), -1)
        if header_index < 0:
            return []
        headers = [self._stringify(cell) or f"列{index + 1}" for index, cell in enumerate(rows[header_index])]
        items: list[WorkItem] = []
        for row_index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
            padded = [*row, *([""] * max(0, len(headers) - len(row)))]
            fields = dict(zip(headers, padded[: len(headers)]))
            if not any(self._stringify(value) for value in fields.values()):
                continue
            item = self._item_from_fields(
                item_id=f"{sheet_id}-r{row_index}",
                fields=fields,
                source_url=self.document_url,
                resource_metadata={
                    "resource_type": "spreadsheet",
                    "spreadsheet_token": resource.token,
                    "sheet_id": sheet_id,
                    "row_index": row_index,
                },
            )
            if item:
                items.append(item)
                if len(items) >= limit:
                    break
        return items

    def _all_docx_blocks(self, document_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 500, "document_revision_id": -1}
            if page_token:
                params["page_token"] = page_token
            payload = self._request_json(
                "GET",
                f"/open-apis/docx/v1/documents/{document_id}/blocks",
                params=params,
            )
            data = payload.get("data") or {}
            blocks.extend(row for row in (data.get("items") or []) if isinstance(row, dict))
            if not isinstance(data, dict) or not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        return blocks

    @classmethod
    def _rich_text(cls, value: Any) -> str:
        if isinstance(value, list):
            return "".join(cls._rich_text(part) for part in value)
        if not isinstance(value, dict):
            return ""
        for key in ("text_run", "mention_doc", "mention_user", "equation", "file"):
            child = value.get(key)
            if isinstance(child, dict):
                for text_key in ("content", "title", "name", "url"):
                    text = child.get(text_key)
                    if isinstance(text, str) and text:
                        return text
        if isinstance(value.get("elements"), list):
            return cls._rich_text(value["elements"])
        return ""

    @classmethod
    def _direct_block_text(cls, block: dict[str, Any]) -> str:
        for key in ("text", "heading1", "heading2", "heading3", "heading4", "heading5", "heading6", "heading7", "heading8", "heading9", "bullet", "ordered", "code", "quote", "todo", "callout"):
            value = block.get(key)
            if isinstance(value, dict):
                text = cls._rich_text(value).strip()
                if text:
                    return text
        return ""

    def _docx_items(self, resource: FeishuResource, limit: int) -> list[WorkItem]:
        blocks = self._all_docx_blocks(resource.token)
        by_id = {str(block.get("block_id") or ""): block for block in blocks if block.get("block_id")}
        children: dict[str, list[str]] = {}
        for block in blocks:
            parent_id = str(block.get("parent_id") or "")
            block_id = str(block.get("block_id") or "")
            if parent_id and block_id:
                children.setdefault(parent_id, []).append(block_id)

        def descendants_text(block_id: str, seen: set[str] | None = None) -> str:
            visited = seen or set()
            if block_id in visited:
                return ""
            visited.add(block_id)
            block = by_id.get(block_id, {})
            parts = [self._direct_block_text(block)]
            child_ids = [str(value) for value in (block.get("children") or [])] or children.get(block_id, [])
            parts.extend(descendants_text(child_id, visited) for child_id in child_ids)
            return "\n".join(part for part in parts if part).strip()

        table_items: list[WorkItem] = []
        for table in blocks:
            table_data = table.get("table")
            if not isinstance(table_data, dict):
                continue
            block_id = str(table.get("block_id") or f"table-{len(table_items) + 1}")
            properties = table_data.get("property") if isinstance(table_data.get("property"), dict) else {}
            columns = int(properties.get("column_size") or properties.get("column_count") or 0)
            cell_ids = [
                str(value)
                for value in (table_data.get("cells") or table.get("children") or [])
            ] or children.get(block_id, [])
            if columns <= 0 or len(cell_ids) < columns * 2:
                continue
            cells = [descendants_text(cell_id) for cell_id in cell_ids]
            headers = [value or f"列{index + 1}" for index, value in enumerate(cells[:columns])]
            for offset in range(columns, len(cells), columns):
                row = cells[offset : offset + columns]
                if len(row) < columns:
                    break
                fields = dict(zip(headers, row))
                item = self._item_from_fields(
                    item_id=f"{block_id}-r{offset // columns}",
                    fields=fields,
                    source_url=self.document_url,
                    resource_metadata={
                        "resource_type": "docx_table",
                        "document_id": resource.token,
                        "table_block_id": block_id,
                        "row_index": offset // columns,
                    },
                )
                if item:
                    table_items.append(item)
                    if len(table_items) >= limit:
                        return table_items

        if self.parse_mode == "table_rows":
            return table_items
        if self.parse_mode == "auto" and table_items:
            return table_items[:limit]

        heading_items: list[WorkItem] = []
        current_title = ""
        current_id = ""
        current_lines: list[str] = []

        def flush_heading() -> None:
            if not current_title:
                return
            fields = {"标题": current_title, "描述": "\n".join(current_lines).strip()}
            item = self._item_from_fields(
                item_id=current_id or f"section-{len(heading_items) + 1}",
                fields=fields,
                source_url=self.document_url,
                resource_metadata={"resource_type": "docx_section", "document_id": resource.token, "block_id": current_id},
            )
            if item:
                heading_items.append(item)

        for block in blocks:
            heading_key = next((key for key in (f"heading{level}" for level in range(1, 10)) if isinstance(block.get(key), dict)), "")
            text = self._direct_block_text(block)
            if heading_key and text:
                flush_heading()
                current_title = text
                current_id = str(block.get("block_id") or f"section-{len(heading_items) + 1}")
                current_lines = []
            elif current_title and text:
                current_lines.append(text)
        flush_heading()
        if self.parse_mode in {"auto", "headings"} and heading_items:
            return heading_items[:limit]

        lines: list[str] = []
        for block in blocks:
            text = self._direct_block_text(block)
            if text and (not lines or lines[-1] != text):
                lines.append(text)
        whole_text = "\n".join(lines).strip()
        if not whole_text:
            return []
        item = self._item_from_fields(
            item_id=resource.token,
            fields={"标题": lines[0][:120] if lines else "飞书文档任务", "描述": whole_text},
            source_url=self.document_url,
            resource_metadata={"resource_type": "docx", "document_id": resource.token},
        )
        return [item] if item else []

    # -- SourceConnector ---------------------------------------------------

    def _load_items(self, limit: int) -> list[WorkItem]:
        resource = self._resolve_resource()
        if resource.resource_type == "bitable":
            return self._bitable_items(resource, limit)
        if resource.resource_type == "spreadsheet":
            return self._spreadsheet_items(resource, limit)
        return self._docx_items(resource, limit)

    def fetch_latest(self, limit: int = 10) -> Iterable[WorkItem]:
        items = self._load_items(max(1, limit))
        self._cached_items = items
        return items[:limit]

    def fetch_latest_all(self, limit: int = 10) -> Iterable[WorkItem]:
        return self.fetch_latest(limit)

    def fetch_latest_by_type(self, limit: int = 10, item_type: str = "story") -> Iterable[WorkItem]:
        expected = TaskType.BUG if (item_type or "").lower() == "bug" else TaskType.REQUIREMENT
        items = self._load_items(max(200, limit))
        self._cached_items = items
        return [item for item in items if item.type == expected][:limit]

    def get_by_id(self, req_id: str) -> WorkItem:
        items = self._cached_items if self._cached_items is not None else self._load_items(500)
        self._cached_items = items
        for item in items:
            if item.id == req_id:
                return item
        raise KeyError(f"飞书工作项不存在：{req_id}")

    def get_by_id_with_type(self, req_id: str, item_type: str = "story") -> WorkItem:
        return self.get_by_id(req_id)
