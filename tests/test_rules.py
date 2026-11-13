"""kit.rules with a fake Opik REST client: the rule it sends, and the IDs it reads back."""

from types import SimpleNamespace

import opik
import pytest

from kit import rules


class FakeEvaluators:
    def __init__(self):
        self.created = None

    def create_automation_rule_evaluator(self, request):
        self.created = request

    def find_evaluators(self, project_id, name, size):
        return SimpleNamespace(content=[SimpleNamespace(id="rule-1")] if self.created else [])


def test_create_sends_a_sampled_policy_judge_on_the_project(monkeypatch):
    evaluators = FakeEvaluators()
    rest = SimpleNamespace(projects=SimpleNamespace(retrieve_project=lambda name: SimpleNamespace(id="proj-1")),
                           automation_rule_evaluators=evaluators)
    monkeypatch.setattr(opik, "Opik", lambda: SimpleNamespace(rest_client=rest))

    assert rules.create("my-app", policy="No refunds over $500.", sampling_rate=0.1) == "rule-1"
    rule = evaluators.created
    assert rule.type == "llm_as_judge" and rule.project_ids == ["proj-1"]
    assert rule.sampling_rate == 0.1 and rule.trigger_scope == "production" and rule.enabled
    prompt = rule.code.messages[0].content
    assert "No refunds over $500." in prompt and "{{input}}" in prompt and "{{output}}" in prompt
    assert rule.code.variables == {"input": "input", "output": "output"}
    assert [(s.name, s.type) for s in rule.code.schema_] == [("follows_policy", "BOOLEAN")]


def test_a_second_create_is_refused_instead_of_doubling_the_rule(monkeypatch):
    evaluators = FakeEvaluators()
    evaluators.created = "an existing rule"
    rest = SimpleNamespace(projects=SimpleNamespace(retrieve_project=lambda name: SimpleNamespace(id="proj-1")),
                           automation_rule_evaluators=evaluators)
    monkeypatch.setattr(opik, "Opik", lambda: SimpleNamespace(rest_client=rest))
    with pytest.raises(SystemExit, match="already has the rule"):
        rules.create("my-app")


def test_the_printed_code_metric_runs():
    namespace = {}
    exec(rules.CODE_METRIC, namespace)  # noqa: S102 (our own constant)
    metric = namespace["RequiredFields"]()
    assert metric.score(output='```json\n{"order_id": 1, "intent": "x", "urgency": "low"}\n```').value == 1.0
    assert metric.score(output='{"order_id": 1}').value == 0.0
