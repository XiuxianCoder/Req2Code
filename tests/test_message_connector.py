from req2code.connectors.message_connector import MessageConnector


def test_message_payload_wechat_work():
    connector = MessageConnector(provider="wechat_work", webhook="")
    payload = connector._build_payload("alice", "please review")
    assert payload["msgtype"] == "markdown"
    assert "审核人" in payload["markdown"]["content"]


def test_message_payload_dingtalk():
    connector = MessageConnector(provider="dingtalk", webhook="")
    payload = connector._build_payload("bob", "please review")
    assert payload["msgtype"] == "markdown"
    assert "审核人" in payload["markdown"]["text"]
