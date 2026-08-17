from req2code.selection import WorkItemSelectionStore


def test_selection_uses_stable_short_keys_and_persists_confirmation(tmp_path):
    store = WorkItemSelectionStore(tmp_path)
    selection = store.create(
        [
            {"id": "DEMO-0151", "type": "bug", "title": "Card layout", "description": "Fix it"},
            {"id": "DEMO-0102", "type": "requirement", "title": "New flow", "description": "Build it"},
        ]
    )

    assert [item["key"] for item in selection.items] == ["B0151", "S0102"]
    confirmed = store.confirm(selection.selection_id, ["b0151", "S0102", "B0151"])
    assert confirmed.status == "confirmed"
    assert confirmed.selected_keys == ["B0151", "S0102"]
    assert confirmed.selected_specs == ["bug:DEMO-0151", "story:DEMO-0102"]
    assert store.require(selection.selection_id).selected_specs == confirmed.selected_specs


def test_selection_recognizes_wrapped_tapd_bug_when_legacy_type_is_wrong(tmp_path):
    store = WorkItemSelectionStore(tmp_path)
    selection = store.create(
        [
            {
                "id": "DEMO-0151",
                "type": "requirement",
                "title": "Card layout",
                "metadata": {"Bug": {"status": "new"}},
            }
        ]
    )

    assert selection.items[0]["key"] == "B0151"
    assert selection.items[0]["type"] == "bug"
    assert selection.items[0]["spec"] == "bug:DEMO-0151"
