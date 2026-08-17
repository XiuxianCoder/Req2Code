# Contributing to Req2Code / 参与 Req2Code 开发

## English

Thank you for improving Req2Code. Keep changes focused and preserve the human approval boundary.

1. Create a topic branch from the repository's default branch.
2. Install development dependencies with `uv sync --extra test`.
3. Add or update tests for behavior changes.
4. Run `python -m compileall -q req2code tests scripts` and `python -m pytest -q`.
5. Update both `README.md` and `README.zh-CN.md` when user-facing behavior changes.
6. Open a pull request describing the problem, design, tests, and any security impact.

Pull requests must not weaken these invariants:

- Development agents cannot commit or push.
- Approval is a human action and is not exposed through MCP.
- The reported change fingerprint is revalidated before publication.
- Pushes are non-force and target only the selected remote branch.
- Existing dirty worktrees are not reset, stashed, or overwritten.

Do not include real TAPD credentials, API keys, webhooks, approval tokens, run-state files, reports, or generated demo repositories. For security issues, follow `SECURITY.md` instead of opening a public issue.

## 中文

感谢参与 Req2Code。修改应保持聚焦，并保留人工审批安全边界。

1. 从仓库默认分支创建开发分支。
2. 运行 `uv sync --extra test` 安装开发依赖。
3. 行为变化必须增加或更新测试。
4. 运行 `python -m compileall -q req2code tests scripts` 和 `python -m pytest -q`。
5. 用户可见行为变化时同步更新 `README.md` 与 `README.zh-CN.md`。
6. Pull Request 中说明问题、设计、测试结果和安全影响。

Pull Request 不得削弱以下约束：

- 开发代理不能 commit 或 push；
- 批准必须由人执行，MCP 不提供批准工具；
- 发布前重新校验报告记录的变更指纹；
- 只允许非强制推送到所选 remote 分支；
- 不 reset、stash 或覆盖已有脏工作区。

不要提交真实 TAPD 凭据、API Key、Webhook、审批令牌、运行状态、报告或生成的演示仓库。安全问题请按 `SECURITY.md` 私下报告，不要创建公开 Issue。
