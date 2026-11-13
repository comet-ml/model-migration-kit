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
        return SimpleNamespace(test_case=SimpleNamespace(dataset_item_content={"case": case}), score_results=list(scores))

    passed = ScoreResult(name="keeps the condition", value=1.0)
    failed = ScoreResult(name="keeps the condition", value=0.0, reason="dropped it")
    result = SimpleNamespace(item_results={"id1": SimpleNamespace(dataset_item_id="id1",
                                                                  test_results=[run("c1", passed), run("c1", failed)])})
    assert suite.tally(result) == {"keeps the condition": {"passed": 1, "total": 2, "failures": [("c1", "dropped it")]}}


def test_suite_task_returns_input_and_output(monkeypatch):
    monkeypatch.setattr("kit.llm.complete", lambda model, messages, **kw: {
        "text": "hello", "finish_reason": "stop", "latency_s": 0.1, "input_tokens": 1, "output_tokens": 1,
        "cost_usd": 0.0, "tool_calls": None})
    assert suite.suite_task("gemini/x", None, "be nice")({"case": "a", "input": "hi"}) == {"input": "hi", "output": "hello"}
