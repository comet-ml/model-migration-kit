"""The comparison logic with fake model replies: pairing, judge failures, outcomes, links and inputs."""

import argparse
import json
from urllib.parse import parse_qs, urlsplit

import litellm
import pytest
from opik.evaluation.metrics.score_result import ScoreResult

from kit import capture, checks, compare, config, llm
from kit.meaning import MeaningChanged


def score(name, value, failed=False, **metadata):
    return ScoreResult(name=name, value=value, reason=f"{name} reason", scoring_failed=failed, metadata=metadata or None)


def case(item_id, label, output, error=None, scores=(), outcome="answered"):
    return item_id, {"output": output, "error": error, "outcome": outcome, "latency_s": 1.0, "cost_usd": 0.001,
                     "output_tokens": 5, "item": {"case": label, "input": f"request {label}"},
                     "scores": {s.name: s for s in scores}}


def judged(changed, better="same"):
    return [score("same_meaning", 0.0 if changed else 1.0, status="judged", kind="fact", better=better,
                  judge_cost_usd=0.01),
            score("new_vs_old", 0.5, status="judged", better=better)]


def summarize(old, new, **extra):
    return compare.summarize(dict(old), dict(new), old_model="p/old", new_model="p/new", judge="p/judge",
                             run_name="r", **extra)


OLD = [case("i1", "a", "A"), case("i2", "b", "B"), case("i3", "c", "C")]


def test_summary_counts_changed_failed_on_new_and_judge_cost():
    new = [case("i1", "a", "A2", scores=judged(True, "old")), case("i2", "b", "B", scores=judged(False)),
           case("i3", "c", "", error="BadRequestError: temperature",
                scores=[score("same_meaning", 0.0, True, status="no_answer")])]
    s = summarize(OLD, new)
    assert (s["meaning_changed"], s["judged"], s["judge_failed"], s["unjudged"]) == (1, 2, 0, 1)
    assert s["status"] == "ok"
    assert s["failed_on_new"] == [{"case": "c", "error": "BadRequestError: temperature"}]
    assert s["preference"] == {"new": 0, "same": 1, "old": 1}
    assert s["judge_cost_usd"] == pytest.approx(0.02)
    assert s["new_stats"]["errors"] == 1 and s["old_stats"]["answered"] == 3
    assert s["rows"][0]["case"] == "a"  # changed meaning first


def test_judge_failures_make_the_run_inconclusive_not_clean():
    failed = [score("same_meaning", 0.0, True, status="judge_failed"), score("new_vs_old", 0.0, True)]
    new = [case("i1", "a", "A", scores=judged(False)), case("i2", "b", "B", scores=failed),
           case("i3", "c", "C", scores=failed)]
    s = summarize(OLD, new)
    assert s["status"] == "inconclusive" and s["judge_failed"] == 2 and s["judged"] == 1
    assert "Inconclusive" in compare.headline(s)


def test_nothing_judged_is_unusable():
    failed = [score("same_meaning", 0.0, True, status="judge_failed")]
    s = summarize(OLD, [case(i, label, out, scores=failed) for i, (label, out) in
                        zip(("i1", "i2", "i3"), (("a", "A"), ("b", "B"), ("c", "C")))])
    assert s["status"] == "unusable" and compare.headline(s).startswith("No result")


def test_old_model_answering_nothing_is_unusable():
    old = [case("i1", "a", "", error="AuthenticationError")]
    s = summarize(old, {})
    assert s["status"] == "unusable" and "old model answered none of the 1" in s["status_reason"]


def test_pairs_by_item_id_even_when_labels_repeat():
    old = [case("i1", "same-label", "first"), case("i2", "same-label", "second")]
    new = [case("i2", "same-label", "second, new", scores=judged(True))]
    [row] = summarize(old, new)["rows"]
    assert (row["old"], row["new"]) == ("second", "second, new")


def test_old_model_misses_are_counted_apart_from_the_new_model():
    old = [case("i1", "a", "not json", scores=[score("json_valid", 0.0)])]
    new = [case("i1", "a", '{"x": 1}', scores=[score("json_valid", 1.0), *judged(False)])]
    s = summarize(old, new)
    assert s["fired_counts"] == {} and s["old_fired_counts"] == {"json_valid": 1}


def test_noise_floor_goes_in_the_headline():
    new = [case("i1", "a", "A2", scores=judged(True))]
    repeat = [case("i1", "a", "A3", scores=judged(True)), case("i2", "b", "B", scores=judged(False))]
    s = summarize(OLD[:2], new, repeat_cases=dict(repeat))
    assert s["noise"] == {"meaning_changed": 1, "judged": 2, "cases": 2}
    assert "(1 expected from run-to-run noise)" in compare.headline(s)


@pytest.mark.parametrize("reply,outcome,has_error", [
    ({"text": "hi", "finish_reason": "stop"}, "answered", False),
    ({"text": "hi, and the", "finish_reason": "length"}, "truncated", False),
    ({"text": "", "finish_reason": "length"}, "empty", True),
    ({"text": "", "finish_reason": "stop"}, "empty", True),
    ({"text": "", "finish_reason": "tool_calls", "tool_calls": [{"name": "lookup", "arguments": '{"id": 1}'}]},
     "tool_call", False),
])
def test_answer_outcomes(reply, outcome, has_error):
    fields = compare.answer_fields({"latency_s": 1, "input_tokens": 1, "output_tokens": 1, "cost_usd": None, **reply})
    assert fields["outcome"] == outcome and bool(fields["error"]) == has_error
    if outcome == "tool_call":
        assert "[tool call] lookup" in fields["output"]


def test_task_replays_history_and_system_override(monkeypatch):
    sent = {}

    def fake_complete(model, messages, **kwargs):
        sent["messages"] = messages
        return {"text": "ok", "finish_reason": "stop", "latency_s": 0.1, "input_tokens": 1, "output_tokens": 1,
                "cost_usd": None}

    monkeypatch.setattr(compare.llm, "complete", fake_complete)
    history = [{"role": "user", "content": "Order KC-1"}, {"role": "assistant", "content": "Got it"},
               {"role": "user", "content": "Cancel it"}]
    out = compare.make_task("p/new", system="OVERRIDE")({"id": "i1", "input": "Cancel it", "system": "row",
                                                         "messages": history})
    assert sent["messages"] == [{"role": "system", "content": "OVERRIDE"}, *history]
    assert out["system"] == "OVERRIDE"  # the judge reads this, not the row's own


def test_local_run_uses_the_same_metrics_and_pairs_old_answers(monkeypatch):
    replies = iter(["The refund is $102."] * 2 + ["The refund is $120."] * 2)
    monkeypatch.setattr(compare.llm, "complete", lambda model, messages, **kw: {
        "text": next(replies), "finish_reason": "stop", "latency_s": 0.1, "input_tokens": 1, "output_tokens": 1,
        "cost_usd": None})
    monkeypatch.setattr("kit.meaning.judge", lambda *a, **kw: {"changed": True, "kind": "fact", "reason": "amount",
                                                               "better": "old", "cost_usd": None})
    cases = [{"case": "m1", "input": "How much?", "system": "", "messages": [], "expects_json": False,
              "required_fields": []},
             {"case": "m2", "input": "And now?", "system": "", "messages": [], "expects_json": False,
              "required_fields": []}]
    single = [check() for check in checks.SINGLE_CHECKS]
    old, _ = compare.run_side_local(cases, "p/old", "old", "r", single, threads=1)
    new, info = compare.run_side_local(cases, "p/new", "new", "r", [*single, MeaningChanged("p/judge")], threads=1,
                                       old_answers=old)
    assert info["url"] is None
    s = summarize(old, new)
    assert s["meaning_changed"] == 2 and s["rows"][0]["old"] == "The refund is $102."


def test_compare_url_selects_both_experiments_on_the_sdk_host():
    sdk_url = "https://opik.internal:5173/my-ws/experiments/ds-1/compare?experiments=%5B%22e-old%22%5D"
    url = compare.compare_url(sdk_url, ["e-old", "e-new"])
    parts = urlsplit(url)
    assert parts.netloc == "opik.internal:5173" and parts.path == "/my-ws/experiments/ds-1/compare"
    assert json.loads(parse_qs(parts.query)["experiments"][0]) == ["e-old", "e-new"]
    assert compare.compare_url(None, ["a", "b"]) is None


def test_bad_params_stop_before_any_call(tmp_path):
    parser = argparse.ArgumentParser()
    for bad in ("{not json", "[1, 2]", '{"messages": []}'):
        with pytest.raises(SystemExit):
            compare.read_params(parser, bad, None)
    path = tmp_path / "params.json"
    path.write_text('{"temperature": 0.2}', encoding="utf-8")
    assert compare.read_params(parser, None, str(path)) == {"temperature": 0.2}
    with pytest.raises(argparse.ArgumentTypeError):
        compare.positive_int("0")


def test_retries_rate_limits_but_not_auth(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def flaky(**kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise litellm.RateLimitError("slow down", llm_provider="gemini", model="m")
        return litellm.ModelResponse(choices=[{"message": {"content": "ok"}, "finish_reason": "stop"}])

    monkeypatch.setattr(llm, "_tracked_completion", flaky)
    assert llm.complete("gemini/m", [{"role": "user", "content": "hi"}])["text"] == "ok" and len(calls) == 3

    def denied(**kwargs):
        calls.append(1)
        raise litellm.AuthenticationError("bad key", llm_provider="gemini", model="m")

    calls.clear()
    monkeypatch.setattr(llm, "_tracked_completion", denied)
    with pytest.raises(litellm.AuthenticationError):
        llm.complete("gemini/m", [{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_capture_skips_tool_use_and_images_with_a_reason():
    with pytest.raises(capture.Skip, match="tool calls"):
        capture.case_from_trace_input({"messages": [{"role": "user", "content": "x"},
                                                    {"role": "assistant", "tool_calls": [{}]}]}, 0, "t")
    with pytest.raises(capture.Skip, match="non-text"):
        capture.case_from_trace_input({"messages": [{"role": "user", "content": [{"type": "image_url"}]}]}, 0, "t")
    kept = capture.case_from_trace_input({"messages": [{"role": "user", "content": "Order KC-1"},
                                                       {"role": "assistant", "content": "Got it"},
                                                       {"role": "user", "content": "Cancel it"}]}, 0, "t", "SYS")
    assert kept["input"] == "Cancel it" and len(kept["messages"]) == 3 and kept["system"] == "SYS"


def test_jsonl_messages_rows_and_input_column(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}]})
                    + "\n" + json.dumps({"question": {"order": 1}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row 2"):
        capture.load_file(path)
    path.write_text(json.dumps({"question": {"order": 1}}) + "\n", encoding="utf-8")
    [row] = capture.load_file(path, input_column="question")
    assert row["input"] == '{"order": 1}'  # non-string input becomes JSON text


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no rows"):
        capture.load_file(path)


def test_config_drops_blank_opik_values_and_reads_after_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPIK_WORKSPACE=\nOPIK_API_KEY=  \nJUDGE_MODEL=openai/x\nMIGRATION_KIT_THREADS=3\n",
                                   encoding="utf-8")
    for name in ("OPIK_WORKSPACE", "OPIK_API_KEY", "JUDGE_MODEL", "MIGRATION_KIT_THREADS", "OPIK_PROJECT_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    settings = config.load()
    assert "OPIK_WORKSPACE" not in config.os.environ and "OPIK_API_KEY" not in config.os.environ
    assert settings == config.Settings(project="model-migration-kit", judge="openai/x", threads=3)


def test_judge_avoids_the_compared_models(monkeypatch):
    monkeypatch.setattr(config, "has_key", lambda model: model.startswith("gemini/"))
    assert config.pick_judge("openai/a", "openai/b") == ("gemini/gemini-3.8-flash", None)
    # The usual Gemini judge is being tested, so the second Gemini judge steps in.
    assert config.pick_judge("gemini/gemini-2.5-pro", "gemini/gemini-3.8-flash") == ("gemini/gemini-3.5-flash", None)
    # Only one judge model reachable and it's the new model: it is used, with a warning.
    monkeypatch.setattr(config, "has_key", lambda model: model == "gemini/gemini-3.8-flash")
    judge, warning = config.pick_judge("gemini/gemini-2.5-pro", "gemini/gemini-3.8-flash")
    assert judge == "gemini/gemini-3.8-flash" and "grades its own" in warning


def test_blank_keys_from_env_example_count_as_unset(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=\nOPENAI_API_KEY=sk-test\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config.load()
    assert "GEMINI_API_KEY" not in config.os.environ and config.os.environ["OPENAI_API_KEY"] == "sk-test"


def test_platform_credentials_come_from_litellm(monkeypatch):
    for name in ("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION", "VERTEXAI_PROJECT", "VERTEXAI_LOCATION",
                 "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME", "AWS_REGION", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config.Path, "home", lambda: config.Path("/nonexistent"))
    assert {"AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"} <= set(config.missing_env("azure/my-gpt-4o"))
    assert {"VERTEXAI_PROJECT", "VERTEXAI_LOCATION"} <= set(config.missing_env("vertex_ai/gemini-2.5-flash"))
    bedrock = config.missing_env("bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert "AWS_ACCESS_KEY_ID" in bedrock and "AWS_REGION_NAME" in bedrock
    monkeypatch.setenv("AWS_PROFILE", "work")
    monkeypatch.setenv("AWS_REGION_NAME", "us-east-1")
    assert config.missing_env("bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0") == []


def test_headline_names_failures_and_unknown_noise():
    summary = {"status": "ok", "meaning_changed": 0, "judged": 1, "noise": {"meaning_changed": 0, "judged": 0, "cases": 30},
               "failed_on_new": [{"case": "a", "error": "x"}] * 29}
    text = compare.headline(summary)
    assert "29 requests failed on the new model" in text and "noise unknown" in text


def test_credentials_in_params_never_reach_the_report():
    assert compare.redact({"api_key": "sk-1", "temperature": 0.2}) == {"api_key": "[hidden]", "temperature": 0.2}
