import json
import re

import pytest
from pathlib import Path

from kit import capture, report, retirements

ROOT = Path(__file__).parent.parent


def test_retirements_load_and_are_sorted():
    rows = retirements.load()
    assert len(rows) >= 5
    assert [row["retires"] for row in rows] == sorted(row["retires"] for row in rows)
    assert {row["kind"] for row in rows} <= set(retirements.KINDS)


def test_tables_match_the_yaml(tmp_path):
    for page in retirements.PAGES:
        (tmp_path / page).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / page).write_text((ROOT / page).read_text(encoding="utf-8"), encoding="utf-8")
    stale = retirements.write_pages(retirements.load(), root=tmp_path)
    assert not stale, f"tables are stale in {stale}: run `uv run python -m kit.retirements --write`"
    assert "<!-- retirements:start -->\n| Model" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_past_dates_render_as_retired_and_no_check_markers():
    rows = retirements.load()
    later = [{**row, "checked_on": row["retires"].replace(year=row["retires"].year + 1)} for row in rows[:1]]
    assert "(retired)" in retirements.markdown_table(later)
    for page in retirements.PAGES:
        assert "[check]" not in (ROOT / page).read_text(encoding="utf-8"), page


def test_example_cases_load():
    cases = capture.load_file(ROOT / "examples/support-bot/cases.jsonl", system="SYS")
    assert len(cases) == 30
    assert all(case["system"] == "SYS" for case in cases)
    assert sum(case["expects_json"] for case in cases) == 7


def test_csv_cases(tmp_path):
    path = tmp_path / "cases.csv"
    path.write_text('input,required_fields\n"where is KC-1","order_id, intent"\n')
    [case] = capture.load_file(path)
    assert case["required_fields"] == ["order_id", "intent"] and case["expects_json"]


def test_trace_input_shapes():
    case = capture.case_from_trace_input(
        {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": [{"type": "text", "text": "U"}]}]},
        0, "t1")
    assert (case["system"], case["input"], case["messages"]) == ("S", "U", [])
    assert capture.case_from_trace_input({"question": "Q"}, 0, "t2")["input"] == "Q"
    with pytest.raises(capture.Skip):
        capture.case_from_trace_input({"foo": 1}, 0, "t3")


def summary_fixture():
    stats = {"answered": 1, "errors": 0, "median_latency_s": 1.0, "mean_latency_s": 1.0, "total_cost_usd": 0.001,
             "priced": 1, "mean_output_tokens": 10, "mean_chars": 20}
    return {
        "run": "migration-test", "run_at": "now", "old_model": "gemini/old", "new_model": "gemini/new",
        "judge_model": "gemini/judge", "cases": 1, "meaning_changed": 1, "judged": 1, "judge_failed": 0, "unjudged": 0,
        "status": "ok", "status_reason": "", "noise": None, "judge_cost_usd": None, "opik": True,
        "compare_url": "https://x/compare?experiments=%5B%22a%22%2C%22b%22%5D",
        "fired_counts": {"same_meaning": 1}, "preference": {"new": 0, "same": 0, "old": 1}, "new_vs_old_mean": 0.0,
        "old_stats": stats, "new_stats": stats, "params": {"temperature": 0.2}, "params_lint": [],
        "params_lint_has_rules": False, "failed_on_new": [],
        "experiments": {"old": {"name": "e-old", "id": "a", "url": "https://x/old"},
                        "new": {"name": "e-new", "id": "b", "url": "https://x/new"}},
        "rows": [{"case": "math-01", "category": "numeric", "request": "How much <back>?", "old": "$102", "new": "$120",
                  "old_error": None, "new_error": None, "fired": [{"check": "same_meaning", "reason": "fact"}],
                  "old_fired": [], "scoring": "judged", "meaning_changed": True, "meaning_reason": "fact: $102 -> $120", "meaning_kind": "fact", "better": "old"}],
    }


def test_report_renders_and_escapes(tmp_path):
    path = report.write(summary_fixture(), tmp_path)
    page = path.read_text(encoding="utf-8")
    assert "1 of 1" in page and "$102" in page and "$120" in page
    assert "How much &lt;back&gt;?" in page
    assert 'href="https://x/new"' in page
    assert page.index("Compare both experiments in Opik") < page.index('href="https://x/new"')
    assert "utm_content=report" in page and "agent evaluation platform built by Comet" in page
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["meaning_changed"] == 1
