from __future__ import annotations

import json
import logging
import secrets
import sys
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer
from rich import print

from req2code import __version__
from req2code.chat import ChatSession
from req2code.config import ConfigManager
from req2code.doctor import run_doctor
from req2code.engine_preflight import inspect_engine, runner_config
from req2code.logging_setup import setup_logging
from req2code.source_factory import get_source_connector
from req2code.source_profiles import build_source_profile, feishu_configured, sync_legacy_source_profile
from req2code.workflow import WorkflowService

app = typer.Typer(help="Req2Code current-agent work-item workflow CLI")
config_app = typer.Typer(help="Configuration commands")
project_app = typer.Typer(help="Project memory commands")
app.add_typer(config_app, name="config")
app.add_typer(project_app, name="project")


def _version_callback(value: bool) -> None:
    if value:
        print(f"Req2Code {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed Req2Code version and exit.",
    ),
) -> None:
    """Req2Code current-agent work-item workflow CLI."""


class ItemType(str, Enum):
    STORY = "story"
    BUG = "bug"
    ALL = "all"

class EngineName(str, Enum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    CURSOR = "cursor"


class SkillHost(str, Enum):
    CODEX = "codex"
    CLAUDE = "claude"
    CURSOR = "cursor"



def _init_logging() -> None:
    try:
        cfg = ConfigManager().load()
        level = getattr(logging, cfg.system.log_level.upper(), logging.INFO)
        setup_logging(level=level, log_file=cfg.system.log_file or "")
    except Exception:
        setup_logging()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def fetch(
    limit: int = 5,
    item_type: Optional[ItemType] = None,
) -> None:
    """Pull requirements/bugs from source."""
    cfg = ConfigManager().load()
    source = get_source_connector(cfg)

    item_type_value = item_type.value if item_type else None

    if item_type_value == "all" and hasattr(source, "fetch_latest_all"):
        items = source.fetch_latest_all(limit=limit)
    elif item_type_value and hasattr(source, "fetch_latest_by_type"):
        items = source.fetch_latest_by_type(limit=limit, item_type=item_type_value)
    else:
        items = source.fetch_latest(limit=limit)

    for item in items:
        print(f"- {item.id} [{item.type.value}] {item.title}")


@app.command()
def run(
    req_id: str,
    item_type: Optional[ItemType] = None,
    auto_review: bool = False,
    target_dir: str = ".",
) -> None:
    """Compatibility mode: run the deprecated nested coding-agent workflow."""
    print("[yellow]Compatibility mode: this command launches a nested coding-agent CLI. Prefer `req2code start` or the Skill/MCP workflow.[/yellow]")
    _init_logging()
    cfg = ConfigManager().load()
    source = get_source_connector(cfg)

    item_type_value = item_type.value if item_type else None

    if item_type_value == "all":
        if not hasattr(source, "fetch_latest_all"):
            print("Current source does not support --item-type all")
            raise typer.Exit(code=2)

        items = list(source.fetch_latest_all(limit=5))
        if req_id and req_id != "ALL":
            items = [x for x in items if x.id == req_id]

        if not items:
            print("No work items found for batch run.")
            raise typer.Exit(code=0)

        svc = WorkflowService(cfg)
        merged = rejected = review_required = failed = 0

        for wi in items:
            result = svc.run(wi, auto_review=auto_review, target_dir=target_dir)
            print(f"[bold]{wi.id}[/bold] -> {result.status.value}")
            print(f"  Branch: {result.branch_name}")
            print(f"  Commit: {result.commit_id}")
            print(f"  Dev report: {result.dev_report_path}")
            print(f"  Test report: {result.test_report_path}")
            if result.review_comment:
                print(f"  Review: {result.review_comment}")

            if result.status.value == "merged":
                merged += 1
            elif result.status.value == "rejected":
                rejected += 1
            elif result.status.value == "review_required":
                review_required += 1
            else:
                failed += 1

        print("\n[bold]Batch summary[/bold]")
        print(f"merged={merged}, rejected={rejected}, review_required={review_required}, failed={failed}")
        return

    if item_type_value and hasattr(source, "get_by_id_with_type"):
        work_item = source.get_by_id_with_type(req_id, item_type=item_type_value)
    else:
        work_item = source.get_by_id(req_id)
    result = WorkflowService(cfg).run(work_item, auto_review=auto_review, target_dir=target_dir)

    print(f"[bold]Workflow status:[/bold] {result.status.value}")
    print(f"Branch: {result.branch_name}")
    print(f"Commit: {result.commit_id}")
    print(f"Dev report: {result.dev_report_path}")
    print(f"Test report: {result.test_report_path}")
    if result.review_comment:
        print(f"Review: {result.review_comment}")


@app.command()
def merge(source_branch: str, target_branch: str = "test") -> None:
    """Manual merge of a branch."""
    from req2code.connectors.git_connector import GitConnector

    git = GitConnector()
    git.merge_to(source_branch, target_branch)
    print(f"Merged {source_branch} -> {target_branch}")


@app.command()
def show(
    req_id: str,
    item_type: ItemType = ItemType.STORY,
    raw: bool = False,
) -> None:
    """Show single work item detail."""
    cfg = ConfigManager().load()
    source = get_source_connector(cfg)

    if hasattr(source, "get_by_id_with_type"):
        work_item = source.get_by_id_with_type(req_id, item_type=item_type.value)
    else:
        work_item = source.get_by_id(req_id)

    print(f"[bold]ID:[/bold] {work_item.id}")
    print(f"[bold]Type:[/bold] {work_item.type.value}")
    print(f"[bold]Title:[/bold] {work_item.title}")
    print(f"[bold]Source:[/bold] {work_item.source}")
    print("[bold]Description:[/bold]")
    print(work_item.description or "")

    if raw:
        print("[bold]Raw metadata:[/bold]")
        print(json.dumps(work_item.metadata or {}, ensure_ascii=False, indent=2))


@app.command()
def review(
    req_id: str,
    approved: bool,
    comment: str = "",
) -> None:
    """Manual review callback and continue workflow."""
    _init_logging()
    cfg = ConfigManager().load()
    source = get_source_connector(cfg)
    work_item = source.get_by_id(req_id)

    service = WorkflowService(cfg)
    service.approvals.decide(req_id, approved=approved, comment=comment)
    result = service.continue_after_manual_review(work_item)
    print(f"[bold]Workflow status:[/bold] {result.status.value}")
    print(f"Branch: {result.branch_name}")
    print(f"Commit: {result.commit_id}")
    if result.review_comment:
        print(f"Review: {result.review_comment}")


@app.command()
def init_project(project_name: str, stack: str = "python", with_git: bool = True) -> None:
    """Initialize a new project (no-git scenario)."""
    from req2code.connectors.git_connector import GitConnector

    root = Path.cwd() / project_name
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "README.md").write_text(f"# {project_name}\n\nStack: {stack}\n", encoding="utf-8")

    if with_git:
        GitConnector(repo_path=root).ensure_repo()

    print(f"Initialized project at {root}")


@app.command()
def serve_approval(host: str = "127.0.0.1", port: int = 8088) -> None:
    """Start approval callback HTTP server."""
    import uvicorn

    uvicorn.run("req2code.approval_server:app", host=host, port=port, reload=False)


@app.command()
def doctor(
    approval_host: str = "127.0.0.1",
    approval_port: int = 8088,
    legacy_engine: bool = typer.Option(False, "--legacy-engine", help="Also check the nested agent CLI compatibility mode"),
) -> None:
    """Pre-flight environment checks."""
    cfg = ConfigManager().load()
    checks = run_doctor(
        cfg,
        approval_host=approval_host,
        approval_port=approval_port,
        check_legacy_engine=legacy_engine,
    )

    passed = 0
    for c in checks:
        status = "[green]PASS[/green]" if c.ok else "[red]FAIL[/red]"
        print(f"{status} {c.name}: {c.detail}")
        if c.ok:
            passed += 1

    total = len(checks)
    if passed != total:
        raise typer.Exit(code=1)


@app.command()
def chat() -> None:
    """Enter interactive chat mode."""
    session = ChatSession()
    print("Req2Code chat mode. Input 'help' for commands, 'exit' to quit.")
    while True:
        text = input("> ").strip()
        if text.lower() in {"exit", "quit"}:
            print("Bye.")
            break
        print(session.handle(text))


# ---------------------------------------------------------------------------
# Config sub-commands
# ---------------------------------------------------------------------------

@config_app.command("set")
def config_set(key: str, value: str) -> None:
    mgr = ConfigManager()
    try:
        mgr.set(key, value)
    except ValueError as err:
        print(f"[red]{err}[/red]")
        print("Available keys:")
        for k in mgr.list_available_keys():
            print(f"- {k}")
        raise typer.Exit(code=2)

    masked = mgr.mask_value(key, value)
    print(f"Set {key}={masked}")


@config_app.command("get")
def config_get(key: str) -> None:
    mgr = ConfigManager()
    try:
        value = mgr.get(key)
    except ValueError as err:
        print(f"[red]{err}[/red]")
        print("Available keys:")
        for k in mgr.list_available_keys():
            print(f"- {k}")
        raise typer.Exit(code=2)

    print(f"{key}={mgr.mask_value(key, value)}")


@config_app.command("list")
def config_list(show_plaintext_secrets: bool = False) -> None:
    mgr = ConfigManager()
    for key in mgr.list_available_keys():
        value = mgr.get(key)
        if show_plaintext_secrets:
            print(f"{key}={value}")
        else:
            print(f"{key}={mgr.mask_value(key, value)}")



@app.command("projects")
def list_projects(limit: int = 50) -> None:
    """List repositories known to the project-memory store."""
    service = WorkflowService(ConfigManager().load())
    rows = service.projects.list(limit=limit)
    if not rows:
        print("No project memory found. Start a development run first.")
        return
    for project in rows:
        print(
            f"{project.project_id} [rev {project.memory_revision}] "
            f"{project.source_sha[:12] or '(not analyzed)'} {project.repository_url}"
        )


@project_app.command("show")
def show_project(project_id: str, raw: bool = False) -> None:
    """Show project identity, source revision, and stored memory."""
    service = WorkflowService(ConfigManager().load())
    try:
        project = service.projects.require(project_id)
    except KeyError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    documents = service.projects.read_documents(project_id)
    if raw:
        print(json.dumps({"project": project.__dict__, "documents": documents}, ensure_ascii=False, indent=2))
        return
    print(f"Project: {project.project_id}")
    print(f"Repository: {project.repository_url}")
    print(f"Canonical URL: {project.canonical_url}")
    print(f"Default branch: {project.default_branch or '(unknown)'}")
    print(f"Memory revision: {project.memory_revision}")
    print(f"Source SHA: {project.source_sha or '(not analyzed)'}")
    print(f"Generated by: {project.generated_by or '(none)'}")
    for name, content in documents.items():
        print(f"\n[bold]{name.title()}[/bold]\n{content}")


@project_app.command("invalidate")
def invalidate_project(project_id: str) -> None:
    """Force a full project-memory rebuild on the next development run."""
    service = WorkflowService(ConfigManager().load())
    try:
        service.projects.invalidate(project_id)
    except KeyError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    print(f"Project {project_id} will be fully analyzed on its next run.")


@project_app.command("forget")
def forget_project(project_id: str, yes: bool = False) -> None:
    """Delete one project's generated memory and cached mirror."""
    service = WorkflowService(ConfigManager().load())
    try:
        project = service.projects.require(project_id)
    except KeyError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    print(f"Project: {project.repository_url}")
    print("This removes generated memory and the local Git mirror, but not run reports or source repositories.")
    if not yes and not typer.confirm("Forget this project?"):
        print("Cancelled.")
        raise typer.Exit(code=0)
    service.projects.forget(project_id)
    print(f"Forgot project {project_id}.")


@project_app.command("export-instructions")
def export_project_instructions(
    project_id: str,
    repository: str = typer.Option(..., "--repository", help="Target Git repository path"),
    target: str = typer.Option(..., "--target", help="codex, claude, or cursor"),
) -> None:
    """Export reviewed project memory as a native agent instruction file without overwriting existing files."""
    service = WorkflowService(ConfigManager().load())
    try:
        output = service.projects.export_instructions(project_id, repository, target)
    except (KeyError, ValueError, FileExistsError) as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    print(f"Created {output}. Review it before committing.")

ENGINE_CHOICES = [
    ("claude_code", "Claude Code", "使用 claude CLI 开发"),
    ("codex", "Codex", "使用 codex exec 开发"),
    ("cursor", "Cursor", "使用 cursor-agent 开发"),
]


def _is_placeholder(value: str) -> bool:
    return not value.strip() or "REPLACE_ME" in value


def _prompt_choice(title: str, choices: list[tuple[str, str]], default_value: str) -> str:
    print(f"\n[bold]{title}[/bold]")
    default_index = 1
    for index, (value, label) in enumerate(choices, start=1):
        if value == default_value:
            default_index = index
        marker = " [当前默认]" if value == default_value else ""
        print(f"  {index}. {label}{marker}")
    while True:
        raw = typer.prompt("请输入序号", default=str(default_index))
        try:
            selected_index = int(raw)
        except ValueError:
            print("[yellow]请输入列表中的数字序号。[/yellow]")
            continue
        if 1 <= selected_index <= len(choices):
            return choices[selected_index - 1][0]
        print(f"[yellow]请输入 1 到 {len(choices)} 之间的序号。[/yellow]")


def _workspace_id_from_tapd_url(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.netloc.lower() not in {"tapd.cn", "www.tapd.cn"}:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "tapd_fe" and parts[1].isdigit():
        return parts[1]
    return ""


def _configure_tapd(cfg) -> bool:
    print("\n[bold]配置 TAPD 需求源[/bold]")
    print("支持开放应用 OAuth2 和 API 账号 Basic 两种方式；密钥或口令输入时不会回显。")
    auth_labels = {
        "oauth2": "开放应用 OAuth2（app_id / app_secret，推荐）",
        "basic": "API 账号 Basic（API 账号 / API 口令）",
    }
    current_auth_mode = cfg.tapd.auth_mode if cfg.tapd.auth_mode in auth_labels else "oauth2"
    if _tapd_ready(cfg):
        masked_app_id = f"{cfg.tapd.app_id[:4]}***{cfg.tapd.app_id[-2:]}"
        print(
            f"检测到已有配置：认证={auth_labels[current_auth_mode]}，API={cfg.tapd.base_url}，"
            f"凭据账号={masked_app_id}，workspace_id={cfg.tapd.workspace_id}"
        )
        action = _prompt_choice(
            "TAPD 配置",
            [("reuse", "使用已有配置"), ("replace", "重新配置并覆盖当前配置")],
            "reuse",
        )
        if action == "reuse":
            return False
    selected_auth_mode = _prompt_choice(
        "选择 TAPD 认证方式",
        [("oauth2", auth_labels["oauth2"]), ("basic", auth_labels["basic"])],
        current_auth_mode,
    )
    auth_mode_changed = selected_auth_mode != current_auth_mode
    cfg.tapd.auth_mode = selected_auth_mode
    current_app_id = "" if auth_mode_changed or _is_placeholder(cfg.tapd.app_id) else cfg.tapd.app_id
    current_workspace = "" if _is_placeholder(cfg.tapd.workspace_id) else cfg.tapd.workspace_id
    entered_url = typer.prompt(
        "TAPD API 地址（不是浏览器中的工作空间页面）",
        default=cfg.tapd.base_url,
    ).strip()
    detected_workspace = _workspace_id_from_tapd_url(entered_url)
    if detected_workspace:
        print(
            f"[yellow]检测到这是 TAPD 工作空间网页；已提取 workspace_id={detected_workspace}，"
            "API 地址改为 https://api.tapd.cn。[/yellow]"
        )
        cfg.tapd.base_url = "https://api.tapd.cn"
    else:
        cfg.tapd.base_url = entered_url.rstrip("/")
    if selected_auth_mode == "oauth2":
        account_prompt = "TAPD 开放应用 app_id"
        secret_prompt = "TAPD 开放应用 app_secret"
    else:
        account_prompt = "TAPD API 账号（api_user）"
        secret_prompt = "TAPD API 口令（api_password）"
    cfg.tapd.app_id = typer.prompt(account_prompt, default=current_app_id or None)
    keep_secret = (
        not auth_mode_changed
        and not _is_placeholder(cfg.tapd.app_secret)
        and typer.confirm(f"保留当前已配置的 {secret_prompt}？", default=True)
    )
    if not keep_secret:
        cfg.tapd.app_secret = typer.prompt(secret_prompt, hide_input=True, confirmation_prompt=True)
    cfg.tapd.workspace_id = typer.prompt(
        "TAPD workspace_id（工作空间网页 URL 中 tapd_fe/ 后面的数字）",
        default=detected_workspace or current_workspace or None,
    )
    print(f"[green]已选择认证方式：{auth_labels[selected_auth_mode]}[/green]")
    return True


def _tapd_ready(cfg) -> bool:
    return all(
        not _is_placeholder(value)
        for value in (cfg.tapd.app_id, cfg.tapd.app_secret, cfg.tapd.workspace_id)
    )


def _feishu_ready(cfg) -> bool:
    return feishu_configured(cfg.feishu)


def _configure_feishu(cfg) -> bool:
    print("\n[bold]配置飞书需求源[/bold]")
    print("使用飞书自建应用读取文档；App Secret 输入时不会回显。")
    if _feishu_ready(cfg):
        action = _prompt_choice(
            "飞书配置",
            [("reuse", "使用已有配置"), ("replace", "重新配置并覆盖当前配置")],
            "reuse",
        )
        if action == "reuse":
            return False
    document_url = typer.prompt(
        "飞书文档、知识库、多维表格或电子表格链接",
        default=cfg.feishu.document_url or None,
    ).strip()
    current_app_id = cfg.feishu.app_id if not _is_placeholder(cfg.feishu.app_id) else ""
    app_id = typer.prompt("飞书 App ID", default=current_app_id or None).strip()
    keep_secret = (
        not _is_placeholder(cfg.feishu.app_secret)
        and typer.confirm("保留当前已配置的飞书 App Secret？", default=True)
    )
    app_secret = cfg.feishu.app_secret if keep_secret else typer.prompt(
        "飞书 App Secret", hide_input=True, confirmation_prompt=True
    )
    profile = build_source_profile(
        profile_name="飞书默认配置",
        source="feishu",
        existing=None,
        auth_mode="tenant",
        app_id=app_id,
        app_secret=app_secret,
        document_url=document_url,
        resource_type="auto",
        parse_mode="auto",
    )
    cfg.feishu = profile.feishu
    print("[green]飞书自建应用配置已完成。[/green]")
    return True


def _ensure_source_ready(manager: ConfigManager, cfg) -> None:
    if (
        cfg.source == "mock"
        or (cfg.source == "tapd" and _tapd_ready(cfg))
        or (cfg.source == "feishu" and _feishu_ready(cfg))
    ):
        return
    if not sys.stdin.isatty():
        label = "飞书" if cfg.source == "feishu" else "TAPD"
        raise typer.BadParameter(
            f"{label} 尚未配置。请先运行 req2code setup，配置文件位置：{manager.path.resolve()}"
        )
    label = "飞书" if cfg.source == "feishu" else "TAPD"
    print(f"[yellow]检测到 {label} 需求源尚未配置。[/yellow]")
    if not typer.confirm("是否现在配置并保存？", default=True):
        raise typer.Exit(code=0)
    _configure_feishu(cfg) if cfg.source == "feishu" else _configure_tapd(cfg)
    manager.save(cfg)
    print(f"[green]TAPD 配置已保存：{manager.path.resolve()}[/green]")


def _choose_engine(manager: ConfigManager, cfg, ask_to_save: bool = True) -> str:
    choices: list[tuple[str, str]] = []
    print("\n[bold]选择本次开发引擎[/bold]")
    for name, label, description in ENGINE_CHOICES:
        check = inspect_engine(cfg, name)
        choices.append((name, f"{label} — {description}（{check.detail}）"))
    while True:
        selected = _prompt_choice("开发引擎", choices, cfg.engines.active)
        selected_config = runner_config(cfg, selected)
        check = inspect_engine(cfg, selected)
        command_changed = False
        if check.ok:
            break
        print(f"[yellow]{check.detail}。当前命令：{selected_config.command}[/yellow]")
        print("这里配置的是 CLI 可执行命令或自定义 wrapper，不是模型名称。")
        if not check.installed and typer.confirm(
            "是否指定已安装 CLI 的完整路径或自定义 wrapper？",
            default=False,
        ):
            selected_config.command = typer.prompt(
                "命令模板（例如 codex exec --json --sandbox workspace-write -）",
                default=selected_config.command,
            )
            command_changed = True
            check = inspect_engine(cfg, selected)
        if check.ok:
            break
        if command_changed:
            manager.save(cfg)
        if typer.confirm("该引擎仍不可用，是否返回引擎列表重新选择？", default=True):
            continue
        raise typer.BadParameter(check.detail)

    should_save = command_changed
    if ask_to_save and selected != cfg.engines.active:
        should_save = typer.confirm(f"是否把 {selected} 保存为以后默认引擎？", default=True)
    if should_save:
        cfg.engines.active = selected
        manager.save(cfg)
        print(f"[green]默认引擎已保存：{selected}（{manager.path.resolve()}）[/green]")
    return selected


def _choose_model(manager: ConfigManager, cfg, engine: str, ask_to_save: bool = True) -> str:
    selected_config = runner_config(cfg, engine)
    current = (selected_config.model or "").strip()
    choices = [("", "使用该 CLI / 当前账号的默认模型")]
    if current:
        choices.append((current, f"已保存模型：{current}"))
    choices.append(("__custom__", "输入其他模型 ID"))
    selected = _prompt_choice(f"{engine} 模型", choices, current)
    if selected == "__custom__":
        selected = typer.prompt("模型 ID（例如模型全名或 CLI 支持的别名）").strip()
        if not selected:
            raise typer.BadParameter("模型 ID 不能为空")
    if any(character.isspace() for character in selected):
        raise typer.BadParameter("模型 ID 不能包含空白字符")

    if ask_to_save and selected != current:
        display = selected or "CLI 默认模型"
        if typer.confirm(f"是否把 {display} 保存为 {engine} 的默认模型？", default=True):
            selected_config.model = selected
            manager.save(cfg)
            print(f"[green]默认模型已保存：{display}（{manager.path.resolve()}）[/green]")
    return selected


@app.command("setup")
def setup_wizard(
    legacy_engines: bool = typer.Option(
        False,
        "--legacy-engines",
        help="Also configure nested Claude/Codex/Cursor CLI execution (compatibility mode).",
    ),
) -> None:
    """Configure a work-item source, Git, tests, and approval for current-agent workflows."""
    manager = ConfigManager()
    cfg = manager.load()
    print("[bold]Req2Code 首次配置向导[/bold]")
    print(f"配置将保存到：{manager.path.resolve()}")
    cfg.source = _prompt_choice(
        "选择需求来源",
        [
            ("tapd", "TAPD（真实需求和 Bug）"),
            ("feishu", "飞书（文档、表格和多维表格）"),
            ("mock", "Mock（仅用于本地演示）"),
        ],
        cfg.source,
    )
    if cfg.source == "tapd":
        _configure_tapd(cfg)
        sync_legacy_source_profile(cfg)
        manager.save(cfg)
        print(f"[green]TAPD 配置已立即保存：{manager.path.resolve()}[/green]")
    elif cfg.source == "feishu":
        _configure_feishu(cfg)
        sync_legacy_source_profile(cfg)
        manager.save(cfg)
        print(f"[green]飞书配置已立即保存：{manager.path.resolve()}[/green]")
    else:
        sync_legacy_source_profile(cfg)
    if legacy_engines:
        print("\n[yellow]正在配置兼容用的嵌套智能体 CLI；默认 Skill/MCP 流程不需要它。[/yellow]")
        cfg.engines.active = _choose_engine(manager, cfg, ask_to_save=False)
        runner_config(cfg, cfg.engines.active).model = _choose_model(
            manager, cfg, cfg.engines.active, ask_to_save=False
        )

    print("\n[bold]配置 Git 默认值[/bold]")
    cfg.git.remote_name = typer.prompt("默认远程名称", default=cfg.git.remote_name)
    cfg.git.base_branch = typer.prompt("默认基线分支", default=cfg.git.base_branch)
    cfg.git.target_branch = cfg.git.base_branch
    cfg.git.branch_prefix = typer.prompt("自动生成开发分支的前缀", default=cfg.git.branch_prefix)
    cfg.git.commit_author = typer.prompt("审批后提交的作者名称", default=cfg.git.commit_author)
    cfg.git.commit_email = typer.prompt("审批后提交的作者邮箱", default=cfg.git.commit_email)

    print("\n[bold]配置测试命令[/bold]")
    cfg.testing.unit_command = typer.prompt("单元测试命令", default=cfg.testing.unit_command)
    cfg.testing.coverage_command = typer.prompt("覆盖率命令", default=cfg.testing.coverage_command)
    cfg.testing.min_coverage = typer.prompt("最低覆盖率百分比", default=cfg.testing.min_coverage, type=float)

    if legacy_engines:
        print("\n[bold]配置兼容模式的项目记忆与上下文复用[/bold]")
        cfg.project_memory.enabled = typer.confirm("启用按 Git SHA 校验的项目记忆？", default=cfg.project_memory.enabled)
    if legacy_engines and cfg.project_memory.enabled:
        cfg.project_memory.max_context_chars = typer.prompt(
            "每次最多注入的项目记忆字符数",
            default=cfg.project_memory.max_context_chars,
            type=int,
        )
        cfg.project_memory.generate_candidate = typer.confirm(
            "测试通过后生成候选记忆？", default=cfg.project_memory.generate_candidate
        )
        cfg.project_memory.promote_after_approval = typer.confirm(
            "批准并推送后晋升候选记忆？", default=cfg.project_memory.promote_after_approval
        )
        cfg.project_memory.use_mirror_cache = typer.confirm(
            "远程仓库使用项目级 bare mirror 缓存？", default=cfg.project_memory.use_mirror_cache
        )
        cfg.project_memory.resume_engine_sessions = typer.confirm(
            "同一次 run 内复用支持恢复的引擎会话？", default=cfg.project_memory.resume_engine_sessions
        )

    if _is_placeholder(cfg.review.callback_secret):
        cfg.review.callback_secret = secrets.token_urlsafe(32)
        print("已自动生成审批回调密钥。")
    cfg.review.approval_base_url = typer.prompt("审核页面地址", default=cfg.review.approval_base_url)
    sync_legacy_source_profile(cfg)
    manager.save(cfg)
    print(f"\n[green]配置完成并已保存：{manager.path.resolve()}[/green]")
    print("下一步：连接 Req2Code MCP/Skill，然后在目标项目对话中选择需求平台和工作项。")


@app.command("install-skill")
def install_skill_command(
    host: SkillHost,
    destination: str = typer.Option("", "--destination", help="Override the host's user Skill root directory"),
    force: bool = typer.Option(False, "--force", help="Update an existing Req2Code Skill installation"),
) -> None:
    """Install only the packaged Skill. Prefer `req2code integrate` for normal setup."""
    from req2code.skill_installer import install_skill

    try:
        path = install_skill(host.value, destination=destination or None, overwrite=force)
    except (ValueError, FileExistsError) as exc:
        print(f"[red]Skill installation failed:[/red] {exc}")
        raise typer.Exit(code=2)
    print(f"Installed Req2Code Skill: {path}")
    print("This command installs only the Skill. Run `req2code integrate <host>` to register MCP too.")


@app.command("integrate")
def integrate_command(
    host: SkillHost,
    force: bool = typer.Option(False, "--force", help="Update an existing Req2Code Skill installation"),
    config_path: str = typer.Option("", "--config", help="Req2Code config file created by setup"),
    mcp_executable: str = typer.Option("", "--mcp-executable", help="Override the req2code-mcp executable"),
) -> None:
    """Install the Skill and automatically register Req2Code MCP for a coding host."""
    from req2code.host_integration import integrate_host

    try:
        result = integrate_host(
            host.value,
            config_path=config_path or None,
            executable=mcp_executable or None,
            overwrite_skill=force,
        )
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"[red]Host integration failed:[/red] {exc}")
        raise typer.Exit(code=2)
    print(f"[green]Req2Code integration installed for {result.host}.[/green]")
    print(f"Skill: {result.skill_path}")
    print(f"MCP executable: {result.mcp_executable}")
    print(f"MCP config: {result.mcp_config_path}")
    print(f"Req2Code config: {result.req2code_config_path}")
    if result.backup_path:
        print(f"Previous host config backup: {result.backup_path}")
    if not result.req2code_config_path.exists():
        print(
            "[yellow]Req2Code has no source profile yet. Open the workflow UI to configure one; "
            "`req2code setup` remains an optional terminal fallback.[/yellow]"
        )
    print(result.restart_hint)


def _resolve_items(source, specs: list[str]):
    selected = []
    for spec in specs:
        kind, separator, item_id = spec.partition(":")
        if not separator:
            item_id = kind
            kind = "story"
        kind = kind.lower()
        if kind not in {"story", "bug"}:
            raise typer.BadParameter(f"Invalid item type in {spec}; use story:<id> or bug:<id>")
        if hasattr(source, "get_by_id_with_type"):
            selected.append(source.get_by_id_with_type(item_id, item_type=kind))
        else:
            selected.append(source.get_by_id(item_id))
    return selected


def _interactive_items(source, limit: int = 20):
    if hasattr(source, "fetch_latest_all"):
        candidates = list(source.fetch_latest_all(limit=limit))
    else:
        candidates = list(source.fetch_latest(limit=limit))
    if not candidates:
        raise typer.BadParameter("需求源没有返回可选择的需求或缺陷")
    print("\n[bold]选择本次要解决的需求和 Bug（支持多选）[/bold]")
    for index, item in enumerate(candidates, start=1):
        print(f"{index:>2}. [{item.type.value}] {item.id} {item.title}")
    raw = typer.prompt("请输入序号，多个序号用英文逗号分隔，例如 1,3,5")
    try:
        indexes = [int(value.strip()) for value in raw.split(",") if value.strip()]
        return [candidates[index - 1] for index in indexes if 1 <= index <= len(candidates)]
    except ValueError as exc:
        raise typer.BadParameter("选择内容必须是数字序号") from exc


def _default_work_branch(item_ids: list[str], prefix: str) -> str:
    safe_ids = ["".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") for value in item_ids]
    suffix = safe_ids[0] if len(safe_ids) == 1 else f"batch-{safe_ids[0]}-{len(safe_ids)}"
    return f"{prefix}/{suffix}"[:120]


@app.command("start")
def start_run(
    item_specs: Optional[list[str]] = typer.Option(None, "--item", help="Repeat story:<id> or bug:<id>"),
    local_path: str = typer.Option("", "--local", help="Existing local Git repository"),
    repo_url: str = typer.Option("", "--repo-url", help="Remote Git URL to clone"),
    base_branch: str = typer.Option("", "--base", help="Base branch for a new work branch"),
    work_branch: str = typer.Option("", "--branch", help="Existing or new development branch"),
    push_branch: str = typer.Option("", "--push-branch", help="Remote branch that receives the approved commit"),
    remote: str = typer.Option("", "--remote", help="Git remote name"),
    pull_latest: bool = typer.Option(
        False,
        "--pull",
        help="Before development, fetch and fast-forward the selected local branch (never merges or rebases)",
    ),
    agent_name: str = typer.Option("current_agent", "--agent-name", help="Name recorded for the current coding agent"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Prepare work items for the current coding agent without launching another agent CLI."""
    from req2code.repository import RepositorySpec

    _init_logging()
    manager = ConfigManager()
    cfg = manager.load()
    _ensure_source_ready(manager, cfg)
    source = get_source_connector(cfg)
    selected = _resolve_items(source, list(item_specs or [])) if item_specs else _interactive_items(source, limit)
    if not selected:
        raise typer.BadParameter("至少选择一个需求或缺陷")

    if not local_path and not repo_url:
        local_path = "."
    if local_path and repo_url:
        raise typer.BadParameter("--local 和 --repo-url 只能选择一个")

    base = base_branch.strip()
    branch = work_branch.strip()
    push = push_branch.strip()
    remote_name = remote or cfg.git.remote_name

    print("\n[bold]请确认本次任务准备[/bold]")
    print(f"- 工作项：{', '.join(f'{item.type.value}:{item.id}' for item in selected)}")
    print(f"- 仓库：{local_path or repo_url}")
    print(f"- 分支：{branch or '保持当前本地分支（远程克隆时使用基线/默认分支）'}")
    print(f"- 开发前同步：{'git pull --ff-only' if local_path and pull_latest else ('远程克隆自动获取最新代码' if repo_url else '不修改本地 HEAD')}")
    print(f"- 审批后推送：{remote_name}/{push or branch or '实际工作分支'}")
    print("- 流程：任务简报 -> 当前智能体开发/测试/说明 -> Req2Code 固化报告 -> 人工审批")
    if sys.stdin.isatty() and not typer.confirm("确认准备任务？", default=True):
        print("已取消，本次没有修改仓库。")
        raise typer.Exit(code=0)

    try:
        record = WorkflowService(cfg).begin_agent_run(
            selected,
            RepositorySpec(
                local_path=local_path,
                repo_url=repo_url,
                remote_name=remote_name,
                base_branch=base,
                work_branch=branch,
                push_branch=push,
                sync_before_start=pull_latest,
            ),
            agent_name=agent_name,
        )
    except Exception as exc:
        print(f"[red]Run failed:[/red] {exc}")
        raise typer.Exit(code=1)

    print(f"[bold]Run:[/bold] {record.run_id}")
    print(f"Status: {record.status}")
    if record.preparation_stage:
        print(f"Preparation stage: {record.preparation_stage}")
    print(f"Execution: current agent ({record.engine})")
    print(f"Repository: {record.repo_path}")
    print(f"Pre-development sync: {'requested (fast-forward only)' if record.sync_before_start else 'not requested'}")
    print(f"开发分支: {record.work_branch}")
    print("发布状态: 尚未选择发布；提交与推送保持锁定")
    print("\n[bold]当前代码智能体任务简报[/bold]")
    print(record.task_brief)
    print(f"\n开发完成后调用 MCP finalize_development_run，或运行：req2code finalize {record.run_id}")


@app.command("finalize")
def finalize_run(
    run_id: str,
    summary: str = typer.Option("", "--summary", help="Implementation summary for the review report"),
    plan: str = typer.Option("", "--plan", help="Implementation plan for the review report"),
    test_evidence: str = typer.Option("", "--test-evidence", help="Exact tests run by the current agent and their results"),
    tests_passed: bool = typer.Option(True, "--tests-passed/--tests-failed", help="Whether the current agent's tests passed"),
    coverage: Optional[float] = typer.Option(None, "--coverage", help="Optional coverage percentage reported by the current agent"),
    rerun_tests: bool = typer.Option(False, "--rerun-tests", help="Strict mode: make Req2Code rerun configured checks"),
) -> None:
    """Record the current agent's result, validate Git state, and stop for human approval."""
    cfg = ConfigManager().load()
    if not summary and sys.stdin.isatty():
        summary = typer.prompt("实现摘要")
    if not test_evidence and sys.stdin.isatty() and not rerun_tests:
        test_evidence = typer.prompt("测试命令与结果")
    if not summary:
        raise typer.BadParameter("--summary is required in non-interactive mode")
    if not test_evidence and not rerun_tests:
        raise typer.BadParameter("--test-evidence is required unless --rerun-tests is used")
    try:
        record = WorkflowService(cfg).finalize_agent_run(
            run_id,
            implementation_plan=plan,
            implementation_summary=summary,
            test_evidence=test_evidence,
            tests_passed=tests_passed,
            coverage=coverage,
            rerun_configured_tests=rerun_tests,
        )
    except Exception as exc:
        print(f"[red]收尾失败，可修复问题后重试：[/red] {exc}")
        raise typer.Exit(code=1)
    print(f"运行: {record.run_id}")
    print(f"状态: {record.status}")
    print(f"变更文件: {len(record.changed_files)}")
    print(f"中文审核报告: {record.report_path}")
    print(record.approval_comment)
    if record.status == "waiting_approval":
        print("当前没有提交或推送，推送仍处于锁定状态。")
        print(f"审批页面: {WorkflowService(cfg).approval_url(record)}")
        print(f"人工审核通过后运行: req2code approve {record.run_id}")


@app.command("verify")
def verify_run(
    run_id: str,
    summary: str = typer.Option("", "--summary", help="Implementation summary for the review report"),
    plan: str = typer.Option("", "--plan", help="Implementation plan for the review report"),
    test_evidence: str = typer.Option("", "--test-evidence", help="Tests already run by the current agent"),
) -> None:
    """Compatibility strict mode: rerun configured checks and stop for human approval."""
    cfg = ConfigManager().load()
    if not summary and sys.stdin.isatty():
        summary = typer.prompt("实现摘要")
    if not summary:
        raise typer.BadParameter("--summary is required in non-interactive mode")
    try:
        record = WorkflowService(cfg).verify_agent_run(
            run_id,
            implementation_plan=plan,
            implementation_summary=summary,
            test_evidence=test_evidence,
        )
    except Exception as exc:
        print(f"[red]Verification failed:[/red] {exc}")
        raise typer.Exit(code=1)
    print(f"Run: {record.run_id}")
    print(f"Status: {record.status}")
    print(f"Changed files: {len(record.changed_files)}")
    print(f"中文审核报告: {record.report_path}")
    print(record.approval_comment)
    if record.status == "waiting_approval":
        print("当前没有提交或推送，推送仍处于锁定状态。")
        print(f"审批页面: {WorkflowService(cfg).approval_url(record)}")
        print(f"人工审核通过后运行: req2code approve {record.run_id}")


@app.command("runs")
def list_runs(limit: int = 20) -> None:
    """List recent workflow runs."""
    cfg = ConfigManager().load()
    for record in WorkflowService(cfg).runs.list(limit=limit):
        ids = ",".join(item["id"] for item in record.work_items)
        engine_model = f"{record.engine}/{record.model}" if record.model else record.engine
        print(
            f"{record.run_id} [{record.status}] {record.execution_mode}:{engine_model} "
            f"{ids} -> {record.remote_name}/{record.push_branch}"
        )


@app.command("status")
def run_status(run_id: str, raw: bool = False) -> None:
    """Show a persisted workflow run and its report."""
    cfg = ConfigManager().load()
    try:
        record = WorkflowService(cfg).runs.require(run_id)
    except KeyError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    if raw:
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        return
    print(f"Run: {record.run_id}")
    print(f"Status: {record.status}")
    if record.preparation_stage:
        print(f"Preparation stage: {record.preparation_stage}")
    print(f"Items: {', '.join(item['id'] for item in record.work_items)}")
    print(f"Execution mode: {record.execution_mode}")
    print(f"Engine: {record.engine}")
    print(f"Model: {record.model or '(CLI default)'}")
    print(f"Engine session: {record.engine_session_id or '(not resumable)' }")
    print(f"Project memory: {record.project_id or '(none)'} revision {record.project_memory_revision}")
    print(f"Repository: {record.repo_path}")
    print(f"Pre-development sync: {'requested (fast-forward only)' if record.sync_before_start else 'not requested'}")
    print(f"Branch: {record.work_branch} ({record.branch_mode})")
    if record.status == "completed":
        print(f"实际发布分支: {record.remote_name}/{record.push_branch}")
    else:
        print("当前发布状态: 尚未提交或推送；发布分支在确认发布时显示")
    print(f"报告: {record.report_path}")
    print(f"提交: {record.commit_sha or '(尚未提交)'}")
    if record.test_result:
        source = record.test_result.get("source", "legacy_verification")
        coverage = record.test_result.get("coverage")
        coverage_text = "not reported" if coverage is None else f"{float(coverage):.1f}%"
        if source == "current_coding_agent":
            print(
                "Tests: "
                f"{'passed' if record.test_result.get('passed') else 'failed'} "
                f"(reported by current coding agent), coverage={coverage_text}"
            )
        else:
            print(
                "Tests: "
                f"unit={'passed' if record.test_result.get('unit_passed') else 'failed'}, "
                f"script={'passed' if record.test_result.get('script_passed') else 'failed'}, "
                f"coverage={coverage_text}, source={source}"
            )
    if record.status == "waiting_approval":
        print(f"Approval page: {WorkflowService(cfg).approval_url(record)}")
    if record.error:
        print(f"Error: {record.error}")


@app.command("approve")
def approve_run(run_id: str, comment: str = "", yes: bool = False) -> None:
    """After human review, commit and push exactly the reported change set."""
    cfg = ConfigManager().load()
    service = WorkflowService(cfg)
    record = service.runs.require(run_id)
    print(f"审核报告: {record.report_path}")
    print(f"审批通过后的预定推送分支: {record.remote_name}/{record.push_branch}")
    print("当前仍未提交或推送。")
    print(f"Changed files: {len(record.changed_files)}")
    if not yes and not typer.confirm("Approve commit and push?"):
        print("Approval cancelled.")
        raise typer.Exit(code=0)
    try:
        record = service.approve_and_publish(run_id, comment=comment)
    except Exception as exc:
        print(f"[red]Publish failed:[/red] {exc}")
        raise typer.Exit(code=1)
    print(f"Pushed commit {record.commit_sha} to {record.remote_name}/{record.push_branch}")


@app.command("reject")
def reject_run(run_id: str, comment: str = "") -> None:
    """Reject a waiting change set without committing or pushing it."""
    cfg = ConfigManager().load()
    try:
        record = WorkflowService(cfg).reject(run_id, comment=comment)
    except Exception as exc:
        print(f"[red]Reject failed:[/red] {exc}")
        raise typer.Exit(code=1)
    print(f"Run {record.run_id} rejected. No commit or push was performed.")

if __name__ == "__main__":
    app()
