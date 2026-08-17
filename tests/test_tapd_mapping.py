from req2code.config import TapdFieldMappingConfig
from req2code.connectors.tapd_connector import TapdConnector
from req2code.models import TaskType


def test_extract_path_and_mapping_build_item():
    mapping = TapdFieldMappingConfig(
        list_path="result.items",
        id_field="story_id",
        title_field="name",
        description_field="desc",
        type_field="kind",
    )
    connector = TapdConnector(field_mapping=mapping)
    payload = {"result": {"items": [{"story_id": 1, "name": "A", "desc": "B", "kind": "bug"}]}}

    records = connector._extract_value(payload, mapping.list_path)
    assert isinstance(records, list)
    item = connector._build_item(records[0], mapping=mapping)
    assert item.id == "1"
    assert item.title == "A"
    assert item.description == "B"
    assert item.type.value == "bug"


def test_fetch_uses_endpoint_kind_instead_of_tapd_business_type(monkeypatch):
    connector = TapdConnector(base_url="https://api.tapd.cn")
    responses = {
        "/stories": {
            "status": 1,
            "data": [{"Story": {"id": "101", "name": "Story", "description": "", "type": ""}}],
        },
        "/bugs": {
            "status": 1,
            "data": [{"Bug": {"id": "202", "title": "Bug", "description": "", "type": None}}],
        },
    }

    monkeypatch.setattr(
        connector,
        "_request_json",
        lambda url, params: responses[next(path for path in responses if url.endswith(path))],
    )

    story = list(connector.fetch_latest_by_type(limit=1, item_type="story"))[0]
    bug = list(connector.fetch_latest_by_type(limit=1, item_type="bug"))[0]

    assert story.type is TaskType.REQUIREMENT
    assert bug.type is TaskType.BUG


def test_detail_uses_requested_item_kind(monkeypatch):
    connector = TapdConnector(base_url="https://api.tapd.cn")
    monkeypatch.setattr(
        connector,
        "_request_json",
        lambda url, params: {
            "status": 1,
            "data": [{"Bug": {"id": "202", "title": "Bug", "description": "", "type": "feature"}}],
        },
    )

    assert connector.get_by_id_with_type("202", item_type="bug").type is TaskType.BUG
