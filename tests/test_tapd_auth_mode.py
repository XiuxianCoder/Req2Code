import pytest
import requests

from req2code.connectors.tapd_connector import TapdConnector


def test_basic_auth_tuple_when_configured():
    c = TapdConnector(auth_mode="basic", app_id="id1", app_secret="sec1")
    assert c._basic_auth() == ("id1", "sec1")


def test_basic_auth_none_when_missing_credentials():
    c = TapdConnector(auth_mode="basic", app_id="", app_secret="")
    assert c._basic_auth() is None


def test_token_request_skipped_for_unknown_auth_mode():
    c = TapdConnector(auth_mode="token", app_id="id1", app_secret="sec1")
    assert c._request_access_token() == ""
    assert "unsupported auth_mode" in c.last_error


def test_basic_request_surfaces_tapd_permission_error(monkeypatch):
    class ForbiddenResponse:
        status_code = 403
        text = '{"status":403,"info":"api account not allowed to access project"}'

        def json(self):
            return {"status": 403, "info": "api account not allowed to access project"}

        def raise_for_status(self):
            raise requests.HTTPError("403 Client Error")

    monkeypatch.setattr("req2code.connectors.tapd_connector.requests.get", lambda *args, **kwargs: ForbiddenResponse())
    connector = TapdConnector(
        base_url="https://api.tapd.cn",
        workspace_id="12345678",
        auth_mode="basic",
        app_id="api-user",
        app_secret="api-password",
        retries=1,
    )

    with pytest.raises(RuntimeError, match="HTTP 403: api account not allowed to access project"):
        list(connector.fetch_latest_by_type(limit=1, item_type="story"))
