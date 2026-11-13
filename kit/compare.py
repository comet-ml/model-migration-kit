"""Run the old and new model on the same requests, as two Opik experiments, and
write a one-page report of what changed.

    uv run python -m kit.compare \\
        --cases examples/support-bot/cases.jsonl --system examples/support-bot/system_prompt.md \\
        --old gemini/gemini-2.5-flash --new gemini/gemini-3.5-flash-lite

Model names are LiteLLM names, so any provider works the same way
(openai/gpt-5, anthropic/claude-sonnet-4-5-20250929, ...).

1. The cases go into an Opik dataset (kit/capture.py).
2. The old model answers every case: experiment "<run>-old-<model>", scored on
   the one-answer checks (valid JSON, required fields).
3. The new model answers every case: experiment "<run>-new-<model>", scored on
   the same checks plus the old-vs-new checks (refusal flip, length drift,
   format drift) and the meaning judge (kit/meaning.py).
4. reports/<run>/report.html and results.json.
"""

import argparse
import json
import os
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

import opik
from dotenv import load_dotenv
from opik.evaluation import evaluate

from kit import capture, checks, params as params_lint, report
from kit.llm import complete
from kit.meaning import DEFAULT_JUDGE, MeaningChanged

PROJECT = os.getenv("OPIK_PROJECT_NAME", "model-migration-kit")
# Two at a time keeps a free Gemini key under its per-minute limit.
THREADS = int(os.getenv("MIGRATION_KIT_THREADS", "2"))

PROVIDER_KEYS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def missing_keys(*models: str) -> list[str]:
    missing = []
    for model in models:
        key = PROVIDER_KEYS.get(model.split("/", 1)[0])
        if key and not os.getenv(key) and not (key == "GEMINI_API_KEY" and os.getenv("GOOGLE_API_KEY")):
            missing.append(f"{key} (for {model})")
    return sorted(set(missing))


def make_task(model: str, old_answers: dict[str, dict] | None = None, params: dict | None = None):
    """The function Opik calls once per dataset item."""

    def run_case(item: dict) -> dict:
        messages = ([{"role": "system", "content": item["system"]}] if item.get("system") else []) + [
            {"role": "user", "content": item["input"]}
        ]
        old = (old_answers or {}).get(item["case"], {})
        try:
            # The same request parameters your app sends today, on both models.
            reply = complete(model, messages, **(params or {}))
        except Exception as error:  # noqa: BLE001 (one failed case shouldn't stop the run)
            return {"output": "", "error": f"{type(error).__name__}: {str(error)[:300]}",
                    "old_output": old.get("output"), "latency_s": None, "input_tokens": None,
                    "output_tokens": None, "cost_usd": None}
        return {
            "output": reply["text"],
            "error": None if reply["text"].strip() else f"empty answer (finish_reason={reply['finish_reason']})",
            # The old answer rides along so the old-vs-new metrics can read it.
            "old_output": old.get("output") if old and not old.get("error") else None,
            "latency_s": reply["latency_s"],
            "input_tokens": reply["input_tokens"],
            "output_tokens": reply["output_tokens"],
            "cost_usd": reply["cost_usd"],
        }

    return run_case


def run_side(dataset, item_ids, model, role, run_name, metrics, old_answers=None, judge=None, params=None):
    return evaluate(
        dataset=dataset,
        task=make_task(model, old_answers, params),
        scoring_metrics=metrics,
        experiment_name=f"{run_name}-{role}-{model.split('/')[-1]}",
        experiment_config={"role": role, "model": model, "judge_model": judge, "run": run_name, "params": params or {}},
        dataset_item_ids=item_ids,
        task_threads=THREADS,
    )


def by_case(result) -> dict[str, dict]:
    cases = {}
    for test in result.test_results:
        item = test.test_case.dataset_item_content
        cases[item["case"]] = {
            **test.test_case.task_output,
            "item": item,
            "scores": {s.name: s for s in test.score_results},
        }
    return cases


def side_stats(cases: dict[str, dict]) -> dict:
    ran = [c for c in cases.values() if not c.get("error")]
    latencies = [c["latency_s"] for c in ran if c.get("latency_s") is not None]
    costs = [c["cost_usd"] for c in ran if c.get("cost_usd") is not None]
    out_tokens = [c["output_tokens"] for c in ran if c.get("output_tokens") is not None]
    return {
        "answered": len(ran),
        "errors": len(cases) - len(ran),
        "median_latency_s": statistics.median(latencies) if latencies else None,
        "mean_latency_s": statistics.mean(latencies) if latencies else None,
        "total_cost_usd": sum(costs) if len(costs) == len(ran) and costs else None,
        "priced": len(costs),
        "mean_output_tokens": statistics.mean(out_tokens) if out_tokens else None,
        "mean_chars": statistics.mean(len(c["output"]) for c in ran) if ran else None,
    }


def summarize(old_result, new_result, old_model, new_model, judge, run_name, params=None) -> dict:
    old_cases, new_cases = by_case(old_result), by_case(new_result)
    rows, fired_counts = [], {}
    for case_id, new in new_cases.items():
        old = old_cases.get(case_id, {})
        scores = new["scores"]
        fired = []
        for name, score in scores.items():
            if name == "new_vs_old" or score.scoring_failed or score.value >= 1.0:
                continue
            fired.append({"check": name, "reason": score.reason})
            fired_counts[name] = fired_counts.get(name, 0) + 1
        for name, score in old.get("scores", {}).items():  # old model's own JSON misses
            if not score.scoring_failed and score.value < 1.0:
                fired.append({"check": f"old {name}", "reason": score.reason})
                fired_counts[f"old {name}"] = fired_counts.get(f"old {name}", 0) + 1
        meaning = scores.get("same_meaning")
        preference = scores.get("new_vs_old")
        rows.append({
            "case": case_id,
            "category": new["item"].get("category", ""),
            "request": new["item"]["input"],
            "old": old.get("output", ""),
            "new": new.get("output", ""),
            "old_error": old.get("error"),
            "new_error": new.get("error"),
            "fired": fired,
            "meaning_changed": bool(meaning and not meaning.scoring_failed and meaning.value == 0.0),
            "meaning_reason": meaning.reason if meaning else None,
            "meaning_kind": (meaning.metadata or {}).get("kind") if meaning else None,
            "better": (preference.metadata or {}).get("better") if preference and not preference.scoring_failed else None,
        })
    rows.sort(key=lambda r: (not r["meaning_changed"], -len(r["fired"]), r["case"]))
    prefs = [r["better"] for r in rows if r["better"]]
    # A request that ran on the old model and errors on the new one is its own
    # outcome: no quality score ever sees it, and it's the one that pages you.
    failed_on_new = [{"case": r["case"], "error": r["new_error"]} for r in rows if r["new_error"] and not r["old_error"]]
    lint = params_lint.lint(new_model, params or {})
    return {
        "params": params or {},
        "params_lint": [issue.__dict__ for issue in lint],
        "params_lint_has_rules": params_lint.has_rules(new_model),
        "failed_on_new": failed_on_new,
        "run": run_name,
        "run_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "old_model": old_model,
        "new_model": new_model,
        "judge_model": judge,
        "cases": len(rows),
        "meaning_changed": sum(r["meaning_changed"] for r in rows),
        "judged": sum(1 for r in rows if r["meaning_reason"] and not str(r["meaning_reason"]).startswith("not scored")),
        "fired_counts": dict(sorted(fired_counts.items(), key=lambda kv: -kv[1])),
        "preference": {k: prefs.count(k) for k in ("new", "same", "old")},
        "new_vs_old_mean": statistics.mean({"new": 1.0, "same": 0.5, "old": 0.0}[p] for p in prefs) if prefs else None,
        "old_stats": side_stats(old_cases),
        "new_stats": side_stats(new_cases),
        "experiments": {
            "old": {"name": old_result.experiment_name, "url": old_result.experiment_url},
            "new": {"name": new_result.experiment_name, "url": new_result.experiment_url},
        },
        "rows": rows,
    }


def run_comparison(cases: list[dict], old: str, new: str, dataset_name: str, judge: str = DEFAULT_JUDGE,
                   out_dir: str | Path = "reports", params: dict | None = None) -> tuple[dict, Path]:
    run_name = "migration-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    dataset, item_ids = capture.to_dataset(cases, dataset_name, PROJECT)
    single = [check() for check in checks.SINGLE_CHECKS]
    try:
        old_result = run_side(dataset, item_ids, old, "old", run_name, single, judge=judge, params=params)
        old_answers = {k: v for k, v in by_case(old_result).items()}
        new_metrics = single + [check() for check in checks.PAIRWISE_CHECKS] + [MeaningChanged(model=judge)]
        new_result = run_side(dataset, item_ids, new, "new", run_name, new_metrics, old_answers, judge=judge, params=params)
    finally:
        opik.flush_tracker()  # send buffered traces before the script exits
    summary = summarize(old_result, new_result, old, new, judge, run_name, params)
    path = report.write(summary, Path(out_dir) / run_name)
    return summary, path


def print_summary(summary: dict, path: Path) -> None:
    o, n = summary["old_stats"], summary["new_stats"]
    print(f"\n{summary['old_model']} -> {summary['new_model']}  ({summary['cases']} cases, judge {summary['judge_model']})")
    print(f"  changed meaning: {summary['meaning_changed']} of {summary['judged']} judged")
    for name, count in summary["fired_counts"].items():
        print(f"  {name:<22} fired on {count}")
    p = summary["preference"]
    print(f"  judge preferred: new {p['new']}, same {p['same']}, old {p['old']}")
    fmt = lambda v, f: "n/a" if v is None else f.format(v)  # noqa: E731
    print(f"  median latency: {fmt(o['median_latency_s'], '{:.2f}s')} -> {fmt(n['median_latency_s'], '{:.2f}s')}")
    print(f"  total cost:     {fmt(o['total_cost_usd'], '${:.4f}')} -> {fmt(n['total_cost_usd'], '${:.4f}')}")
    print(f"  errors:         {o['errors']} -> {n['errors']}")
    print(f"  failed on new model only: {len(summary['failed_on_new'])}")
    for failure in summary["failed_on_new"][:5]:
        print(f"    - {failure['case']}: {failure['error'][:160]}")
    if summary["params"]:
        print(f"  request params {summary['params']}: " + (
            "; ".join(f"{i['effect']} {i['param']} ({i['why']})" for i in summary["params_lint"]) or
            ("nothing flagged by the migration guide" if summary["params_lint_has_rules"] else "no sourced rules for this model")))
    for side in ("old", "new"):
        print(f"  {side} experiment: {summary['experiments'][side]['url']}")
    print(f"  report: {path.resolve()}")


def load_cases(cases_path: str | None, dataset_name: str | None, system: str | None = None) -> list[dict]:
    """Cases from a file, or else from an existing Opik dataset. Exits with a clear message otherwise."""
    if cases_path:
        return capture.load_file(cases_path, system)
    if not dataset_name:
        sys.exit("Give --cases <file>, or --dataset <name> to read an existing Opik dataset "
                 "(for example one written by: python -m kit.capture --from-opik-project <project> --dataset <name>).")
    cases = capture.from_opik_dataset(dataset_name, PROJECT, system)
    if not cases:
        sys.exit(f"Opik dataset '{dataset_name}' has no usable items (each needs an 'input').")
    return cases


def main(argv=None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", help=".jsonl or .csv of requests (or use --dataset alone)")
    parser.add_argument("--system", help="file with the system prompt for every case")
    parser.add_argument("--old", required=True, help="LiteLLM name of the model you run today")
    parser.add_argument("--new", required=True, help="LiteLLM name of the replacement")
    parser.add_argument("--judge", default=DEFAULT_JUDGE, help=f"LiteLLM name of the judge (default {DEFAULT_JUDGE})")
    parser.add_argument("--dataset", help="Opik dataset: with --cases it's written to, without it it's read "
                        "(e.g. one kit.capture --from-opik-project made). Default with --cases: model-migration-cases")
    parser.add_argument("--limit", type=int, help="only the first N cases")
    parser.add_argument("--params", default="{}",
                        help='JSON of the request parameters your app sends, e.g. \'{"temperature": 0.2}\'')
    args = parser.parse_args(argv)
    missing = missing_keys(args.old, args.new, args.judge)
    if missing:
        sys.exit("Missing keys: " + ", ".join(missing) + ". Copy .env.example to .env and fill it in.")
    system = Path(args.system).read_text() if args.system else None
    cases = load_cases(args.cases, args.dataset, system)[: args.limit]
    params = json.loads(args.params)
    for issue in params_lint.lint(args.new, params):
        print(f"{issue.effect.upper()} on {args.new}: {issue.param}: {issue.why} ({issue.source})")
    dataset_name = args.dataset or "model-migration-cases"
    summary, path = run_comparison(cases, args.old, args.new, dataset_name, args.judge, params=params)
    print_summary(summary, path)


if __name__ == "__main__":
    main()
