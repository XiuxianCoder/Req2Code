from __future__ import annotations

from typing import Any

from req2code.config import FeishuFieldMappingConfig
from req2code.connectors.feishu_connector import FeishuConnector
from req2code.models import TaskType


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return FakeResponse({"code": 0, "tenant_access_token": "tenant-token", "expire": 7200})

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        return FakeResponse(self.responses.pop(0))


def _text_block(block_id: str, parent_id: str, content: str) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "parent_id": parent_id,
        "text": {"elements": [{"text_run": {"content": content}}]},
    }


def test_bitable_records_are_normalized_and_locally_classified():
    session = FakeSession(
        [
            {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "record_id": "recBug001",
                            "fields": {
                                "编号": "BUG-42",
                                "标题": "上传图纸后无法取消",
                                "问题描述": "点击取消没有反应",
                                "类型": "缺陷",
                                "状态": "进行中",
                                "优先级": "高",
                                "负责人": [{"name": "张三"}],
                            },
                        },
                        {
                            "record_id": "recStory002",
                            "fields": {
                                "需求名称": "新增批量导出",
                                "需求说明": "支持选择多个部件导出",
                                "类型": "需求",
                                "状态": "规划中",
                            },
                        },
                    ],
                    "has_more": False,
                },
            }
        ]
    )
    connector = FeishuConnector(
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/base/bascnApp?table=tblIssues&view=vewFiltered",
        session=session,
    )

    items = list(connector.fetch_latest_all(limit=20))

    assert [item.id for item in items] == ["recBug001", "recStory002"]
    assert items[0].type == TaskType.BUG
    assert items[1].type == TaskType.REQUIREMENT
    assert items[0].metadata["normalized_fields"]["business_id"] == "BUG-42"
    assert items[0].metadata["normalized_fields"]["owner"] == "张三"
    assert "原始字段" in items[0].description
    assert connector.get_by_id("recBug001").title == "上传图纸后无法取消"
    assert session.calls[0][0] == "POST"
    assert session.calls[1][2]["headers"]["Authorization"] == "Bearer tenant-token"
    assert "view_id" not in session.calls[1][2]["params"]
    assert items[0].metadata["feishu"]["view_filter_applied"] is False


def test_bitable_connection_validation_ignores_view_filters():
    session = FakeSession([{"code": 0, "data": {"items": [], "has_more": False}}])
    connector = FeishuConnector(
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/base/bascnApp?table=tblIssues&view=vewFiltered",
        session=session,
    )

    result = connector.validate()

    assert result["table_id"] == "tblIssues"
    assert "view_id" not in session.calls[1][2]["params"]


def test_bitable_inspection_lists_tables_and_views_for_the_link_selection():
    session = FakeSession(
        [
            {
                "code": 0,
                "data": {
                    "items": [
                        {"table_id": "tblGuide", "name": "使用说明"},
                        {"table_id": "tblIssues", "name": "测试用例执行记录表"},
                    ]
                },
            },
            {
                "code": 0,
                "data": {
                    "items": [
                        {"view_id": "vewOpen", "view_name": "待处理", "view_type": "grid"},
                    ]
                },
            },
        ]
    )
    connector = FeishuConnector(
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/base/bascnApp?table=tblIssues&view=vewOpen",
        session=session,
    )

    result = connector.inspect_bitable()

    assert result["selected_table_id"] == "tblIssues"
    assert result["selected_table_name"] == "测试用例执行记录表"
    assert result["selected_view_id"] == "vewOpen"
    assert [item["table_id"] for item in result["tables"]] == ["tblGuide", "tblIssues"]
    assert result["views"][0]["name"] == "待处理"
    assert "/tables" in session.calls[1][1]
    assert "/tables/tblIssues/views" in session.calls[2][1]


def test_bitable_field_definitions_include_all_configured_select_options():
    session = FakeSession(
        [{
            "code": 0,
            "data": {
                "items": [
                    {
                        "field_id": "fldCategory",
                        "field_name": "问题分类",
                        "type": 3,
                        "ui_type": "SingleSelect",
                        "property": {"options": [{"id": "opt1", "name": "问题"}, {"id": "opt2", "name": "需求"}]},
                    },
                    {
                        "field_id": "fldStatus",
                        "field_name": "状态",
                        "type": 4,
                        "ui_type": "MultiSelect",
                        "property": {"options": [{"name": "未解决"}, {"name": "已验证"}, {"name": "已关闭"}]},
                    },
                ],
                "has_more": False,
            },
        }]
    )
    connector = FeishuConnector(
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/base/bascnApp?table=tblIssues",
        session=session,
    )

    definitions = connector.bitable_field_definitions()

    assert definitions[0]["options"] == ["问题", "需求"]
    assert definitions[1]["options"] == ["未解决", "已验证", "已关闭"]
    assert definitions[1]["ui_type"] == "MultiSelect"
    assert "/tables/tblIssues/fields" in session.calls[1][1]


def test_agent_schema_analysis_classifies_and_marks_active_rows():
    session = FakeSession(
        [{
            "code": 0,
            "data": {
                "items": [
                    {
                        "record_id": "recProblem",
                        "fields": {
                            "测试项名称": "保存失败",
                            "问题分类": "问题",
                            "状态": "未解决",
                            "实际结果": "点击保存后没有响应",
                            "预期结果": "保存成功",
                        },
                    },
                    {
                        "record_id": "recDone",
                        "fields": {
                            "测试项名称": "导出功能",
                            "问题分类": "需求",
                            "状态": "已验证",
                            "预期结果": "可导出文件",
                        },
                    },
                ],
                "has_more": False,
            },
        }]
    )
    connector = FeishuConnector(
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/base/bascnApp?table=tblIssues",
        schema_analysis={
            "analysis_id": "analysis-1",
            "title_field": "测试项名称",
            "type_field": "问题分类",
            "status_field": "状态",
            "description_fields": ["实际结果", "预期结果"],
            "display_fields": ["问题分类", "状态", "预期结果"],
            "bug_values": ["问题"],
            "requirement_values": ["需求"],
            "active_statuses": ["未解决", "待确认"],
            "terminal_statuses": ["已验证", "已关闭"],
            "notes": ["问题分类决定工作项类型"],
        },
        session=session,
    )

    items = list(connector.fetch_latest_all(limit=20))

    assert items[0].type == TaskType.BUG
    assert items[0].metadata["normalized_fields"]["status_bucket"] == "active"
    assert items[1].type == TaskType.REQUIREMENT
    assert items[1].metadata["normalized_fields"]["status_bucket"] == "terminal"
    assert items[0].metadata["feishu_schema"]["display_fields"] == ["问题分类", "状态", "预期结果"]
    assert "实际结果：点击保存后没有响应" in items[0].description


def test_docx_native_table_rows_become_work_items():
    table = {
        "block_id": "table001",
        "table": {
            "property": {"column_size": 4, "row_size": 2},
            "cells": ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"],
        },
    }
    cells: list[dict[str, Any]] = []
    texts = ["编号", "标题", "类型", "状态", "BUG-9", "保存时页面报错", "Bug", "待处理"]
    for index, text in enumerate(texts, start=1):
        cell_id = f"c{index}"
        text_id = f"t{index}"
        cells.append({"block_id": cell_id, "parent_id": "table001", "table_cell": {}, "children": [text_id]})
        cells.append(_text_block(text_id, cell_id, text))
    session = FakeSession(
        [{"code": 0, "data": {"items": [table, *cells], "has_more": False}}]
    )
    connector = FeishuConnector(
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/docx/doxcnDocumentToken123456789",
        parse_mode="auto",
        session=session,
    )

    items = list(connector.fetch_latest_all(limit=20))

    assert len(items) == 1
    assert items[0].id == "table001-r1"
    assert items[0].title == "保存时页面报错"
    assert items[0].type == TaskType.BUG
    assert items[0].metadata["feishu"]["resource_type"] == "docx_table"
    assert items[0].metadata["normalized_fields"]["status"] == "待处理"


def test_wiki_node_is_resolved_before_reading_docx_headings():
    session = FakeSession(
        [
            {
                "code": 0,
                "data": {"node": {"obj_type": "docx", "obj_token": "doxcnResolvedDocumentToken12"}},
            },
            {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "block_id": "heading001",
                            "heading1": {"elements": [{"text_run": {"content": "新增示例功能"}}]},
                        },
                        _text_block("paragraph001", "heading001", "删除前需要二次确认"),
                    ],
                    "has_more": False,
                },
            },
        ]
    )
    connector = FeishuConnector(
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/wiki/wikcnNodeToken",
        parse_mode="headings",
        session=session,
    )

    items = list(connector.fetch_latest_all(limit=20))

    assert len(items) == 1
    assert items[0].title == "新增示例功能"
    assert "二次确认" in items[0].description
    assert "/open-apis/wiki/v2/spaces/get_node" in session.calls[1][1]
    assert "/open-apis/docx/v1/documents/doxcnResolvedDocumentToken12/blocks" in session.calls[2][1]


def test_project_specific_bitable_columns_can_be_mapped():
    session = FakeSession(
        [{
            "code": 0,
            "data": {
                "items": [{"record_id": "recCustom", "fields": {"事项": "登录页白屏", "阶段": "处理中", "分类值": "缺陷"}}],
                "has_more": False,
            },
        }]
    )
    connector = FeishuConnector(
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/base/bascnApp?table=tblCustom",
        field_mapping=FeishuFieldMappingConfig(title_field="事项", status_field="阶段", type_field="分类值"),
        session=session,
    )

    item = list(connector.fetch_latest_all(limit=20))[0]

    assert item.title == "登录页白屏"
    assert item.type == TaskType.BUG
    assert item.metadata["normalized_fields"]["status"] == "处理中"


def test_bitable_problem_category_and_actual_result_are_classified_as_a_bug():
    session = FakeSession(
        [{
            "code": 0,
            "data": {
                "items": [{
                    "record_id": "recProblem",
                    "fields": {
                        "测试项名称": "新建项目",
                        "问题分类": "问题",
                        "状态": "未解决",
                        "实际结果": "未填写的信息被错误填充",
                        "预期结果": "未填写的信息应保持为空",
                    },
                }],
                "has_more": False,
            },
        }]
    )
    connector = FeishuConnector(
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/base/bascnApp?table=tblTests",
        field_mapping=FeishuFieldMappingConfig(title_field="测试项名称"),
        session=session,
    )

    item = list(connector.fetch_latest_all(limit=20))[0]

    assert item.type == TaskType.BUG
    assert item.metadata["normalized_fields"]["status"] == "未解决"
    assert "错误填充" in item.description
    assert "预期结果" in item.description


def test_spreadsheet_rows_become_work_items():
    session = FakeSession(
        [
            {
                "code": 0,
                "data": {"sheets": [{"sheet_id": "giDk9k", "title": "需求列表", "hidden": False}]},
            },
            {
                "code": 0,
                "data": {
                    "valueRange": {
                        "range": "giDk9k!A1:D3",
                        "values": [
                            ["编号", "标题", "类型", "状态"],
                            ["REQ-1", "增加导出能力", "需求", "规划中"],
                            ["BUG-2", "导出按钮无响应", "缺陷", "待处理"],
                        ],
                    }
                },
            },
        ]
    )
    connector = FeishuConnector(
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/sheets/shtcnToken",
        session=session,
    )

    items = list(connector.fetch_latest_all(limit=20))

    assert [item.title for item in items] == ["增加导出能力", "导出按钮无响应"]
    assert [item.type for item in items] == [TaskType.REQUIREMENT, TaskType.BUG]
    assert items[1].metadata["feishu"]["sheet_id"] == "giDk9k"
    assert "/sheets/query" in session.calls[1][1]
    assert "/values/giDk9k" in session.calls[2][1]


def test_wide_spreadsheet_is_read_in_bounded_column_chunks():
    first_headers = [f"字段{index}" for index in range(1, 25)]
    session = FakeSession(
        [
            {
                "code": 0,
                "data": {
                    "sheets": [
                        {
                            "sheet_id": "wide01",
                            "hidden": False,
                            "grid_properties": {"column_count": 30, "row_count": 1000},
                        }
                    ]
                },
            },
            {"code": 0, "data": {"valueRange": {"values": [first_headers, [*([""] * 23), "辅助值"]]}}},
            {
                "code": 0,
                "data": {
                    "valueRange": {
                        "values": [
                            ["标题", "类型", "状态", "字段28", "字段29", "字段30"],
                            ["跨分块需求", "需求", "规划中", "", "", ""],
                        ]
                    }
                },
            },
        ]
    )
    connector = FeishuConnector(
        auth_mode="tenant",
        app_id="cli_a123",
        app_secret="secret",
        document_url="https://example.feishu.cn/sheets/shtWide",
        session=session,
    )

    item = list(connector.fetch_latest_all(limit=200))[0]

    assert item.title == "跨分块需求"
    assert len([call for call in session.calls if "/values/" in call[1]]) == 2
