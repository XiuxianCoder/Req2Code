from req2code.config import AgentConfig, FeishuSourceConfig
from req2code.connectors.feishu_connector import FeishuConnector
from req2code.connectors.mock_connector import MockConnector
from req2code.connectors.tapd_connector import TapdConnector
from req2code.source_factory import get_source_connector


def test_get_tapd_source_connector():
    cfg = AgentConfig(source="tapd")
    connector = get_source_connector(cfg)
    assert isinstance(connector, TapdConnector)
    assert connector.auth_mode == "oauth2"


def test_get_mock_source_connector():
    cfg = AgentConfig(source="mock")
    connector = get_source_connector(cfg)
    assert isinstance(connector, MockConnector)


def test_get_feishu_source_connector():
    cfg = AgentConfig(
        source="feishu",
        feishu=FeishuSourceConfig(
            app_id="cli_a123",
            app_secret="secret",
            document_url="https://example.feishu.cn/docx/doxcnDocumentToken123456789",
        ),
    )
    connector = get_source_connector(cfg)
    assert isinstance(connector, FeishuConnector)
    assert connector.auth_mode == "tenant"
