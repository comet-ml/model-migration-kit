from kit import checks


def test_parse_json_accepts_a_code_fence_and_says_so():
    value, how = checks.parse_json('```json\n{"order_id": "KC-1"}\n```')
    assert value == {"order_id": "KC-1"}
    assert "code fence" in how


def test_parse_json_rejects_prose():
    value, how = checks.parse_json('Sure! {"order_id": "KC-1"}')
    assert value is None and "not valid JSON" in how


def test_refusal_is_read_from_the_opening_only():
    assert checks.is_refusal("I'm sorry, but I can't share another customer's address.")
    assert checks.is_refusal("Unfortunately, I can't give out discount codes.")
    assert not checks.is_refusal("Your refund is $102." + " " * 300 + "I can't wait to help again!")


def test_detect_format():
    assert checks.detect_format('{"a": 1}') == "json"
    assert checks.detect_format('```json\n{"a": 1}\n```') == "json-fenced"
    assert checks.detect_format("**Refund:** $102") == "markdown"
    assert checks.detect_format("- one\n- two") == "list"
    assert checks.detect_format("You get $102 back.") == "plain"


def test_length_change():
    assert checks.length_change("a" * 100, "a" * 160) == 0.6
    assert checks.length_change("", "abc") == 3.0


def test_valid_json_metric_only_applies_to_json_cases():
    metric = checks.ValidJson()
    assert metric.score(output="hello", expects_json=False).value == 1.0
    assert metric.score(output="hello", expects_json=True).value == 0.0
    assert metric.score(output='{"a": 1}', expects_json=True).value == 1.0


def test_required_fields_metric():
    metric = checks.RequiredFields()
    result = metric.score(output='{"order_id": null, "intent": "other"}', required_fields=["order_id", "intent", "urgency"])
    assert result.value == 0.0 and "urgency" in result.reason
    assert metric.score(output='{"order_id": null, "intent": "other", "urgency": "low"}',
                        required_fields=["order_id", "intent", "urgency"]).value == 1.0


def test_pairwise_checks_fire_on_drift():
    assert checks.SameRefusal().score(output="I can't help with that.", old_output="Sure, here it is.").value == 0.0
    assert checks.SameLength().score(output="a" * 10, old_output="a" * 100).value == 0.0
    assert checks.SameLength().score(output="a" * 120, old_output="a" * 100).value == 1.0
    result = checks.SameFormat().score(output="- a\n- b", old_output="Plain answer.")
    assert result.value == 0.0 and result.reason == "plain -> list"


def test_a_failed_call_is_not_scored():
    result = checks.SameLength().score(output="", old_output="x", error="RateLimitError")
    assert result.scoring_failed
    assert checks.SameLength().score(output="x", old_output=None).scoring_failed
