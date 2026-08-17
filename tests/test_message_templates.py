from req2code.connectors.message_connector import MessageConnector


def test_message_template_render_critical():
    c = MessageConnector(
        provider="webhook",
        templates={
            "normal": "[{level}] {content}",
            "critical": "[{level}] {content} @ {artifact}",
        },
    )
    rendered = c._render("boom", level="critical", artifact="/tmp/logs")
    assert "critical" in rendered
    assert "/tmp/logs" in rendered
