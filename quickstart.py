"""Ten support requests, the old model vs its replacement, in about two minutes.

    uv run quickstart.py

gemini-2.5-flash is rerouted to gemini-3.5-flash-lite on the Gemini API on
Dec 1, 2026. This runs both on 10 sample requests, logs two Opik experiments,
and prints what changed. For your own requests and models, see kit/compare.py.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
for name in ("OPIK_API_KEY", "OPIK_WORKSPACE"):  # blank .env lines would hide `opik configure`
    if os.environ.get(name) == "":
        del os.environ[name]

from kit.capture import load_file  # noqa: E402 (after the .env is loaded)
from kit.compare import missing_keys, print_summary, run_comparison  # noqa: E402

OLD, NEW, JUDGE = "gemini/gemini-2.5-flash", "gemini/gemini-3.5-flash-lite", "gemini/gemini-3.8-flash"
EXAMPLE = Path(__file__).parent / "examples" / "support-bot"

if __name__ == "__main__":
    if missing := missing_keys(OLD, NEW, JUDGE):
        raise SystemExit(f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in.")
    cases = load_file(EXAMPLE / "cases.jsonl", system=(EXAMPLE / "system_prompt.md").read_text())
    sample = cases[::3]  # 10 of the 30: plain answers, JSON, refusals, traps and math
    summary, report = run_comparison(sample, OLD, NEW, "migration-kit-quickstart", JUDGE,
                                     params={"temperature": 0.2, "max_tokens": 1024})
    print_summary(summary, report)
    for row in [r for r in summary["rows"] if r["meaning_changed"]][:3]:
        print(f"\n{row['case']}: {row['meaning_reason']}\n  old: {row['old'][:160]!r}\n  new: {row['new'][:160]!r}")
