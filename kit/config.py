"""Settings and links, shared by every entry point.

Call load() first: it reads .env, then the settings, so a value in .env always
counts. Blank OPIK_* lines (as in .env.example) are dropped, so they don't hide
the ~/.opik.config that `opik configure` writes.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv

REPO = "https://github.com/comet-ml/model-migration-kit"
NEW_ISSUE = REPO + "/issues/new/choose"
DEFAULT_PROJECT = "model-migration-kit"

# Judge candidates, best first. The default judge is the first one whose key you
# have and that is neither the old nor the new model.
JUDGES = ("gemini/gemini-3.8-flash", "openai/gpt-6.1-terra", "anthropic/claude-sonnet-5-5")


def comet_link(path: str, content: str) -> str:
    """A comet.com link that says it came from this repo. content: readme, report or cli."""
    query = urlencode({"utm_source": "github", "utm_medium": "referral",
                       "utm_campaign": "model-migration-kit", "utm_content": content})
    return f"https://www.comet.com{path}?{query}"


def links(content: str) -> dict[str, str]:
    return {
        "signup": comet_link("/signup", content),
        "self_host": comet_link("/docs/opik/self-host/overview", content),
        "rules": comet_link("/docs/opik/production/online-evaluation/rules", content),
        "opik": comet_link("/docs/opik", content),
    }


@dataclass(frozen=True)
class Settings:
    project: str
    judge: str | None  # JUDGE_MODEL, or None to pick one from the keys you have
    threads: int


def load() -> Settings:
    load_dotenv()
    for name in [n for n, v in os.environ.items() if n.startswith("OPIK_") and not v.strip()]:
        del os.environ[name]
    # Model answers can hold any character; a Windows console shouldn't crash on one.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    threads = os.getenv("MIGRATION_KIT_THREADS") or "2"
    if not threads.isdigit() or int(threads) < 1:
        sys.exit(f"MIGRATION_KIT_THREADS must be a whole number, 1 or more (got {threads!r}).")
    return Settings(
        project=os.getenv("OPIK_PROJECT_NAME") or DEFAULT_PROJECT,
        judge=os.getenv("JUDGE_MODEL") or None,
        threads=int(threads),
    )


def provider(model: str) -> str:
    return model.split("/", 1)[0] if "/" in model else ""


def missing_env(model: str) -> list[str]:
    """The environment variables LiteLLM still needs for `model` (any provider LiteLLM knows)."""
    import litellm

    missing = litellm.validate_environment(model).get("missing_keys") or []
    if provider(model) == "gemini" and os.getenv("GOOGLE_API_KEY"):
        return []
    if provider(model) == "bedrock":
        # An AWS profile or SSO login works too; LiteLLM only looks for the key pair.
        has_profile = os.getenv("AWS_PROFILE") or Path.home().joinpath(".aws", "credentials").exists()
        missing = [] if has_profile else missing
        if not (os.getenv("AWS_REGION_NAME") or os.getenv("AWS_REGION")):
            missing = [*missing, "AWS_REGION_NAME"]
    return missing


def has_key(model: str) -> bool:
    return not missing_env(model)


def missing_keys(*models: str) -> list[str]:
    """One line per missing variable, naming the model that needs it."""
    return sorted({f"{name} (for {model})" for model in models for name in missing_env(model)})


def pick_judge(old: str, new: str, configured: str | None = None) -> tuple[str, str | None]:
    """(judge, warning or None). A judge that is the old or new model grades its own answers."""
    judge = configured or next((j for j in JUDGES if has_key(j) and j not in (old, new)), None)
    judge = judge or next((j for j in JUDGES if has_key(j)), JUDGES[0])
    warning = None
    if judge in (old, new):
        warning = (f"The judge ({judge}) is also the {'old' if judge == old else 'new'} model, so it grades its own "
                   "answers. Pass --judge <a model from another family> if you can.")
    return judge, warning
