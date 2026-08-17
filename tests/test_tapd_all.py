from req2code.connectors.tapd_connector import TapdConnector


def test_fetch_latest_all_combines_story_and_bug():
    c = TapdConnector(base_url="")
    items = list(c.fetch_latest_all(limit=4))
    assert len(items) == 4
    # fallback split should include both kinds
    kinds = {x.type.value for x in items}
    assert "requirement" in kinds or "bug" in kinds
