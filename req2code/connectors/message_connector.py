from __future__ import annotations

import requests


class MessageConnector:
    """通知连接器：企业微信/钉钉/Webhook。"""

    def __init__(
        self,
        provider: str = "webhook",
        webhook: str = "",
        timeout_seconds: int = 10,
        default_level: str = "normal",
        templates: dict | None = None,
    ) -> None:
        self.provider = (provider or "webhook").lower()
        self.webhook = webhook
        self.timeout_seconds = timeout_seconds
        self.default_level = default_level
        self.templates = templates or {
            "normal": "[{level}] {content}",
            "warning": "[{level}] {content}",
            "critical": "[{level}] {content}\\nartifact={artifact}",
        }

    def _render(self, content: str, level: str, artifact: str) -> str:
        template = self.templates.get(level) or self.templates.get("normal") or "{content}"
        return template.format(level=level, content=content, artifact=artifact)

    def _build_payload(self, reviewer: str, content: str) -> dict:
        if self.provider == "wechat_work":
            return {
                "msgtype": "markdown",
                "markdown": {"content": f"**审核人**: {reviewer}\n\n{content}"},
            }
        if self.provider == "dingtalk":
            return {
                "msgtype": "markdown",
                "markdown": {"title": "Req2Code 告警通知", "text": f"### 审核人: {reviewer}\n\n{content}"},
            }
        return {
            "reviewer": reviewer,
            "content": content,
        }

    def notify(self, reviewer: str, content: str, level: str | None = None, artifact: str = "") -> None:
        level = (level or self.default_level).lower()
        rendered = self._render(content, level=level, artifact=artifact)

        if not self.webhook:
            print(f"[Notify/Fallback][{level}] to={reviewer}: {rendered}")
            return

        payload = self._build_payload(reviewer, rendered)
        try:
            resp = requests.post(self.webhook, json=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException:
            print(f"[Notify/Failed/Fallback][{level}] to={reviewer}: {rendered}")
