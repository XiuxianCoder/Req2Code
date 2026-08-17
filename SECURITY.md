# Security Policy / 安全策略

## Supported versions / 支持版本

Req2Code is currently alpha software. Security fixes are applied to the latest revision of the default branch. No older release line is currently maintained.

Req2Code 当前处于 Alpha 阶段，安全修复只应用到默认分支最新版本，暂不维护旧版本分支。

## Reporting a vulnerability / 报告安全问题

Do not open a public issue for suspected credential exposure, command injection, approval bypass, unsafe Git publication, signature/replay bypass, or path traversal. After the repository is published, use GitHub's private **Report a vulnerability** security-advisory flow. Until that is available, contact the repository owner privately.

如怀疑存在凭据泄露、命令注入、绕过审批、不安全 Git 发布、签名/重放保护绕过或目录穿越，请不要创建公开 Issue。仓库发布后请使用 GitHub Security 页面中的私密 **Report a vulnerability**；在该功能可用前，请私下联系仓库所有者。

Include the affected revision, operating system, minimal reproduction, expected/actual behavior, and impact. Remove all real credentials, tokens, repository URLs, work-item contents, and customer data from the report.

报告中请包含受影响版本、操作系统、最小复现、预期/实际行为及影响，并删除真实凭据、令牌、仓库 URL、工作项内容和客户数据。

## Operational guidance / 运行建议

- Start with Mock and a local bare remote.
- Use a dedicated operating-system account and least-privilege TAPD/Git credentials.
- Keep approval service access restricted and configure a strong callback secret and IP allowlist.
- Treat project memory, cached mirrors, reports, and artifacts as sensitive because summaries, prompts, diffs, and test logs may contain proprietary code.
- Never expose the state directory through a public web server.
- Protect production branches in the Git hosting platform as a second control.

- 先使用 Mock 和本地 bare remote 测试。
- 使用专用系统账号及最小权限 TAPD/Git 凭据。
- 限制审核服务访问，并配置强回调密钥和 IP 白名单。
- 项目记忆、Git mirror、报告与产物可能包含架构摘要、提示词、代码 Diff 和测试日志，应按敏感数据处理。
- 不要通过公共 Web 服务暴露状态目录。
- 在 Git 托管平台继续启用生产分支保护，作为第二道安全控制。