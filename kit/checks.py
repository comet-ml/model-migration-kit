"""Rules checked in code, not by an AI judge.

Two kinds:
  - one answer at a time: valid JSON when JSON is expected, required fields present
  - old answer vs new answer: refusal flip, length drift, format drift

Each check is a plain function (easy to test, easy to reuse) plus a thin Opik
metric around it. Opik calls a metric's score() with the dataset item's fields
and the task's output, matched by argument name; extras land in **ignored.

Every metric scores 1.0 for "fine / unchanged" and 0.0 for "fired", so higher
is better in Opik like any other score.
"""

import json
import re

from opik.evaluation.metrics import base_metric, score_result

LENGTH_DRIFT_LIMIT = 0.5  # a change of more than 50% in characters

FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)

# An answer whose first 200 characters match is treated as a refusal. Answers
# that help often say "I can't" further down, so only the opening is read.
REFUSAL = re.compile(
    r"\b(I can(?:not|'t|’t)|I'm (?:not able|unable)|I am (?:not able|unable)|I (?:won't|will not) be able"
    r"|I (?:must|have to) decline|I'm sorry,? but|unfortunately,? (?:I|we) (?:can(?:not|'t|’t)|are unable|aren't able)"
    r"|(?:not|isn't|is not) (?:something )?(?:I'm |I am )?(?:able|allowed|permitted) to"
    r"|against (?:our|the) policy|I'm not (?:qualified|permitted) to|I am not (?:qualified|permitted) to)",
    re.IGNORECASE,
)
REFUSAL_WINDOW = 200


def strip_fence(text: str) -> tuple[str, bool]:
    """Remove one Markdown code fence around the whole answer, if there is one."""
    match = FENCE.match(text.strip())
    return (match.group(1).strip(), True) if match else (text.strip(), False)


def parse_json(text: str) -> tuple[object | None, str]:
    """Parse an answer as JSON. Returns (value or None, how it went)."""
    body, fenced = strip_fence(text)
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, TypeError) as error:
        return None, f"not valid JSON ({error.msg if hasattr(error, 'msg') else error})"
    if value is None:
        return None, "the answer is JSON null"
    return value, "valid JSON inside a code fence" if fenced else "valid JSON"


def is_refusal(text: str) -> bool:
    return bool(REFUSAL.search(text.strip()[:REFUSAL_WINDOW]))


def detect_format(text: str) -> str:
    """json, json-fenced, markdown, list or plain."""
    body, fenced = strip_fence(text)
    if body[:1] in "{[":
        try:
            json.loads(body)
            return "json-fenced" if fenced else "json"
        except json.JSONDecodeError:
            pass
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if any(re.match(r"^#{1,6}\s", line) or line.startswith("|---") or line.startswith("| ---") for line in lines) or "**" in body:
        return "markdown"
    if sum(bool(re.match(r"^([-*•]|\d+[.)])\s", line)) for line in lines) >= 2:
        return "list"
    return "plain"


def length_change(old: str, new: str) -> float:
    """Relative change in length, new vs old: 0.5 = 50% longer, -0.5 = 50% shorter."""
    return (len(new) - len(old)) / max(len(old), 1)


def missing_fields(value: object, required: list[str]) -> list[str]:
    if not isinstance(value, dict):
        return list(required)
    return [field for field in required if field not in value]


# ---- Opik metrics -------------------------------------------------------------


def _result(name: str, ok: bool, reason: str) -> score_result.ScoreResult:
    return score_result.ScoreResult(name=name, value=1.0 if ok else 0.0, reason=reason)


def not_scored(name: str, error: str, status: str = "no_answer") -> score_result.ScoreResult:
    """Nothing to score (a failed call, or a failed judge): kept out of averages.

    status says which: "no_answer" (a model call failed) or "judge_failed".
    """
    return score_result.ScoreResult(name=name, value=0.0, reason=f"not scored: {error}", scoring_failed=True,
                                    metadata={"status": status})


class ValidJson(base_metric.BaseMetric):
    """0.0 if the case expects JSON and the answer doesn't parse (a code fence is allowed)."""

    def __init__(self, name: str = "json_valid"):
        super().__init__(name=name)

    def score(self, output: str, expects_json: bool = False, error: str | None = None, **ignored):
        if error:
            return not_scored(self.name, error)
        if not expects_json:
            return _result(self.name, True, "no JSON expected")
        value, how = parse_json(output)
        return _result(self.name, value is not None, how)


class RequiredFields(base_metric.BaseMetric):
    """0.0 if the case expects JSON fields and any are missing."""

    def __init__(self, name: str = "required_fields"):
        super().__init__(name=name)

    def score(self, output: str, required_fields: list[str] | None = None, error: str | None = None, **ignored):
        if error:
            return not_scored(self.name, error)
        if not required_fields:
            return _result(self.name, True, "no fields required")
        value, _ = parse_json(output)
        missing = missing_fields(value, required_fields)
        return _result(self.name, not missing, f"missing {missing}" if missing else f"all of {required_fields}")


class _Pairwise(base_metric.BaseMetric):
    """Base for checks that compare the new answer with the old one."""

    def score(self, output: str, old_output: str | None = None, error: str | None = None, **ignored):
        if error:
            return not_scored(self.name, error)
        if old_output is None:
            return not_scored(self.name, "the old model has no answer for this case")
        return self.compare(old_output, output)


class SameRefusal(_Pairwise):
    """0.0 if one model refused and the other answered."""

    def __init__(self, name: str = "same_refusal"):
        super().__init__(name=name)

    def compare(self, old: str, new: str):
        before, after = is_refusal(old), is_refusal(new)
        if before == after:
            return _result(self.name, True, "both refused" if before else "both answered")
        return _result(self.name, False, "old refused, new answered" if before else "old answered, new refused")


class SameLength(_Pairwise):
    """0.0 if the answer got more than 50% longer or shorter."""

    def __init__(self, name: str = "same_length"):
        super().__init__(name=name)

    def compare(self, old: str, new: str):
        change = length_change(old, new)
        reason = f"{len(old)} -> {len(new)} characters ({change:+.0%})"
        return _result(self.name, abs(change) <= LENGTH_DRIFT_LIMIT, reason)


class SameFormat(_Pairwise):
    """0.0 if the answer's shape changed (JSON, fenced JSON, Markdown, list, plain)."""

    def __init__(self, name: str = "same_format"):
        super().__init__(name=name)

    def compare(self, old: str, new: str):
        before, after = detect_format(old), detect_format(new)
        return _result(self.name, before == after, f"{before} -> {after}" if before != after else before)


SINGLE_CHECKS = [ValidJson, RequiredFields]
PAIRWISE_CHECKS = [SameRefusal, SameLength, SameFormat]
