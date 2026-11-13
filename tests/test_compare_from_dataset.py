"""compare.py reading cases from an existing Opik dataset (capture -> compare), with a fake Opik client."""

import pytest

from kit import capture, compare


class FakeDataset:
    def __init__(self, items):
        self.items = items

    def get_items(self):
        return self.items


class FakeClient:
    def __init__(self, items):
        self.items = items
        self.asked = None

    def get_dataset(self, name, project_name=None):
        self.asked = (name, project_name)
        return FakeDataset(self.items)


def use_fake_opik(monkeypatch, items):
    client = FakeClient(items)
    monkeypatch.setattr(capture.opik, "Opik", lambda *args, **kwargs: client)
    return client


def test_cases_come_from_the_dataset_when_no_file_is_given(monkeypatch):
    client = use_fake_opik(monkeypatch, [
        {"id": "1", "case": "trace-abc", "input": "Where is KC-1?", "system": "S", "expects_json": False,
         "required_fields": [], "category": ""},
        {"id": "2", "input": "  "},  # no usable input: skipped
        {"id": "3", "input": "Refund?", "required_fields": ["order_id"]},
    ])
    cases = compare.load_cases(None, "my-migration")
    assert client.asked == ("my-migration", compare.PROJECT)
    assert [case["input"] for case in cases] == ["Where is KC-1?", "Refund?"]
    assert cases[0]["case"] == "trace-abc" and cases[0]["system"] == "S"
    assert cases[1]["expects_json"] and cases[1]["case"] == "case-002"


def test_an_empty_dataset_stops_with_a_clear_message(monkeypatch):
    use_fake_opik(monkeypatch, [])
    with pytest.raises(SystemExit, match="no usable items"):
        compare.load_cases(None, "empty")


def test_neither_cases_nor_dataset_stops_with_a_clear_message():
    with pytest.raises(SystemExit, match="--cases"):
        compare.load_cases(None, None)
