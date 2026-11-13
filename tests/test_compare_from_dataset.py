"""compare.py reading cases from an existing Opik dataset (capture -> compare), with a fake Opik client."""

import opik
import pytest

from kit import compare


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
    monkeypatch.setattr(opik, "Opik", lambda *args, **kwargs: client)
    return client


def test_cases_come_from_the_dataset_when_no_file_is_given(monkeypatch):
    client = use_fake_opik(monkeypatch, [
        {"id": "1", "case": "trace-abc", "input": "Where is KC-1?", "system": "S", "expects_json": False,
         "required_fields": [], "category": ""},
        {"id": "2", "input": "  "},  # no usable input: skipped
        {"id": "3", "input": "Refund?", "required_fields": ["order_id"]},
    ])
    cases = compare.load_cases(None, "my-migration", "proj")
    assert client.asked == ("my-migration", "proj")
    assert [case["input"] for case in cases] == ["Where is KC-1?", "Refund?"]
    assert cases[0]["case"] == "trace-abc" and cases[0]["system"] == "S"
    assert cases[1]["expects_json"] and cases[1]["case"] == "case-002"
    assert [case["id"] for case in cases] == ["1", "3"]  # item IDs kept, so nothing is written back


def test_an_empty_dataset_stops_with_a_clear_message(monkeypatch):
    use_fake_opik(monkeypatch, [])
    with pytest.raises(SystemExit, match="no usable items"):
        compare.load_cases(None, "empty", "proj")


def test_neither_cases_nor_dataset_stops_with_a_clear_message():
    with pytest.raises(SystemExit, match="--cases"):
        compare.load_cases(None, None, "proj")


def test_duplicate_case_labels_in_a_dataset_stop_the_run(monkeypatch):
    use_fake_opik(monkeypatch, [{"id": "1", "case": "a", "input": "x"}, {"id": "2", "case": "a", "input": "y"}])
    with pytest.raises(SystemExit, match="unique"):
        compare.load_cases(None, "edited", "proj")
