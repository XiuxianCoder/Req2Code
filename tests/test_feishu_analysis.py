from __future__ import annotations

import pytest

from req2code.feishu_analysis import FeishuTableAnalysisStore, build_analysis_prompt


def test_analysis_store_preserves_field_types_and_all_select_options(tmp_path):
    store = FeishuTableAnalysisStore(tmp_path)
    analysis = store.create(
        profile_id="feishu-product",
        profile_name="飞书产品问题",
        table_id="tblIssues",
        view_id="vewOpen",
        field_names=["标题", "问题分类", "状态"],
        field_samples={"问题分类": ["问题"], "状态": ["未解决", "已验证"]},
        field_definitions=[
            {"field_id": "fldType", "field_name": "问题分类", "type": 3, "ui_type": "SingleSelect", "options": ["问题", "需求", "优化"]},
            {"field_id": "fldStatus", "field_name": "状态", "type": 4, "ui_type": "MultiSelect", "options": ["未解决", "待确认", "已验证", "已关闭"]},
        ],
    )

    prompt = build_analysis_prompt(analysis)

    assert '"options":["问题","需求","优化"]' in prompt
    assert '"options":["未解决","待确认","已验证","已关闭"]' in prompt
    assert "App Secret" not in prompt

    completed = store.complete(
        analysis.analysis_id,
        {
            "title_field": "标题",
            "type_field": "问题分类",
            "status_field": "状态",
            "description_fields": ["标题"],
            "display_fields": ["问题分类", "状态"],
            "bug_values": ["问题"],
            "requirement_values": ["需求"],
            "active_statuses": ["未解决", "待确认"],
            "terminal_statuses": ["已验证", "已关闭"],
        },
    )

    assert completed.status == "completed"
    assert completed.mapping["active_statuses"] == ["未解决", "待确认"]
    assert store.require(analysis.analysis_id).mapping["display_fields"] == ["问题分类", "状态"]


def test_analysis_rejects_fields_that_are_not_in_the_authorized_schema(tmp_path):
    store = FeishuTableAnalysisStore(tmp_path)
    analysis = store.create(
        profile_id="feishu-product",
        profile_name="飞书产品问题",
        table_id="tblIssues",
        view_id="",
        field_names=["标题", "状态"],
        field_samples={},
    )

    with pytest.raises(ValueError, match="字段映射不存在"):
        store.complete(analysis.analysis_id, {"title_field": "不存在的字段"})
