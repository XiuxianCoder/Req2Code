# Req2Code 测试指南

[English](TESTING.md) | [简体中文](TESTING.zh-CN.md)

测试分为三层：第一层不需要外部服务或代码智能体；第二层用一次性本地 Git remote 验证“当前智能体直接开发”流程；第三层再接入测试 TAPD 和测试 Git 仓库。

## 第一层：自动化测试

### 推荐使用 uv

```powershell
uv sync --extra test
uv run python -m compileall -q req2code tests scripts
uv run python -m pytest -q
node tests/selector_ui_harness.js
node tests/launcher_ui_harness.js
node tests/feishu_analysis_ui_harness.js
uv run req2code --version
uv run req2code start --help
uv run req2code finalize --help
uv run req2code verify --help
uv run req2code install-skill --help
```

uv 管理的 `.venv` 可能没有 `pip`，这是正常情况。请使用 `uv sync`、`uv run` 或 `uv pip`。

### 已经激活虚拟环境

```powershell
.\.venv\Scripts\Activate.ps1
python -m compileall -q req2code tests scripts
python -m pytest -q
req2code --version
```

测试使用 Mock 数据和本地 bare Git 仓库，会检查：分支留空时保持当前分支、自动生成当前智能体任务简报、默认直接固化智能体测试证据而不重复测试、可选严格复跑、阻止智能体提交和推送、过期现场识别、拒绝流程，以及人工批准后的发布。

三个 Node 脚本分别验证旧选择会话兼容性、“首次配置后直接选择工作项”流程，以及飞书 AI 字段分析往返，并确认发给智能体的消息不包含凭据。

## 第二层：Mock 当前智能体完整流程

此测试不连接 TAPD，即使批准也只会推送到 `.demo/` 内的一次性本地 bare 仓库。

### 1. 创建隔离配置

```powershell
$env:REQ2CODE_CONFIG = Join-Path $PWD ".demo-config.yaml"
req2code setup
```

需求来源选择 **Mock**，演示测试命令保留：

- 单元测试：`python -m pytest -q`
- 覆盖率：`python -m coverage run -m pytest -q && python -m coverage report`
- 最低覆盖率：`80`

正常 setup 不应再要求选择代码智能体或模型。

```powershell
req2code fetch --item-type all --limit 10
req2code doctor
```

应看到 `DEMO-STORY-1` 和 `DEMO-BUG-1`。

### 2. 创建一次性仓库

```powershell
python scripts/create_demo_repository.py --output .demo
```

脚本不会覆盖已有目录。

### 3. 在代码智能体中打开目标项目

用 Codex、Claude Code 或 Cursor 打开 `.demo/work`，确认 Req2Code MCP 已启用，然后调用 Skill 并选择 `DEMO-STORY-1`。也可以先用 CLI 准备：

```powershell
req2code start --item story:DEMO-STORY-1 --local .demo/work
```

不要传 `--branch`。预期：

- 仍然停留在 `main`，不新建也不切换分支；
- 不启动第二个代码智能体 CLI；
- run 状态为 `developing`；
- 任务简报要求当前智能体增加 `multiply(a, b)`、执行测试、整理结果，并调用 `finalize_development_run`；
- remote 的 push URL 被临时禁用。

让当前智能体完成开发、相关测试和失败修复，并整理实现与测试说明，然后通过 MCP 调用 `finalize_development_run`。CLI 备用命令：

```powershell
req2code finalize <run_id> `
  --plan "增加乘法及回归测试" `
  --summary "实现 multiply 并补充测试" `
  --test-evidence "python -m pytest -q：全部通过" `
  --tests-passed
```

预期收尾结果：

- 状态变成 `waiting_approval`；
- 报告保存当前智能体的准确测试证据，并明确说明 Req2Code 没有复跑配置测试；
- Markdown 报告包含工作项、方案、实现摘要、变更文件和测试日志；
- `git -C .demo/work log -1 --oneline` 仍显示 `Initial demo`；
- 没有发生推送。

### 4. 审核、拒绝或批准

```powershell
req2code runs
req2code status <run_id>
git -C .demo/work diff
```

安全测试拒绝：

```powershell
req2code reject <run_id> --comment "演示拒绝"
```

若要测试批准，请重新准备并收尾一个新 run，审核后运行：

```powershell
req2code approve <run_id>
req2code status <run_id>
git --git-dir=.demo/remote.git log --oneline --all --decorate
```

预期：run 为 `completed`，审核过的提交存在于本地 bare remote，并且没有强制推送。

## 第三层：TAPD 与测试 Git 联调

1. 用 `REQ2CODE_CONFIG` 指向测试环境专用配置。
2. 打开 `req2code-workflow`，在私有界面中新增带名称的 TAPD 项目，并按实际凭据选择“开放应用 OAuth2”或“API 账号 Basic”；宿主不支持 MCP Apps 时才在私密终端使用 `req2code setup`。
3. 确认界面同时通过需求与缺陷接口验证；还可运行 `req2code doctor`、`req2code fetch` 和 `req2code show` 再检查一次只读访问。
4. 在代码智能体中打开非生产目标仓库。
5. 通过 Skill/MCP 选择一个低风险工作项。
6. 先在已经检出的安全 feature 分支验证“不填分支”。
7. 再验证明确指定的新分支。
8. 选择两个工作项共用一个分支，验证批量场景。
9. 使用明确的 base/work 分支验证远程克隆模式。
10. 每次批准前检查报告和 diff，批准后确认远程 SHA。

第一次联调不要使用生产分支。

## Skill 和 MCP 检查

```powershell
python C:\path\to\skill-creator\scripts\quick_validate.py integrations\codex\skills\req2code-workflow
req2code-mcp
```

MCP 会等待 stdio 输入，可按 `Ctrl+C` 停止。代码智能体中应能看到这些可调用流程工具：

- `render_req2code_launcher`
- `submit_feishu_table_analysis`（仅用于用户明确授权的多维表格分析）
- `prepare_development_run`
- `finalize_development_run`
- `verify_development_run`
- `get_run`

必须确认配置、候选项加载、选择确认、审核和发布工具均标记为应用私有，代码模型不能主动选择调用。

## 打包检查

```powershell
uv build
uv run python -c "import req2code.mcp_server; print('MCP import OK')"
```

把 wheel 安装到一次性环境，再确认 `req2code` 和 `req2code-mcp` 都存在。

## 常见问题

| 现象 | 检查内容 |
| --- | --- |
| `.venv` 没有 pip | 使用 `uv sync --extra test`，这不代表 uv 环境损坏。 |
| setup 还在询问引擎 | 正常流程不应询问；删除 `--legacy-engines` 并确认版本为 0.5+。 |
| 启动时提示仓库不干净 | 先处理已有变更；Req2Code 不会用 stash/reset 隐藏它们。 |
| 准备任务看起来很慢 | 查询 `list_runs`；`preparing` 记录会显示阶段，Git 也会在配置时限后返回错误，不要重复提交同一请求。 |
| 本地代码不是最新 | 明确同意同步或使用 `req2code start --pull`；Req2Code 不会静默 pull。 |
| 分支发生意外变化 | 只有希望保持本地当前分支时才省略 `--branch`。 |
| 覆盖率显示“未报告” | 当前智能体获得覆盖率时，通过 `coverage` / `--coverage` 一并上报。 |
| 收尾返回 `changes_requested` | 修复报告中的实现/测试问题，再调用 `finalize_development_run`。 |
| run 变成 `stale` | 分支、HEAD、remote、远程 SHA 或审核 diff 已变化，应重新准备 run。 |
| 审核页面打不开 | 启动 `req2code serve-approval` 并检查 `review.approval_base_url`。 |
