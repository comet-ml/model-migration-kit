"""Does the request your app sends today even run on the new model?

A static lint, no API call: give it the parameters your app sends and the
target model, and it lists what the provider's migration guide says will fail
(HTTP 400) or must change, with the source. Run it before compare.py; a
request that 400s on the new model is the worst kind of regression, because no
quality score ever sees it.

    uv run python -m kit.params --model anthropic/claude-sonnet-5-5 \\
        --params '{"temperature": 0.2, "thinking": {"type": "enabled", "budget_tokens": 2048}}'

Only rules from the provider pages below are listed (checked 2026-11-13). A
model with no rules here isn't "safe", it just has no sourced rule yet:
compare.py still records every call that fails on the new model.
"""

import argparse
import json
from dataclasses import dataclass

ANTHROPIC_GUIDE = "https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide"
GEMINI_38_GUIDE = "https://aistudio.google.com/docs/whats-new-gemini-3.8"
OPENAI_GUIDE = "https://developers.openai.com/api/docs/guides/latest-model"


@dataclass(frozen=True)
class Issue:
    param: str
    effect: str  # "fails" (HTTP 400) or "change" (remove or rename before you switch)
    why: str
    source: str


def _assistant_prefill(messages: list[dict] | None) -> bool:
    return bool(messages) and messages[-1].get("role") in ("assistant", "model")


def _anthropic_sonnet_5_5(params: dict, messages: list[dict] | None) -> list[Issue]:
    issues = []
    thinking = params.get("thinking")
    if isinstance(thinking, dict) and "budget_tokens" in thinking:
        issues.append(Issue("thinking.budget_tokens", "fails", "thinking budgets are not accepted", ANTHROPIC_GUIDE))
    if isinstance(thinking, dict) and thinking.get("type") == "disabled":
        issues.append(Issue("thinking.type", "fails", "thinking: disabled is not accepted", ANTHROPIC_GUIDE))
    for name in ("temperature", "top_p", "top_k"):
        if name in params:
            issues.append(Issue(name, "fails", f"{name} is not accepted", ANTHROPIC_GUIDE))
    tool_choice = params.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("type") in ("tool", "any"):
        issues.append(Issue("tool_choice", "fails", "forced tool_choice is not accepted", ANTHROPIC_GUIDE))
    if _assistant_prefill(messages):
        issues.append(Issue("messages[-1]", "fails", "assistant prefill (ending on an assistant turn) is not accepted",
                            ANTHROPIC_GUIDE))
    if "output_format" in params:
        issues.append(Issue("output_format", "change", "renamed to output_config.format", ANTHROPIC_GUIDE))
    issues.append(Issue("(tokens)", "change", "about 30% more tokens for the same text: recheck max_tokens and cost",
                        ANTHROPIC_GUIDE))
    return issues


def _gemini_3_8(params: dict, messages: list[dict] | None) -> list[Issue]:
    issues = []
    if "thinking_budget" in params or "thinking_budget" in (params.get("thinking_config") or {}):
        issues.append(Issue("thinking_budget", "change", "replaced by thinking_level", GEMINI_38_GUIDE))
    level = params.get("thinking_level") or (params.get("thinking_config") or {}).get("thinking_level")
    if level == "minimal":
        issues.append(Issue("thinking_level", "fails", "thinking_level minimal errors on 3.8 Flash", GEMINI_38_GUIDE))
    for name in ("temperature", "top_p", "top_k", "candidate_count", "n"):
        if name in params:
            issues.append(Issue(name, "change", f"remove {name} (the guide says to drop it on 3.8)", GEMINI_38_GUIDE))
    if _assistant_prefill(messages):
        issues.append(Issue("messages[-1]", "change", "remove prefilled model turns", GEMINI_38_GUIDE))
    return issues


def _openai_latest(params: dict, messages: list[dict] | None, model: str) -> list[Issue]:
    issues = []
    effort = params.get("reasoning_effort") or (params.get("reasoning") or {}).get("effort")
    is_sol = "sol" in model
    if is_sol and effort == "none":
        issues.append(Issue("reasoning.effort", "fails", "Sol does not support effort none; use low", OPENAI_GUIDE))
    if effort != "none" or is_sol:
        for name in ("temperature", "top_p", "top_logprobs"):
            if name in params:
                issues.append(Issue(name, "change", f"remove {name} when reasoning effort isn't none", OPENAI_GUIDE))
    if ("sol" in model or "terra" in model) and params.get("tools") and not params.get("use_responses_api"):
        issues.append(Issue("tools", "change", "tool calling needs the Responses API on Sol and Terra", OPENAI_GUIDE))
    return issues


def lint(target_model: str, params: dict, messages: list[dict] | None = None) -> list[Issue]:
    """What breaks or must change when `params` are sent to `target_model`."""
    name = target_model.split("/")[-1]
    if name.startswith("claude-sonnet-5-5"):
        return _anthropic_sonnet_5_5(params, messages)
    if name.startswith("gemini-3.8"):
        return _gemini_3_8(params, messages)
    if name.startswith("gpt-6"):
        return _openai_latest(params, messages, name)
    return []


def has_rules(target_model: str) -> bool:
    name = target_model.split("/")[-1]
    return name.startswith(("claude-sonnet-5-5", "gemini-3.8", "gpt-6"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="the model you're moving to (LiteLLM name)")
    parser.add_argument("--params", default="{}", help="JSON of the parameters your app sends")
    args = parser.parse_args()
    found = lint(args.model, json.loads(args.params))
    if not has_rules(args.model):
        print(f"No sourced rules for {args.model} yet. Run compare.py: it records calls that fail on the new model.")
    for issue in found:
        print(f"{issue.effect.upper():<7} {issue.param}: {issue.why}  ({issue.source})")
    if has_rules(args.model) and not found:
        print("Nothing in these parameters is flagged by the migration guide.")
