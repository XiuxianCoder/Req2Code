# Req2Code 使用指南

[English](USAGE.md) | [简体中文](USAGE.zh-CN.md) | [返回 README](../README.zh-CN.md)

Req2Code 的推荐定位是“需求开发流程编排器”：它负责从 TAPD 或飞书获取需求和 Bug、让用户选择工作项、整理目标任务、保护 Git 现场、保存开发测试结果并生成审核报告。当前打开项目的 Codex、Claude Code 或 Cursor 负责理解项目、修改代码、执行测试和修复失败。

默认流程不会启动第二个代码智能体进程，也不会在人工批准前提交或推送。

## 推荐接入方式

| 使用环境 | 推荐方式 | 模型在哪里选择 |
| --- | --- | --- |
| Codex 桌面版 | Req2Code Skill + MCP；内嵌 UI 已验证 | Codex 自己的模型设置 |
| Codex CLI | Req2Code Skill + MCP；终端文字降级 | Codex 自己的模型设置 |
| Claude Code | Req2Code Skill + MCP；文字/外部 UI 降级 | Claude Code 自己的模型设置 |
| Cursor | Req2Code Skill + MCP；MCP Apps 需要 Cursor 2.6+ | Cursor 自己的模型设置 |
| 纯终端或 MCP 不可用 | Req2Code CLI | 当前代码智能体负责开发 |

Req2Code 不需要在正常配置中再次选择 Codex、Claude Code、Cursor 或模型。只有旧版嵌套 CLI 兼容模式才需要配置引擎。

## 1. 安装项目

GitHub 普通用户安装：

```powershell
uv tool install "git+https://github.com/XiuxianCoder/Req2Code.git"
req2code --version
```

项目贡献者安装：

```powershell
git clone https://github.com/XiuxianCoder/Req2Code.git
cd Req2Code
uv sync --extra test

uv run req2code --version
uv run python -m pytest -q
```

如果已经激活 `.venv`，也可以直接使用 `req2code`。uv 管理的虚拟环境可能没有 pip，这是正常情况；更新依赖应使用 `uv sync` 或 `uv pip`。

## 2. 配置需求来源

正常流程无需先在终端配置。安装宿主集成后启动 `req2code-workflow`，私有启动界面会先让用户选择 TAPD、飞书或 Mock，再新增或复用该平台下的命名配置，验证连接并继续选择工作项。TAPD 支持：

- 开放应用 OAuth2：输入 `app_id`、`app_secret` 和工作空间；
- API 账号 Basic：输入 `api_user`、`api_password` 和工作空间。

飞书使用 App ID/App Secret 自建应用。支持 `/docx/` 文档、`/wiki/` 知识库节点、`/base/` 多维表格和 `/sheets/` 电子表格；普通文档可按原生表格行、标题章节或整篇解析，多维表格按记录解析，电子表格按首个非空表头行解析。链接中的 `table`、`view`、`sheet` 参数会自动读取，也可以在配置中覆盖。对于多维表格，可点击“读取数据表”选择准确的数据表和视图；Req2Code 会保留视图用于配置展示和溯源，但读取记录时忽略该视图自带的筛选条件。点击“AI 解析并选择工作项”后，由当前智能体识别不固定字段以及单选/多选列的全部配置项，Req2Code 再在本地过滤待处理记录。

飞书应用需要开通相应的文档只读权限，而且目标文档必须对该应用身份可访问。Req2Code 会在保存配置前实际验证读取权限。

只在 Req2Code 私有表单中输入这些信息。它们会交给应用私有的本机 MCP 工具，不会插入代码智能体聊天内容。你在 TAPD 创建的是开放应用时必须选择 OAuth2；选择 Basic 会把应用凭据误当成 API 账号并导致 403。

配置读取顺序：

1. `REQ2CODE_CONFIG` 指定的配置文件；
2. 当前目录的 `.req2code/config.yaml`；
3. 用户目录的 `~/.req2code/config.yaml`。

宿主不支持 MCP Apps 时，仍可使用私密终端降级：

```powershell
uv run req2code setup
uv run req2code doctor
```

## 3. 一键安装宿主集成

```powershell
req2code integrate codex
# 或：req2code integrate claude
# 或：req2code integrate cursor
```

这条命令会安装宿主的用户级 Skill，并使用绝对路径注册 stdio MCP 及 Req2Code 私密配置文件。它会保留其他 MCP；直接修改 Codex/Cursor 配置前会生成 `*.req2code.bak`。更新已有 Skill 时使用 `--force`；需要指定非默认本地配置文件时使用 `--config <路径>`，该文件可以稍后由私有界面创建。

安装后重启 Codex/Cursor 或新建 Agent 任务/对话；Claude Code 请新开会话。模型应能看到 `render_req2code_launcher`、`prepare_development_run`、`finalize_development_run` 和 `get_run`。配置、候选项加载、选择确认、审核与发布仍属于私有 UI 动作；`submit_feishu_table_analysis` 只是用于回传用户明确授权的多维表格字段分析 JSON。

自定义集成时仍可只安装 Skill：

```powershell
req2code install-skill codex
# 或：req2code install-skill claude
# 或：req2code install-skill cursor
```

## 4. 在目标项目中开始任务

在需要开发的目标项目中打开 Codex、Claude Code 或 Cursor，然后输入：

```text
使用 req2code-workflow，打开 Req2Code，让我选择需求平台和需要解决的工作项。
```

代码智能体会通过 MCP：

1. 只调用一次 `render_req2code_launcher`；
2. 私有界面让用户新增或选择带名称的平台/项目配置；多维表格只有在用户明确点击 AI 解析后，才自动发送一条仅含分析 ID 的短消息，智能体再通过 `get_feishu_table_analysis_task` 取得字段名/类型、选择列全部配置项和少量样例值，不把大段载荷或 MCP App 上下文附件放进输入框；收到映射 JSON 后会在当前对话位置打开新的选择器，由 Req2Code 在本地识别需求/缺陷、过滤终态并展示关键字段；明显属于封面或使用说明的数据表会在分析前被拦截；
3. 凭据、配置详情和完整未确认行只存在于组件私有数据中；用户确认后，自动发送一条只包含已选工作项完整内容、默认流程、执行要求和审批边界的自包含开发任务；
4. 若用户未在打开选择器前指定覆盖项，默认使用当前项目、保持当前分支并且不 pull，不再重复询问；
5. 用户预先指定本地路径、远程 URL、分支或 pull 时按其选择执行；
6. 使用 `selection_id` 只调用一次 `prepare_development_run`；
7. 获得包含完整来源内容、验收范围、测试要求、报告要求和安全边界的 `task_brief`，随后当前智能体直接开发和测试。

`task_brief` 包含所选需求/Bug 的字段、完整说明和验收内容，以及仓库路径、工作分支、基线 SHA、开发测试与逐工作项审核要求和禁止提前提交/推送等安全规则。人工完成审核和第二次发布确认以前，推送始终锁定。准确发布分支只在第二次发布确认中显示。Codex 是当前已验证的 UI 参考宿主；Cursor 2.6+ 官方支持 MCP Apps，但仍需做 Req2Code 发布实测；Claude Code 官方没有保证相同的自定义 HTML 界面，因此使用文字报告或外部审核页降级。

## 5. 仓库与分支选择

| 输入方式 | 行为 |
| --- | --- |
| 不填写仓库 | 使用代码智能体当前打开的项目 |
| `local_path` | 直接在指定的干净本地 Git 仓库开发 |
| `repo_url` | Req2Code 克隆到独立托管工作区后开发 |
| 本地仓库不填写分支 | 保持当前分支，不创建也不切换分支 |
| 明确指定分支 | 所有选中的需求/Bug 共用该分支 |
| 本地仓库且同意同步 | 先 fetch；远程存在该分支时执行 `git pull --ff-only` |
| 本地仓库且不同步 | 不进行网络更新，也不修改本地 HEAD |
| 不填写推送分支 | 审批后推送到实际工作分支 |

一个需求/Bug 一个分支是推荐默认值，但 Req2Code 支持多个工作项有意共用一个分支。

任务会话会在 Git 校验前写入状态目录。如果 Git 凭据或网络操作超时，应通过 `list_runs` / `get_run` 查看阶段和错误，不要反复提交相同准备请求。`git.command_timeout_seconds` 默认是 120 秒。

CLI 备用示例：

```powershell
# 当前项目、当前分支
req2code start --item story:101 --item bug:202 --local .

req2code start --item bug:202 --local . --pull

# 当前项目、指定共享分支
req2code start --item story:101 --item bug:202 --local . `
  --base develop --branch feature/sprint-08 --push-branch feature/sprint-08

# 克隆远程仓库
req2code start --item bug:202 `
  --repo-url https://git.example.com/team/service.git `
  --base develop --branch fix/tapd-202
```

## 6. 开发、测试与收尾

当前代码智能体负责：

1. 阅读 `task_brief` 和目标项目说明；
2. 分析影响范围并制定实现方案；
3. 完成全部选中需求/Bug；
4. 添加或修改相关测试；
5. 执行测试、Lint、构建等适用检查；
6. 修复失败，直到达到可审核状态；
7. 为每个已选工作项分别整理解决方案/根因、实际修改、关联文件、测试证据、验收结论和剩余风险。

完成后，代码智能体调用：

```text
finalize_development_run(
  run_id,
  implementation_plan,
  implementation_summary,
  test_evidence,
  tests_passed,
  coverage,
  item_results
)
```

`item_results` 必须覆盖每个已选工作项 ID。默认情况下 Req2Code 不重复执行测试，而是保存智能体的测试证据、重新检查分支和基线、计算 diff 指纹、生成 Markdown 审计快照、自动打开中文审核 UI 并进入 `waiting_approval`。

CLI 备用方式：

```powershell
req2code finalize <run_id> `
  --plan "实现方案" `
  --summary "完成的代码变更" `
  --test-evidence "python -m pytest -q：72 passed" `
  --tests-passed `
  --coverage 92.5
```

需要 Req2Code 独立复跑配置测试时，使用：

```powershell
req2code finalize <run_id> `
  --summary "完成的代码变更" `
  --test-evidence "当前智能体的测试结果" `
  --rerun-tests
```

`req2code verify` 和 MCP `verify_development_run` 是严格复跑模式的兼容入口。

## 7. 人工审核与发布

状态进入 `waiting_approval` 后，Req2Code 自动打开逐工作项审核 UI。当前智能体只需说明结果已等待审核且当前没有提交或推送，然后停止，不应在聊天中重复粘贴整份报告或发布分支。

用户先点击“审核通过，进入发布确认”，该动作不执行 Git 操作；第二个确认框才显示准确发布分支，并在 `main`/`master` 时给出警告。勾选确认后点击“确认提交并推送”，服务端重新校验当前分支、基线 SHA、远程地址、diff 指纹和远程分支 SHA，全部一致才提交并执行非强制推送。点击“要求继续修改”则退回 `changes_requested` 并将意见发送给当前代码智能体。

查看现场：

```powershell
req2code runs
req2code status <run_id>
git diff
```

可选的本地审核页面：

```powershell
req2code serve-approval --host 127.0.0.1 --port 8088
```

审核不通过：

```powershell
req2code reject <run_id> --comment "需要补充边界测试"
```

审核通过后，由人明确运行：

```powershell
req2code approve <run_id>
```

批准时 Req2Code 会重新校验分支、基线 HEAD、remote URL、diff 指纹和远程目标分支 SHA。校验一致才会创建提交并执行非强制推送；任何现场变化都会让 run 变成 `stale`，不会强行提交或推送。

## 完整对话示例

```text
用户：使用 req2code-workflow，列出 TAPD 需求和 Bug。
智能体：展示工作项，并询问选择哪些、使用哪个仓库和分支。
用户：选择 story:101 和 bug:202，使用当前项目和当前分支。
智能体：调用 prepare_development_run，读取 task_brief，完成开发和测试。
智能体：调用 finalize_development_run，展示报告，并说明尚未提交或推送。
用户：审核 diff 和报告后，明确批准 run。
用户/终端：运行 req2code approve <run_id>。
Req2Code：重新校验现场，提交并推送到报告中的目标分支。
```
