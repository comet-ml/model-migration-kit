"""One call to any provider's model through LiteLLM, with retries, traced in Opik.

Model names are LiteLLM names: "gemini/gemini-2.5-flash", "openai/gpt-5",
"anthropic/claude-sonnet-4-5-20250929". Each provider reads its own key from
the environment (GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY).
"""

import time

import litellm
from opik.integrations.litellm import track_completion

# Inside an Opik evaluation this becomes an LLM span under the case's trace,
# with the model, tokens and usage.
_tracked_completion = track_completion()(litellm.completion)

# Free keys hit per-minute limits during an evaluation. These are worth a retry;
# anything else (a bad key, a bad model name) fails at once.
RETRYABLE = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.Timeout,
    litellm.APIConnectionError,
)


def complete(model: str, messages: list[dict], max_attempts: int = 6, first_wait_s: float = 5, **kwargs) -> dict:
    """Call `model` and return its text plus latency, tokens and cost (None when unknown)."""
    wait = first_wait_s
    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = _tracked_completion(model=model, messages=messages, **kwargs)
            break
        except RETRYABLE:
            if attempt == max_attempts:
                raise
            time.sleep(wait)
            wait = min(wait * 2, 60)
    latency = time.perf_counter() - started
    usage = getattr(response, "usage", None)
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 (LiteLLM has no price for this model)
        cost = None
    return {
        "text": response.choices[0].message.content or "",
        "finish_reason": response.choices[0].finish_reason,
        "latency_s": latency,
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "cost_usd": cost or None,
    }
