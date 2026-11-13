"""Checks that run before anything is created in Opik or any case is sent.

opik_ready():  is Opik configured? On a terminal, offer to set it up (one key paste).
models_ready(): one tiny call per distinct model, with a plain message for each
                way it can fail (no key, no access, unknown name).
"""

import sys

import litellm
import opik
from opik.config import OpikConfig

from kit import config

GEMINI_25_NOTE = (
    "Google limits Gemini 2.5 to accounts that used it before (https://aistudio.google.com/docs/deprecations). "
    "With a new key, try a pair you can reach, e.g. --old gemini/gemini-3.5-flash-lite --new gemini/gemini-3.8-flash, "
    "or an OpenAI or Anthropic key."
)


def _check_connection() -> None:
    """A wrong key or an unreachable server stops here, before any paid model call."""
    try:
        opik.Opik().auth_check()
    except Exception as error:  # noqa: BLE001 (the SDK's auth and connection errors vary)
        sys.exit(f"Opik is set up but the connection failed ({type(error).__name__}: {str(error)[:200]}).\n"
                 "Check OPIK_API_KEY and OPIK_WORKSPACE in .env (OPIK_WORKSPACE is the workspace name shown in Opik), "
                 "or OPIK_URL_OVERRIDE for a self-hosted Opik.")


def opik_ready(interactive: bool | None = None) -> None:
    """Exit with three clear lines if Opik isn't configured (or offer to configure it on a terminal)."""
    misconfigured, _ = OpikConfig().get_misconfiguration_detection_results()
    if not misconfigured:
        _check_connection()
        return
    link = config.links("cli")
    interactive = sys.stdin.isatty() if interactive is None else interactive
    if interactive:
        print(f"Opik isn't set up yet. It stores both runs so you can compare them side by side.\n"
              f"Get a free API key at {link['signup']} and paste it below (or Ctrl-C to stop).")
        try:
            opik.configure()
        except (KeyboardInterrupt, EOFError):
            sys.exit("\nStopped. Run `uv run opik configure` when you're ready.")
        except Exception as error:  # noqa: BLE001 (the configurator's own errors are already readable)
            sys.exit(f"Opik setup didn't finish: {error}")
        if not OpikConfig().get_misconfiguration_detection_results()[0]:
            _check_connection()
            return
    sys.exit(
        "Opik isn't configured. Pick one:\n"
        f"  1. Free Opik Cloud account: {link['signup']} then put OPIK_API_KEY and OPIK_WORKSPACE in .env\n"
        "  2. Or run `uv run opik configure` once\n"
        f"  3. Or self-host Opik ({link['self_host']}) and set OPIK_URL_OVERRIDE\n"
        "No account yet? Add --no-opik for a report-only run."
    )


def explain(model: str, role: str, error: Exception) -> str:
    """One readable line for a model that can't answer."""
    text = str(error)
    hint = " Pass --judge <model> to use a judge from a provider you have a key for." if role == "judge" else ""
    if isinstance(error, litellm.AuthenticationError):
        return f"{role} model {model}: the credentials were rejected. Check them in .env.{hint}"
    if "existing users" in text or "new users" in text or ("gemini-2.5" in model and isinstance(
            error, (litellm.NotFoundError, litellm.PermissionDeniedError))):
        return f"{role} model {model}: this key has no access to it. {GEMINI_25_NOTE}"
    if isinstance(error, litellm.PermissionDeniedError):
        return f"{role} model {model}: this key has no access to it.{hint}"
    if isinstance(error, litellm.NotFoundError) or "LLM Provider NOT provided" in text:
        return (f"{role} model {model}: unknown model name. Use a LiteLLM name such as openai/gpt-5 "
                f"(https://docs.litellm.ai/docs/providers).{hint}")
    return f"{role} model {model}: {type(error).__name__}: {text[:200]}{hint}"


def models_ready(*models: str, judge: str | None = None) -> None:
    """One short call per distinct model (old first, then new, or any list). Exits if one can't answer."""
    names = ["old", "new"] if len(models) == 2 else [f"model {n}" for n in range(1, len(models) + 1)]
    roles = {**dict(zip(names, models)), **({"judge": judge} if judge else {})}
    missing = config.missing_keys(*roles.values())
    if missing:
        judge_hint = (" (the judge is the model that reads both answers; pass --judge <model> "
                      "to use one from a provider you have a key for)") if judge and any(judge in m for m in missing) else ""
        sys.exit(f"Missing {', '.join(missing)}{judge_hint}. Copy .env.example to .env and fill it in.")
    problems, seen = [], set()
    for role, model in roles.items():
        if model in seen:
            continue
        seen.add(model)
        try:
            # Plain LiteLLM, not the traced call: nothing is logged to Opik yet.
            litellm.completion(model=model, messages=[{"role": "user", "content": "Reply with the word OK."}],
                               timeout=60, num_retries=1)
        except Exception as error:  # noqa: BLE001 (each failure becomes a readable line)
            problems.append(explain(model, role, error))
    if problems:
        sys.exit("Stopped before running any cases:\n  " + "\n  ".join(problems))
