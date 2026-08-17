# Req2Code Codex plugin / Codex 插件

This distributable plugin bundles the `req2code-workflow` Skill and the `req2code` stdio MCP declaration. It expects `req2code-mcp` on the process `PATH`. Source profiles can be configured privately in the workflow UI; `req2code setup` is only a terminal fallback.

此插件包包含 `req2code-workflow` Skill 和 `req2code` stdio MCP 声明。Codex 进程需要能在 `PATH` 中找到 `req2code-mcp`；需求源可直接在工作流私有界面中配置，`req2code setup` 只用于终端降级。

For a development checkout whose virtual-environment executable is not on Codex's `PATH`, keep using the absolute-path `[mcp_servers.req2code]` configuration documented in the repository README. Do not commit source profiles or secrets into this plugin.

如果 Codex 无法从 `PATH` 找到项目虚拟环境中的程序，请继续使用项目 README 中记录的绝对路径 `[mcp_servers.req2code]` 配置。不要把需求源配置或密钥放进插件。

Validate before distribution:

```powershell
python C:\Users\<you>\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .
```
