import json
import re
from pathlib import Path

from kit import capture, report, retirements

ROOT = Path(__file__).parent.parent


def test_retirements_load_and_are_sorted():
    rows = retirements.load()
    assert len(rows) >= 5
    assert [row["retires"] for row in rows] == sorted(row["retires"] for row in rows)
    assert {row["kind"] for row in rows} <= {"shutoff", "reroute"}


def test_readme_table_matches_the_yaml():
    readme = (ROOT / "README.md").read_text()
    block = re.search(r"<!-- retirements:start -->\n(.*?)\n<!-- retirements:end -->", readme, re.DOTALL)
    assert block, "README.md needs the retirements markers"
    assert block.group(1).strip() == retirements.markdown_table(retirements.load()).strip(), (
        "README table is stale: run `uv run python -m kit.retirements` and paste it in"
    )


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
    assert capture.messages_from_trace_input(
        {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": [{"type": "text", "text": "U"}]}]}
    ) == ("S", "U")
    assert capture.messages_from_trace_input({"question": "Q"}) == ("", "Q")
    assert capture.messages_from_trace_input({"foo": 1}) is None


def summary_fixture():
    stats = {"answered": 1, "errors": 0, "median_latency_s": 1.0, "mean_latency_s": 1.0, "total_cost_usd": 0.001,
             "priced": 1, "mean_output_tokens": 10, "mean_chars": 20}
    return {
        "run": "migration-test", "run_at": "now", "old_model": "gemini/old", "new_model": "gemini/new",
        "judge_model": "gemini/judge", "cases": 1, "meaning_changed": 1, "judged": 1,
        "fired_counts": {"same_meaning": 1}, "preference": {"new": 0, "same": 0, "old": 1}, "new_vs_old_mean": 0.0,
        "old_stats": stats, "new_stats": stats, "params": {"temperature": 0.2}, "params_lint": [],
        "params_lint_has_rules": False, "failed_on_new": [],
        "experiments": {"old": {"name": "e-old", "url": "https://x/old"}, "new": {"name": "e-new", "url": "https://x/new"}},
        "rows": [{"case": "math-01", "category": "numeric", "request": "How much <back>?", "old": "$102", "new": "$120",
                  "old_error": None, "new_error": None, "fired": [{"check": "same_meaning", "reason": "fact"}],
                  "meaning_changed": True, "meaning_reason": "fact: $102 -> $120", "meaning_kind": "fact", "better": "old"}],
    }


def test_report_renders_and_escapes(tmp_path):
    path = report.write(summary_fixture(), tmp_path)
    page = path.read_text()
    assert "1 of 1" in page and "$102" in page and "$120" in page
    assert "How much &lt;back&gt;?" in page
    assert 'href="https://x/new"' in page
    assert json.loads((tmp_path / "results.json").read_text())["meaning_changed"] == 1
