"""The one AI judge: did the new answer change what the old answer said?

Aggregate quality scores can stay flat while individual answers say different
things: a different refund amount, a yes that became a no, a promise the old
model never made. This judge reads the request, the old answer and the new
answer, and says whether the new one changes a fact, a decision, an action or
a promise. Wording, tone, length and formatting don't count; the code checks
in checks.py cover those.

Use a judge model that is neither the old nor the new model, so it isn't
grading its own answers. The 2026-11-13 run used gemini-3.8-flash to judge
gemini-2.5-flash vs gemini-3.5-flash-lite.
"""

import json

from opik.evaluation.metrics import base_metric, score_result

from kit.checks import not_scored, strip_fence
from kit.llm import complete

DEFAULT_JUDGE = "gemini/gemini-3.8-flash"  # compare.py picks one you have a key for (kit/config.py)
JSON_MODE_PROVIDERS = ("gemini", "openai", "azure", "vertex_ai")  # where response_format json_object is supported

KINDS = ("fact", "decision", "action", "promise", "none")

JUDGE_PROMPT = """You compare two answers an assistant gave to the same request.
OLD came from the model in production today. NEW came from the model replacing it.

Decide whether NEW changes the meaning in a way the user or a downstream system would notice:
- fact: a different number, amount, date, name, status or claim
- decision: a different outcome (approve vs refuse, eligible vs not, yes vs no)
- action: the user is told to do something different, or the assistant says it will do something different
- promise: a commitment, guarantee or timeline that the other answer doesn't make

Do NOT count wording, tone, length, formatting, or extra detail that doesn't contradict the other answer.

Then say which answer better serves the user, following the assistant's instructions if given.

Reply with JSON only:
{{"changed": true or false, "kind": "fact" | "decision" | "action" | "promise" | "none", "reason": "<one line naming exactly what changed, or 'same meaning'>", "better": "old" | "new" | "same"}}

ASSISTANT INSTRUCTIONS:
{system}

REQUEST:
{request}

OLD:
{old}

NEW:
{new}"""


def parse_verdict(text: str) -> dict:
    """Read the judge's JSON. Raises ValueError if it isn't usable."""
    body, _ = strip_fence(text)
    try:
        verdict = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError(f"judge did not return JSON: {text[:200]!r}") from error
    if not isinstance(verdict, dict) or not isinstance(verdict.get("changed"), bool):
        raise ValueError(f"judge JSON has no boolean 'changed': {text[:200]!r}")
    kind = verdict.get("kind") if verdict.get("kind") in KINDS else ("none" if not verdict["changed"] else "fact")
    better = verdict.get("better") if verdict.get("better") in ("old", "new", "same") else "same"
    return {"changed": verdict["changed"], "kind": kind, "reason": str(verdict.get("reason", "")).strip(), "better": better}


def judge(request: str, old: str, new: str, system: str = "", model: str = DEFAULT_JUDGE) -> dict:
    prompt = JUDGE_PROMPT.format(system=system or "(none)", request=request, old=old, new=new)
    extra = {"response_format": {"type": "json_object"}} if model.split("/")[0] in JSON_MODE_PROVIDERS else {}
    reply = complete(model, [{"role": "user", "content": prompt}], track=False, **extra)
    return {**parse_verdict(reply["text"]), "cost_usd": reply.get("cost_usd")}


class MeaningChanged(base_metric.BaseMetric):
    """Two scores per case:
    same_meaning: 1.0 if the new answer means the same as the old, 0.0 if it changed
    new_vs_old:   1.0 new is better, 0.5 the same, 0.0 old is better
    """

    def __init__(self, model: str = DEFAULT_JUDGE, name: str = "same_meaning"):
        super().__init__(name=name)
        self.model = model

    def score(self, input: str, output: str, old_output: str | None = None, system: str = "",
              error: str | None = None, messages: list | None = None, **ignored):
        if error or old_output is None:
            reason = error or "the old model has no answer for this case"
            return [not_scored(self.name, reason, "no_answer"), not_scored("new_vs_old", reason, "no_answer")]
        try:
            # A multi-turn case: the judge reads the whole conversation, not only the last message.
            request = "\n\n".join(f"{t['role'].upper()}: {t['content']}" for t in messages) if messages and len(messages) > 1 else input
            verdict = judge(request, old_output, output, system=system, model=self.model)
        except Exception as failure:  # noqa: BLE001 (a judge failure is not the model's fault)
            reason = f"judge failed: {type(failure).__name__}: {str(failure)[:300]}"
            return [not_scored(self.name, reason, "judge_failed"), not_scored("new_vs_old", reason, "judge_failed")]
        meta = {"status": "judged", "kind": verdict["kind"], "better": verdict["better"], "judge_model": self.model,
                "judge_cost_usd": verdict["cost_usd"]}
        return [
            score_result.ScoreResult(
                name=self.name,
                value=0.0 if verdict["changed"] else 1.0,
                reason=f"{verdict['kind']}: {verdict['reason']}" if verdict["changed"] else verdict["reason"],
                metadata=meta,
            ),
            score_result.ScoreResult(
                name="new_vs_old",
                value={"new": 1.0, "same": 0.5, "old": 0.0}[verdict["better"]],
                reason=f"better: {verdict['better']}",
                metadata=meta,
            ),
        ]
