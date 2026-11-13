import pytest

from kit import meaning


def fake_complete(reply_text):
    calls = []

    def _complete(model, messages, **kwargs):
        calls.append({"model": model, "prompt": messages[0]["content"], **kwargs})
        return {"text": reply_text}

    return _complete, calls


def test_changed_answer_scores_zero_with_the_reason(monkeypatch):
    stub, calls = fake_complete(
        '{"changed": true, "kind": "fact", "reason": "refund went from $102 to $120", "better": "old"}'
    )
    monkeypatch.setattr(meaning, "complete", stub)
    same, preference = meaning.MeaningChanged(model="gemini/judge").score(
        input="How much back?", output="$120", old_output="$102", system="15% restocking fee"
    )
    assert same.name == "same_meaning" and same.value == 0.0
    assert "fact" in same.reason and "$120" in same.reason
    assert preference.name == "new_vs_old" and preference.value == 0.0
    assert calls[0]["model"] == "gemini/judge"
    assert "15% restocking fee" in calls[0]["prompt"] and "$102" in calls[0]["prompt"]
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_unchanged_answer_scores_one(monkeypatch):
    stub, _ = fake_complete('```json\n{"changed": false, "kind": "none", "reason": "same meaning", "better": "same"}\n```')
    monkeypatch.setattr(meaning, "complete", stub)
    same, preference = meaning.MeaningChanged().score(input="q", output="a", old_output="a")
    assert same.value == 1.0 and preference.value == 0.5


def test_judge_failure_is_not_scored(monkeypatch):
    stub, _ = fake_complete("I think they are about the same.")
    monkeypatch.setattr(meaning, "complete", stub)
    results = meaning.MeaningChanged().score(input="q", output="a", old_output="b")
    assert all(result.scoring_failed for result in results)


def test_parse_verdict_rejects_missing_changed():
    with pytest.raises(ValueError):
        meaning.parse_verdict('{"kind": "fact"}')


def test_parse_verdict_fills_bad_fields():
    verdict = meaning.parse_verdict('{"changed": true, "kind": "vibes", "better": "both"}')
    assert verdict["kind"] == "fact" and verdict["better"] == "same"
