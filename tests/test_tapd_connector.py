from req2code.connectors.tapd_connector import TapdConnector


def test_tapd_fallback_without_base_url():
    connector = TapdConnector(base_url="")
    items = list(connector.fetch_latest(limit=3))
    assert len(items) == 3
    assert items[0].source == "tapd"


def test_tapd_get_by_id_fallback():
    connector = TapdConnector(base_url="")
    item = connector.get_by_id("TAPD-123")
    assert item.id == "TAPD-123"


def test_tapd_throttle_does_not_crash():
    connector = TapdConnector(base_url="", rate_limit_qps=1000)
    connector._throttle()
    connector._throttle()


def test_tapd_headers_basic_mode_has_no_auth_header():
    connector = TapdConnector(base_url="", app_id="id", app_secret="secret")
    headers = connector._headers()
    assert "Authorization" not in headers
