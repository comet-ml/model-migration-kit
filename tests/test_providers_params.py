"""The OpenAI and Anthropic paths, tested with LiteLLM's mock_response (no keys, no network)."""

import pytest

from kit import compare, config, params
from kit.llm import complete


@pytest.mark.parametrize("model", ["openai/gpt-5", "anthropic/claude-sonnet-4-5-20250929", "gemini/gemini-2.5-flash"])
def test_complete_goes_through_litellm_for_every_provider(model):
    reply = complete(model, [{"role": "user", "content": "hi"}], mock_response="hello")
    assert reply["text"] == "hello"
    assert reply["latency_s"] >= 0


def test_missing_keys_names_the_provider_key(monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert config.missing_keys("openai/gpt-5", "anthropic/claude-sonnet-5-5") == [
        "ANTHROPIC_API_KEY (for anthropic/claude-sonnet-5-5)",
        "OPENAI_API_KEY (for openai/gpt-5)",
    ]


def test_a_failing_call_becomes_an_error_not_a_crash(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("400: temperature is not supported")

    monkeypatch.setattr(compare.llm, "complete", boom)
    out = compare.make_task("anthropic/claude-sonnet-5-5", {"item-1": {"output": "old answer"}})(
        {"id": "item-1", "case": "c1", "input": "hi", "system": ""}
    )
    assert out["output"] == "" and "temperature" in out["error"] and out["old_output"] == "old answer"


def test_sonnet_5_5_lint_flags_what_returns_400():
    found = params.lint(
        "anthropic/claude-sonnet-5-5",
        {"temperature": 0.2, "thinking": {"type": "enabled", "budget_tokens": 2048},
         "tool_choice": {"type": "tool", "name": "x"}},
        messages=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "{"}],
    )
    fails = {issue.param for issue in found if issue.effect == "fails"}
    assert fails == {"temperature", "thinking.budget_tokens", "tool_choice", "messages[-1]"}
    assert all(issue.source.startswith("https://") for issue in found)


def test_gemini_3_8_lint():
    found = params.lint("gemini/gemini-3.8-flash", {"temperature": 0.2, "thinking_level": "minimal"})
    assert {(i.param, i.effect) for i in found} == {("temperature", "change"), ("thinking_level", "fails")}


def test_openai_sol_lint():
    found = params.lint("openai/gpt-6.1-sol", {"reasoning_effort": "none", "temperature": 0.2, "tools": [{}]})
    assert {i.param for i in found} == {"reasoning.effort", "temperature", "tools"}


def test_models_without_sourced_rules_return_nothing():
    assert params.lint("gemini/gemini-3.5-flash-lite", {"temperature": 0.2}) == []
    assert not params.has_rules("gemini/gemini-3.5-flash-lite")
