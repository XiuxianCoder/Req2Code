from __future__ import annotations

from pathlib import Path

from req2code.run_state import RunRecord


STATUS_LABELS = {
    "preparing": "准备中",
    "developing": "开发中（可继续收尾）",
    "testing": "验证中",
    "waiting_approval": "等待人工审核",
    "changes_requested": "需要继续修改",
    "rejected": "已驳回",
    "stale": "变更已失效",
    "committing": "正在提交",
    "pushing": "正在推送",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def _status_label(status: str) -> str:
    return f"{STATUS_LABELS.get(status, status)}（`{status}`）"


def _item_type_label(item_type: str) -> str:
    return "缺陷" if item_type == "bug" else "需求" if item_type == "requirement" else item_type


class RunReportManager:
    def __init__(self, state_dir: str | Path = ".req2code") -> None:
        self.report_dir = Path(state_dir).resolve() / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def write(self, record: RunRecord) -> Path:
        item_lines: list[str] = []
        results_by_id = {
            str(result.get("item_id") or ""): result
            for result in record.item_results
            if isinstance(result, dict)
        }
        for item in record.work_items:
            result = results_by_id.get(str(item.get("id") or ""), {})
            files = result.get("changed_files") if isinstance(result.get("changed_files"), list) else []
            file_lines = "\n".join(f"  - `{name}`" for name in files) or "  - （未单独关联文件）"
            item_lines.extend(
                [
                    f"### {item.get('id')} / {_item_type_label(str(item.get('type') or ''))}",
                    f"- 标题：{item.get('title')}",
                    "- 完整说明：",
                    str(item.get("description") or "（无）"),
                    "- 解决方案或根因：",
                    str(result.get("solution") or record.analysis or "（未单独提供）"),
                    "- 实际修改内容：",
                    str(result.get("changes") or record.development or "（未单独提供）"),
                    "- 关联变更文件：",
                    file_lines,
                    "- 测试证据：",
                    str(result.get("test_evidence") or record.agent_test_evidence or "（未单独提供）"),
                    f"- 验收结论：{result.get('acceptance_result') or '（未单独提供）'}",
                    f"- 剩余风险：{result.get('residual_risks') or '（未单独提供）'}",
                    "",
                ]
            )
        test = record.test_result or {}
        test_source = str(test.get("source") or "legacy_verification")
        coverage = test.get("coverage")
        coverage_display = "未报告" if coverage is None else f"{float(coverage):.1f}%"
        if test_source == "current_coding_agent":
            test_summary = [
                f"- 总体结果：{'通过' if test.get('passed') else '未通过'}",
                "- 证据来源：当前代码智能体",
                "- Req2Code 是否重新执行配置测试：否",
                f"- 覆盖率：{coverage_display}",
            ]
        else:
            test_summary = [
                f"- 单元测试：{'通过' if test.get('unit_passed') else '未通过'}",
                f"- 脚本测试：{'通过' if test.get('script_passed') else '未通过'}",
                f"- 证据来源：{test_source}",
                f"- Req2Code 是否重新执行配置测试：{'是' if test.get('rerun_configured_tests', True) else '否'}",
                f"- 覆盖率：{coverage_display}",
            ]
        changed = "\n".join(f"- `{name}`" for name in record.changed_files) or "- （未检测到代码变更）"
        if record.status == "completed":
            publication_state = "人工审核已通过；Req2Code 已提交并推送经过校验的变更集。"
        elif record.status == "waiting_approval":
            publication_state = "当前未提交、未推送；推送功能保持禁用，等待人工审核。"
        else:
            publication_state = "Req2Code 未发布该运行；当前没有提交或推送。"
        model_display = (
            "当前对话模型（由代码智能体宿主管理）"
            if record.execution_mode == "current_agent"
            else (record.model or "CLI / 账号默认模型")
        )
        execution_display = "当前代码智能体" if record.execution_mode == "current_agent" else record.execution_mode
        branch_mode_display = {
            "current": "保持当前已检出分支",
            "selected": "使用指定分支",
            "default": "使用仓库默认分支",
        }.get(record.branch_mode, record.branch_mode)
        content = "\n".join(
            [
                f"# Req2Code 开发审核报告 / {record.run_id}",
                "",
                "## 运行信息",
                f"- 当前状态：{_status_label(record.status)}",
                f"- 执行方式：{execution_display}（`{record.execution_mode}`）",
                f"- 智能体：{record.engine}",
                f"- 模型：{model_display}",
                f"- 智能体会话：`{record.engine_session_id or '不可恢复'}`",
                f"- 项目记忆：`{record.project_id or '无'}`，版本 {record.project_memory_revision}",
                f"- 项目记忆来源 SHA：`{record.project_memory_source_sha or '未分析'}`",
                f"- 代码仓库：{record.repo_url}",
                f"- 本地路径：`{record.repo_path}`",
                f"- 开发前同步：{'已请求（仅快进）' if record.sync_before_start else '未请求'}",
                f"- 基础分支：`{record.base_branch}`",
                f"- 基准 SHA：`{record.baseline_sha}`",
                f"- 开发分支：`{record.work_branch}`",
                f"- 分支使用方式：{branch_mode_display}（`{record.branch_mode}`）",
                "- 当前发布状态：尚未选择发布；提交和推送保持锁定",
                "- 发布分支：仅在审核通过后的第二次发布确认界面中显示并由人工确认",
                f"- 开始开发时的远程 SHA：`{record.remote_branch_sha or '新分支'}`",
                f"- 变更指纹：`{record.diff_hash}`",
                "",
                "## 需求与缺陷",
                *item_lines,
                "## 实现方案",
                record.analysis or "（未提供实现方案）",
                "",
                "## 开发结果",
                record.development or "（未提供开发结果）",
                "",
                "## 变更文件",
                changed,
                "",
                "## 测试结果",
                *test_summary,
                "",
                "### 测试记录",
                "```text",
                str(test.get("details") or "")[:30000],
                "```",
                f"- 收尾尝试次数：{record.verification_count}",
                "",
                "## 人工审核与发布安全",
                publication_state,
                (
                    f"- 实际发布分支：`{record.remote_name}/{record.push_branch}`"
                    if record.status == "completed"
                    else "- 当前没有提交或推送目标生效"
                ),
                "报告生成后，如果开发分支、基准 HEAD、远程地址、变更指纹或远程分支 SHA 发生变化，本次审批立即失效。",
                f"- 审核说明：{record.approval_comment or '（待审核）'}",
                f"- 提交 SHA：{record.commit_sha or '（尚未提交）'}",
                f"- 错误信息：{record.error or '（无）'}",
            ]
        )
        path = self.report_dir / f"run_{record.run_id}.md"
        path.write_text(content + "\n", encoding="utf-8")
        return path
