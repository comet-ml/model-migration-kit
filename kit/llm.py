"""One call to any provider's model through LiteLLM, with retries, traced in Opik.

Model names are LiteLLM names: "gemini/gemini-2.5-flash", "openai/gpt-5",
"anthropic/claude-sonnet-4-5-20250929". Each provider reads its own key from
the environment (GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY).
"""

import random
import sys
import time

import litellm
from opik.integrations.litellm import track_completion

litellm.suppress_debug_info = True  # errors are reported per case; skip LiteLLM's help banner

# Inside an Opik evaluation this becomes an LLM span under the case's trace,
# with the model, tokens and usage.
_tracked_completion = track_completion()(litellm.completion)

# Rate limits and outages are worth a retry. A bad key, no access or a bad model
# name fails at once: retrying those only burns the time budget.
RETRYABLE = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.BadGatewayError,
    litellm.Timeout,
    litellm.APIConnectionError,
)
NOT_RETRYABLE = (litellm.AuthenticationError, litellm.PermissionDeniedError, litellm.NotFoundError,
                 litellm.BadRequestError)

TIMEOUT_S = 90  # one request
_deadline: float | None = None  # monotonic time after which nothing is retried


def set_deadline(minutes: float | None) -> None:
    """Stop retrying after this many minutes, so a rate-limited run ends instead of crawling."""
    global _deadline
    _deadline = time.monotonic() + minutes * 60 if minutes else None


def complete(model: str, messages: list[dict], max_attempts: int | None = None, first_wait_s: float = 5,
             track: bool = True, **kwargs) -> dict:
    """Call `model` and return its text plus latency, tokens and cost (None when unknown).

    Rate limits and outages are retried with backoff (5s, doubling, at most 60s
    apart) until the deadline from set_deadline(), or 6 attempts when there is
    no deadline. latency_s is the successful attempt only. track=False keeps the
    call out of Opik (the judge: its time and cost would otherwise land in the
    new model's traces and make it look slower and costlier).
    """
    call = _tracked_completion if track else litellm.completion
    kwargs.setdefault("timeout", TIMEOUT_S)
    limit = max_attempts or (None if _deadline is not None else 6)
    wait, attempt = first_wait_s, 0
    while True:
        attempt += 1
        started = time.perf_counter()
        try:
            response = call(model=model, messages=messages, **kwargs)
            break
        except NOT_RETRYABLE:
            raise
        except RETRYABLE as error:
            out_of_time = _deadline is not None and time.monotonic() + wait > _deadline
            if (limit is not None and attempt >= limit) or out_of_time:
                raise
            print(f"  {model}: {type(error).__name__}, retry {attempt} in {wait:.0f}s", file=sys.stderr, flush=True)
            time.sleep(wait + random.uniform(0, 1))
            wait = min(wait * 2, 60)
    latency = time.perf_counter() - started
    usage = getattr(response, "usage", None)
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 (LiteLLM has no price for this model)
        cost = None
    message = response.choices[0].message
    tool_calls = [
        {"name": call.function.name, "arguments": call.function.arguments}
        for call in (getattr(message, "tool_calls", None) or [])
    ]
    return {
        "text": message.content or "",
        "tool_calls": tool_calls,
        "finish_reason": response.choices[0].finish_reason,
        "latency_s": latency,
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "cost_usd": cost or None,
    }
