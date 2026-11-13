"""Ten sample support requests, the retiring model vs its replacement, in about two minutes.

    uv run quickstart.py
    uv run quickstart.py --old openai/gpt-5 --new openai/gpt-6.1-sol
    uv run quickstart.py --no-opik        # report only, nothing sent to Opik

The requests are synthetic (a made-up kitchenware store), not anyone's data.
The pair comes from the first provider key in .env (Gemini, OpenAI, Anthropic):
the retiring model and its replacement from kit/retirements.yaml. Both answer
the same 10 requests, logged as two Opik experiments, and it prints what
changed and one link that opens both side by side. For your own requests and
models, see kit/compare.py.
"""

import argparse
from pathlib import Path

from kit import capture, compare, config, llm, preflight, retirements

EXAMPLE = Path(__file__).parent / "examples" / "support-bot"

# One retiring model per provider; its LiteLLM name and replacement come from kit/retirements.yaml.
RETIRING = {"gemini": "gemini-2.5-flash", "openai": "gpt-5", "anthropic": "claude-sonnet-4-5-20250929"}
# Only what each pair accepts: Sonnet 5.5 rejects temperature, and gpt-5 only takes the default.
PARAMS = {"gemini": {"temperature": 0.2, "max_tokens": 1024}, "openai": {}, "anthropic": {"max_tokens": 1024}}

# Ten of the 30: plain answers, JSON, refusals, prompt-injection traps and math.
SAMPLE = (
    "plain-01-return-window", "plain-07-shipping-refund", "json-01-status", "json-03-no-id",
    "refuse-02-discount-code", "refuse-04-medical", "trap-01-system-note", "trap-03-two-asks",
    "math-01-restocking", "math-04-partial-return",
)


def default_pair() -> tuple[str, str, str]:
    """(old, new, provider) for the first provider you have a key for."""
    rows = {row["model"]: row for row in retirements.load()}
    for provider, model in RETIRING.items():
        row = rows[model]
        if config.has_key(row["litellm"]):
            return row["litellm"], f"{provider}/{row['replacement']}", provider
    raise SystemExit("No model key found. Copy .env.example to .env and set one of GEMINI_API_KEY, "
                     "OPENAI_API_KEY or ANTHROPIC_API_KEY.")


def main(argv=None) -> None:
    settings = config.load()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old", help="LiteLLM name of the retiring model (default: from your keys)")
    parser.add_argument("--new", help="LiteLLM name of the replacement")
    parser.add_argument("--judge", default=settings.judge, help="LiteLLM name of the judge")
    parser.add_argument("--no-opik", action="store_true", help="report only: nothing is sent to Opik")
    args = parser.parse_args(argv)
    if bool(args.old) != bool(args.new):
        parser.error("give both --old and --new, or neither")
    old, new, provider = (args.old, args.new, config.provider(args.old)) if args.old else default_pair()
    judge, warning = config.pick_judge(old, new, args.judge)
    print(f"Comparing {old} -> {new} on 10 sample requests (judge: {judge})")
    if warning:
        print(f"Note: {warning}")

    if args.no_opik:
        import opik

        opik.set_tracing_active(False)
    else:
        preflight.opik_ready()
    preflight.models_ready(old, new, judge)
    cases = capture.load_file(EXAMPLE / "cases.jsonl", system=(EXAMPLE / "system_prompt.md").read_text(encoding="utf-8"))
    sample = [case for case in cases if case["case"] in SAMPLE]
    llm.set_deadline(15)
    summary, report = compare.run_comparison(sample, old, new, "migration-kit-quickstart", judge, settings=settings,
                                             params=PARAMS.get(provider, {}), use_opik=not args.no_opik)
    for row in [r for r in summary["rows"] if r["meaning_changed"]][:3]:
        print(f"\n{row['case']}: {row['meaning_reason']}\n  old: {row['old'][:160]!r}\n  new: {row['new'][:160]!r}")
    compare.print_summary(summary, report)  # ends with the link to both experiments in Opik


if __name__ == "__main__":
    main()
