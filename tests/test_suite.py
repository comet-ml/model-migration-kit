from pathlib import Path
from types import SimpleNamespace

import pytest
from opik.evaluation.metrics.score_result import ScoreResult

from kit import capture, suite

EXAMPLE = Path(__file__).parent.parent / "examples" / "support-bot"


def write(tmp_path, text):
    path = tmp_path / "checks.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_example_checks_load_and_name_real_cases():
    checks = suite.load_checks(EXAMPLE / "checks.yaml")
    cases = capture.load_file(EXAMPLE / "cases.jsonl")
    everywhere, per_case = suite.plan(checks, cases)
    assert checks and not everywhere
    assert "plain-06-refund-timing" in per_case
    items = suite.suite_items(cases, per_case, everywhere)
    assert {item["data"]["case"] for item in items} == set(per_case)
    assert all(item["assertions"] for item in items)


def test_check_text_is_folded_to_one_line(tmp_path):
    checks = suite.load_checks(write(tmp_path, "- check: >-\n    first line\n    second line\n"))
    assert checks == [{"check": "first line second line", "cases": None, "found": None}]


@pytest.mark.parametrize("text", ["", "check: not a list\n", "- cases: [a]\n", "- check: ok\n  cases: a-string\n"])
def test_bad_checks_files_are_refused(tmp_path, text):
    with pytest.raises(ValueError):
        suite.load_checks(write(tmp_path, text))


def test_a_check_without_cases_covers_every_case():
    cases = [{"case": "a", "input": "x"}, {"case": "b", "input": "y"}]
    checks = [{"check": "is polite", "cases": None, "found": None}, {"check": "says no", "cases": ["b"], "found": None}]
    everywhere, per_case = suite.plan(checks, cases)
    items = suite.suite_items(cases, per_case, everywhere)
    assert everywhere == ["is polite"]
    assert [(i["data"]["case"], i["assertions"]) for i in items] == [("a", []), ("b", ["says no"])]


def test_a_check_naming_a_missing_case_is_refused():
    with pytest.raises(ValueError, match="nope"):
        suite.plan([{"check": "x", "cases": ["nope"], "found": None}], [{"case": "a", "input": "x"}])


def test_tally_counts_passes_and_keeps_failure_reasons():
    def run(case, *scores):
        return SimpleNamespace(test_case=SimpleNamespace(dataset_item_content={"case": case}, task_output={"output": "x"}),
                               score_results=list(scores))

    passed = ScoreResult(name="keeps the condition", value=1.0)
    failed = ScoreResult(name="keeps the condition", value=0.0, reason="dropped it")
    result = SimpleNamespace(item_results={"id1": SimpleNamespace(dataset_item_id="id1",
                                                                  test_results=[run("c1", passed), run("c1", failed)])})
    assert suite.tally(result) == {"keeps the condition": {"passed": 1, "total": 2, "failures": [("c1", "dropped it")],
                                                           "judge_errors": 0}}


def test_a_failed_judge_call_is_not_counted_as_a_model_failure():
    run = SimpleNamespace(test_case=SimpleNamespace(dataset_item_content={"case": "c1"}, task_output={"output": "x"}),
                          score_results=[ScoreResult(name="no refund", value=0.0, scoring_failed=True)])
    result = SimpleNamespace(item_results={"id1": SimpleNamespace(dataset_item_id="id1", test_results=[run])})
    assert suite.tally(result)["no refund"] == {"passed": 0, "total": 0, "failures": [], "judge_errors": 1}


def test_suite_task_returns_input_and_output(monkeypatch):
    monkeypatch.setattr("kit.llm.complete", lambda model, messages, **kw: {
        "text": "hello", "finish_reason": "stop", "latency_s": 0.1, "input_tokens": 1, "output_tokens": 1,
        "cost_usd": 0.0, "tool_calls": None})
    out = suite.suite_task("gemini/x", None, "be nice")({"case": "a", "input": "hi"})
    assert out == {"input": "ASSISTANT INSTRUCTIONS:\nbe nice\n\nUSER: hi", "output": "hello"}


def test_the_judge_sees_the_whole_conversation():
    data = {"case": "a", "input": "Cancel it", "messages": [
        {"role": "user", "content": "My order is KC-1"}, {"role": "assistant", "content": "Got it"},
        {"role": "user", "content": "Cancel it"}]}
    text = suite.judge_input(data, None)
    assert "KC-1" in text and text.endswith("USER: Cancel it")


def test_a_case_whose_model_call_failed_fails_every_check_without_the_judge():
    errored = SimpleNamespace(test_case=SimpleNamespace(dataset_item_content={"case": "c1"},
                                                        task_output={"output": suite.ERROR_PREFIX + "BadRequestError"}),
                              score_results=[ScoreResult(name="no refund", value=1.0)])
    result = SimpleNamespace(item_results={"id1": SimpleNamespace(dataset_item_id="id1", test_results=[errored])})
    assert suite.tally(result)["no refund"]["passed"] == 0


def test_suite_task_marks_a_failed_model_call(monkeypatch):
    def boom(model, messages, **kw):
        raise RuntimeError("temperature is not supported")
    monkeypatch.setattr("kit.llm.complete", boom)
    output = suite.suite_task("anthropic/x", {"temperature": 0.2}, None)({"case": "a", "input": "hi"})["output"]
    assert output.startswith(suite.ERROR_PREFIX)


def test_empty_cases_list_is_refused(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        suite.load_checks(write(tmp_path, "- check: ok\n  cases: []\n"))


class FakeSuite:
    def __init__(self, items):
        self.items, self.calls = items, []

    def update_test_settings(self, **kw):
        self.calls.append(("settings", kw))

    def get_items(self):
        return self.items

    def update(self, items):
        self.calls.append(("update", [i["id"] for i in items]))

    def insert(self, items):
        self.calls.append(("insert", [i["data"]["case"] for i in items]))

    def delete(self, ids):
        self.calls.append(("delete", ids))


def test_sync_suite_updates_inserts_and_removes_only_its_own_items(monkeypatch):
    import opik

    fake = FakeSuite([{"id": "1", "data": {"case": "a"}}, {"id": "2", "data": {"case": "gone"}},
                      {"id": "3", "data": {"note": "added by hand in Opik"}}])
    monkeypatch.setattr(opik, "Opik", lambda: SimpleNamespace(get_or_create_test_suite=lambda *a, **k: fake))
    items = [{"data": {"case": "a"}, "assertions": []}, {"data": {"case": "b"}, "assertions": []}]
    suite.sync_suite("s", items, ["is polite"], 3, "p")
    settings = fake.calls[0][1]
    assert settings["global_assertions"] == ["is polite", suite.ANSWERED_CHECK]
    assert settings["global_execution_policy"] == {"runs_per_item": 3, "pass_threshold": 3}
    assert ("update", ["1"]) in fake.calls and ("insert", ["b"]) in fake.calls and ("delete", ["2"]) in fake.calls
