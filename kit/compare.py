"""Run the old and new model on the same requests, as two Opik experiments, and
write a one-page report of what changed.

    uv run python -m kit.compare \\
        --cases examples/support-bot/cases.jsonl --system examples/support-bot/system_prompt.md \\
        --old gemini/gemini-2.5-flash --new gemini/gemini-3.5-flash-lite

Model names are LiteLLM names, so any provider works the same way
(openai/gpt-5, anthropic/claude-sonnet-4-5-20250929, azure/<deployment>,
bedrock/<model-id>, vertex_ai/<model>, ...).

1. The cases go into an Opik dataset (kit/capture.py).
2. The old model answers every case: experiment "<run>-old-<model>", scored on
   the one-answer checks (valid JSON, required fields).
3. The new model answers every case: experiment "<run>-new-<model>", scored on
   the same checks plus the old-vs-new checks (refusal flip, length drift,
   format drift) and the meaning judge (kit/meaning.py).
4. reports/<run>/report.html and results.json, and one link that opens both
   experiments side by side in Opik.

--no-opik runs the same checks on your machine and writes only the report.
Exit status: 0 done, 2 the run can't tell you anything (no answers, nothing
judged), 3 more answers changed meaning than --fail-on-changed allows.
"""

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from kit import capture, checks, config, llm, preflight, report
from kit import params as params_lint
from kit.meaning import MeaningChanged

RESERVED_PARAMS = ("messages", "model", "stream")  # the kit sets these itself
EXIT_UNUSABLE, EXIT_TOO_MANY_CHANGED = 2, 3


# ---- one side: run a model on every case ---------------------------------------


def answer_fields(reply: dict) -> dict:
    """What the model returned, with an outcome: answered, truncated, tool_call or empty."""
    text, finish = reply["text"], reply["finish_reason"]
    error, outcome = None, "answered"
    if reply.get("tool_calls"):
        # A tool call is an answer, not an error: record it as text so the checks can compare it.
        calls = "; ".join(f"{call['name']}({call['arguments']})" for call in reply["tool_calls"])
        text, outcome = (text + "\n" if text.strip() else "") + f"[tool call] {calls}", "tool_call"
    elif not text.strip():
        outcome = "empty"
        error = ("cut off before any text (finish_reason=length): raise max_tokens" if finish == "length"
                 else f"empty answer (finish_reason={finish})")
    elif finish == "length":
        outcome = "truncated"
    return {
        "output": text, "error": error, "outcome": outcome, "latency_s": reply["latency_s"],
        "input_tokens": reply["input_tokens"], "output_tokens": reply["output_tokens"], "cost_usd": reply["cost_usd"],
    }


def make_task(model: str, old_answers: dict[str, dict] | None = None, params: dict | None = None,
              system: str | None = None):
    """The function Opik calls once per dataset item. `system`, when given, replaces each item's own."""

    def run_case(item: dict) -> dict:
        prompt = system if system is not None else (item.get("system") or "")
        turns = item.get("messages") or [{"role": "user", "content": item["input"]}]
        messages = ([{"role": "system", "content": prompt}] if prompt else []) + turns
        old = (old_answers or {}).get(item.get("id"), {})
        # The old answer rides along so the old-vs-new metrics can read it.
        shared = {"old_output": old.get("output") if old and not old.get("error") else None, "system": prompt}
        try:
            # The same request parameters your app sends today, on both models.
            reply = llm.complete(model, messages, **(params or {}))
        except Exception as error:  # noqa: BLE001 (one failed case shouldn't stop the run)
            return {**shared, "output": "", "error": f"{type(error).__name__}: {str(error)[:300]}", "outcome": "error",
                    "latency_s": None, "input_tokens": None, "output_tokens": None, "cost_usd": None}
        return {**shared, **answer_fields(reply)}

    return run_case


def experiment_name(run_name: str, role: str, model: str) -> str:
    return f"{run_name}-{role}-{model.split('/')[-1]}"


def run_side_opik(dataset, item_ids, model, role, run_name, metrics, threads, judge,
                  old_answers=None, params=None, system=None) -> tuple[dict, dict]:
    """One Opik experiment. Returns (cases by dataset item ID, experiment info)."""
    from opik.evaluation import evaluate

    result = evaluate(
        dataset=dataset,
        task=make_task(model, old_answers, params, system),
        scoring_metrics=metrics,
        experiment_name=experiment_name(run_name, role, model),
        experiment_config={"role": role, "model": model, "judge_model": judge, "run": run_name, "params": params or {}},
        dataset_item_ids=item_ids,
        task_threads=threads,
    )
    cases = {
        test.test_case.dataset_item_id: {
            **test.test_case.task_output,
            "item": test.test_case.dataset_item_content,
            "scores": {score.name: score for score in test.score_results},
        }
        for test in result.test_results
    }
    return cases, {"name": result.experiment_name, "id": result.experiment_id, "url": result.experiment_url}


def run_side_local(cases, model, role, run_name, metrics, threads, old_answers=None, params=None,
                   system=None) -> tuple[dict, dict]:
    """The same task and metrics as run_side_opik, on this machine, nothing logged."""
    task = make_task(model, old_answers, params, system)

    def one(case: dict) -> tuple[str, dict]:
        item = {**case, "id": case.get("id") or case["case"]}
        output = task(item)
        scores = {}
        for metric in metrics:
            result = metric.score(**{**item, **output})  # the same merge Opik does: task output wins
            for score in result if isinstance(result, list) else [result]:
                scores[score.name] = score
        return item["id"], {**output, "item": item, "scores": scores}

    with ThreadPoolExecutor(threads) as pool:
        by_id = dict(pool.map(one, cases))
    return by_id, {"name": experiment_name(run_name, role, model), "id": None, "url": None}


def compare_url(experiment_url: str | None, experiment_ids: list[str]) -> str | None:
    """The SDK's experiment link already opens Opik's compare view; select every experiment in it.

    Built from the SDK's URL, so the host and workspace (Cloud or self-hosted) are right.
    """
    if not experiment_url or not all(experiment_ids):
        return None
    parts = urlsplit(experiment_url)
    query = parse_qs(parts.query)
    query["experiments"] = [json.dumps(experiment_ids)]
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True, quote_via=quote)))


# ---- the summary the report and terminal read -----------------------------------


def side_stats(cases: dict[str, dict]) -> dict:
    ran = [c for c in cases.values() if not c.get("error")]
    latencies = [c["latency_s"] for c in ran if c.get("latency_s") is not None]
    costs = [c["cost_usd"] for c in ran if c.get("cost_usd") is not None]
    out_tokens = [c["output_tokens"] for c in ran if c.get("output_tokens") is not None]
    return {
        "answered": len(ran),
        "errors": len(cases) - len(ran),
        "truncated": sum(c.get("outcome") == "truncated" for c in ran),
        "tool_calls": sum(c.get("outcome") == "tool_call" for c in ran),
        "median_latency_s": statistics.median(latencies) if latencies else None,
        "mean_latency_s": statistics.mean(latencies) if latencies else None,
        "total_cost_usd": sum(costs) if costs and len(costs) == len(ran) else None,
        "priced": len(costs),
        "mean_output_tokens": statistics.mean(out_tokens) if out_tokens else None,
        "mean_chars": statistics.mean(len(c["output"]) for c in ran) if ran else None,
    }


def _misses(scores: dict) -> list[dict]:
    """The checks that fired (scored below 1.0), leaving out the judge's own two scores."""
    return [{"check": name, "reason": score.reason} for name, score in scores.items()
            if name not in ("same_meaning", "new_vs_old") and not score.scoring_failed and score.value < 1.0]


def meaning_status(scores: dict) -> str:
    """judged, judge_failed or no_answer (a model call failed, so there was nothing to judge)."""
    meaning = scores.get("same_meaning")
    if meaning is None:
        return "no_answer"
    if not meaning.scoring_failed:
        return "judged"
    return (meaning.metadata or {}).get("status", "no_answer")


def judged_rows(old_cases: dict, other_cases: dict) -> list[dict]:
    """One row per case, paired by dataset item ID (never by label)."""
    rows = []
    for item_id, new in other_cases.items():
        old = old_cases.get(item_id, {})
        scores = new["scores"]
        meaning, preference = scores.get("same_meaning"), scores.get("new_vs_old")
        status = meaning_status(scores)
        judged = status == "judged"
        rows.append({
            "id": item_id,
            "case": new["item"].get("case", item_id),
            "category": new["item"].get("category", ""),
            "request": new["item"]["input"],
            "old": old.get("output", ""),
            "new": new.get("output", ""),
            "old_error": old.get("error"),
            "new_error": new.get("error"),
            "new_outcome": new.get("outcome"),
            "fired": _misses(scores) + ([{"check": "same_meaning", "reason": meaning.reason}]
                                        if judged and meaning.value == 0.0 else []),
            "old_fired": _misses(old.get("scores", {})),
            "scoring": status,
            "meaning_changed": judged and meaning.value == 0.0,
            "meaning_reason": meaning.reason if meaning else None,
            "meaning_kind": (meaning.metadata or {}).get("kind") if judged else None,
            "better": (preference.metadata or {}).get("better") if judged and preference else None,
            "judge_cost_usd": (meaning.metadata or {}).get("judge_cost_usd") if judged else None,
        })
    rows.sort(key=lambda r: (not r["meaning_changed"], -len(r["fired"]), r["case"]))
    return rows


def count(rows: list[dict], key: str) -> dict[str, int]:
    counts = {}
    for row in rows:
        for fired in row[key]:
            counts[fired["check"]] = counts.get(fired["check"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def run_status(rows: list[dict], old_stats: dict, new_stats: dict) -> tuple[str, str]:
    """ok, inconclusive (some cases unjudged because the judge failed) or unusable; and why."""
    judged = sum(r["scoring"] == "judged" for r in rows)
    judge_failed = sum(r["scoring"] == "judge_failed" for r in rows)
    if not old_stats["answered"] or not new_stats["answered"]:
        side = "old" if not old_stats["answered"] else "new"
        total = old_stats["answered"] + old_stats["errors"]
        return "unusable", f"the {side} model answered none of the {total} requests"
    if not judged:
        return "unusable", f"the judge scored none of the {len(rows)} cases ({judge_failed} judge failures)"
    if judge_failed:
        return "inconclusive", f"the judge failed on {judge_failed} of {len(rows)} cases, so changes there are unknown"
    return "ok", ""


def summarize(old_cases: dict, new_cases: dict, *, old_model: str, new_model: str, judge: str, run_name: str,
              params: dict | None = None, experiments: dict | None = None, repeat_cases: dict | None = None,
              compare_link: str | None = None, opik: bool = True) -> dict:
    rows = judged_rows(old_cases, new_cases)
    old_stats, new_stats = side_stats(old_cases), side_stats(new_cases)
    status, why = run_status(rows, old_stats, new_stats)
    prefs = [r["better"] for r in rows if r["better"]]
    judge_costs = [r["judge_cost_usd"] for r in rows if r["judge_cost_usd"] is not None]
    noise = None
    if repeat_cases is not None:
        repeat = judged_rows(old_cases, repeat_cases)
        noise = {"meaning_changed": sum(r["meaning_changed"] for r in repeat),
                 "judged": sum(r["scoring"] == "judged" for r in repeat)}
    lint = params_lint.lint(new_model, params or {})
    return {
        "run": run_name,
        "run_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "old_model": old_model,
        "new_model": new_model,
        "judge_model": judge,
        "status": status,
        "status_reason": why,
        "cases": len(rows),
        "meaning_changed": sum(r["meaning_changed"] for r in rows),
        "judged": sum(r["scoring"] == "judged" for r in rows),
        "judge_failed": sum(r["scoring"] == "judge_failed" for r in rows),
        "unjudged": sum(r["scoring"] != "judged" for r in rows),
        "noise": noise,
        "fired_counts": count(rows, "fired"),
        "old_fired_counts": count(rows, "old_fired"),
        "preference": {k: prefs.count(k) for k in ("new", "same", "old")},
        # A request that ran on the old model and errors on the new one is its own
        # outcome: no quality score ever sees it, and it's the one that pages you.
        "failed_on_new": [{"case": r["case"], "error": r["new_error"]} for r in rows
                          if r["new_error"] and not r["old_error"]],
        "old_stats": old_stats,
        "new_stats": new_stats,
        "judge_cost_usd": sum(judge_costs) if judge_costs else None,
        "params": params or {},
        "params_lint": [issue.__dict__ for issue in lint],
        "params_lint_has_rules": params_lint.has_rules(new_model),
        "opik": opik,
        "experiments": experiments or {},
        "compare_url": compare_link,
        "rows": rows,
    }


# ---- the whole run -------------------------------------------------------------


def run_comparison(cases: list[dict], old: str, new: str, dataset_name: str | None, judge: str, *,
                   settings: config.Settings, params: dict | None = None, system: str | None = None,
                   noise_floor: bool = False, use_opik: bool = True, out_dir: str | Path = "reports") -> tuple[dict, Path]:
    run_name = "migration-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    single = [check() for check in checks.SINGLE_CHECKS]
    paired = single + [check() for check in checks.PAIRWISE_CHECKS] + [MeaningChanged(model=judge)]
    roles = [("old", old, single), ("new", new, paired)] + ([("repeat", old, paired)] if noise_floor else [])
    results, experiments = {}, {}
    if use_opik:
        import opik

        dataset, item_ids = capture.to_dataset(cases, dataset_name, settings.project)
    try:
        for role, model, metrics in roles:
            print(f"\n{role} side: {model} on {len(cases)} requests", flush=True)
            old_answers = results.get("old")
            if use_opik:
                results[role], experiments[role] = run_side_opik(
                    dataset, item_ids, model, role, run_name, metrics, settings.threads, judge, old_answers, params, system)
            else:
                results[role], experiments[role] = run_side_local(
                    cases, model, role, run_name, metrics, settings.threads, old_answers, params, system)
            if role == "old" and not side_stats(results["old"])["answered"]:
                break  # nothing to compare against; the summary says so
    finally:
        if use_opik:
            opik.flush_tracker()  # send buffered traces before the script exits
    results.setdefault("new", {})
    shown = [experiments[r]["id"] for r in ("old", "new") if r in experiments]
    link = compare_url(experiments.get("old", {}).get("url"), shown) if len(shown) == 2 else None
    summary = summarize(results["old"], results["new"], old_model=old, new_model=new, judge=judge, run_name=run_name,
                        params=params, experiments=experiments, repeat_cases=results.get("repeat"),
                        compare_link=link, opik=use_opik)
    return summary, report.write(summary, Path(out_dir) / run_name)


def headline(summary: dict) -> str:
    """'5 of 30 changed meaning (7 expected from run-to-run noise)', or why the count can't be trusted."""
    if summary["status"] == "unusable":
        return f"No result: {summary['status_reason']}."
    text = f"{summary['meaning_changed']} of {summary['judged']} judged answers changed meaning"
    if summary.get("noise"):
        text += f" ({summary['noise']['meaning_changed']} expected from run-to-run noise)"
    if summary["status"] == "inconclusive":
        text += f". Inconclusive: {summary['status_reason']}"
    return text


def print_summary(summary: dict, path: Path) -> None:
    o, n = summary["old_stats"], summary["new_stats"]
    num = report.num
    print(f"\n{summary['old_model']} -> {summary['new_model']}  ({summary['cases']} cases, judge {summary['judge_model']})")
    print(f"  {headline(summary)}")
    if summary["unjudged"]:
        print(f"  not judged: {summary['unjudged']} ({summary['judge_failed']} judge failures, "
              f"{summary['unjudged'] - summary['judge_failed']} with no answer to judge)")
    for name, hits in summary["fired_counts"].items():
        print(f"  {name:<22} fired on {hits}")
    p = summary["preference"]
    print(f"  judge preferred: new {p['new']}, same {p['same']}, old {p['old']}")
    print(f"  median latency (successful calls): {num(o['median_latency_s'], '{:.2f}s')} -> "
          f"{num(n['median_latency_s'], '{:.2f}s')}")
    print(f"  estimated model cost (LiteLLM prices, without the judge): {num(o['total_cost_usd'], '${:.4f}')} -> "
          f"{num(n['total_cost_usd'], '${:.4f}')}; judge {num(summary['judge_cost_usd'], '${:.4f}')}")
    print(f"  errors: {o['errors']} -> {n['errors']}; failed on new model only: {len(summary['failed_on_new'])}")
    for failure in summary["failed_on_new"][:5]:
        print(f"    - {failure['case']}: {failure['error'][:160]}")
    if summary["params"]:
        print(f"  request params {summary['params']}: " + (
            "; ".join(f"{i['effect']} {i['param']} ({i['why']})" for i in summary["params_lint"]) or
            ("nothing flagged by the migration guide" if summary["params_lint_has_rules"] else "no sourced rules for this model")))
    print(f"  report: {path.resolve()}")
    if summary["compare_url"]:
        print(f"\nCompare both experiments in Opik:\n  {summary['compare_url']}")
    elif not summary["opik"]:
        link = config.links("cli")
        print(f"\nTo see these answers side by side in Opik, run again without --no-opik: free Opik Cloud account "
              f"at {link['signup']} or self-host ({link['self_host']}).")


# ---- command line --------------------------------------------------------------


def positive_int(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"must be a whole number, 1 or more (got {text!r})")
    return int(text)


def read_params(parser: argparse.ArgumentParser, inline: str | None, path: str | None) -> dict:
    """--params '<json>' or --params-file <file> (easier on Windows shells). Must be a JSON object."""
    if inline and path:
        parser.error("use --params or --params-file, not both")
    try:
        text = Path(path).read_text(encoding="utf-8") if path else (inline or "{}")
        params = json.loads(text)
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"--params{'-file' if path else ''}: {error}")
    if not isinstance(params, dict):
        parser.error('--params must be a JSON object, e.g. {"temperature": 0.2}')
    if reserved := [key for key in RESERVED_PARAMS if key in params]:
        parser.error(f"--params can't set {', '.join(reserved)}: the kit sends those itself")
    return params


def load_cases(cases_path: str | None, dataset_name: str | None, project: str, system: str | None = None) -> list[dict]:
    """Cases from a file, or else from an existing Opik dataset. Exits with a clear message otherwise."""
    if cases_path:
        return capture.load_file(cases_path, system)
    if not dataset_name:
        sys.exit("Give --cases <file>, or --dataset <name> to read an existing Opik dataset "
                 "(for example one written by: python -m kit.capture --from-opik-project <project> --dataset <name>).")
    try:
        cases = capture.from_opik_dataset(dataset_name, project, system)
    except ValueError as error:
        sys.exit(str(error))
    if not cases:
        sys.exit(f"Opik dataset '{dataset_name}' has no usable items (each needs an 'input').")
    return cases


def build_parser(settings: config.Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", help=".jsonl or .csv of requests (or use --dataset alone)")
    parser.add_argument("--system", help="file with the system prompt; replaces each case's own")
    parser.add_argument("--old", required=True, help="LiteLLM name of the model you run today")
    parser.add_argument("--new", required=True, help="LiteLLM name of the replacement")
    parser.add_argument("--judge", default=settings.judge,
                        help="LiteLLM name of the judge (default: JUDGE_MODEL, else one you have a key for)")
    parser.add_argument("--dataset", help="Opik dataset: with --cases it's written to, without it it's read "
                        "(e.g. one kit.capture --from-opik-project made). Default with --cases: model-migration-cases")
    parser.add_argument("--limit", type=positive_int, help="only the first N cases")
    parser.add_argument("--params", help='JSON of the request parameters your app sends, e.g. \'{"temperature": 0.2}\'')
    parser.add_argument("--params-file", help="the same JSON, read from a file (easier in PowerShell)")
    parser.add_argument("--noise-floor", action="store_true",
                        help="also run the old model against itself, to show how much answers move on their own")
    parser.add_argument("--no-opik", action="store_true",
                        help="report only: nothing is sent to Opik (the model calls still go to the providers)")
    parser.add_argument("--fail-on-changed", type=int, metavar="N", help="exit 3 if more than N answers changed meaning")
    parser.add_argument("--deadline-minutes", type=positive_int, default=30,
                        help="stop retrying rate-limited calls after this long (default 30)")
    return parser


def main(argv=None) -> None:
    settings = config.load()
    parser = build_parser(settings)
    args = parser.parse_args(argv)
    params = read_params(parser, args.params, args.params_file)
    if args.no_opik and args.dataset and not args.cases:
        parser.error("--no-opik needs --cases: reading a dataset needs Opik")
    try:
        system = Path(args.system).read_text(encoding="utf-8") if args.system else None
        cases = capture.load_file(args.cases, system) if args.cases else None
    except (OSError, ValueError) as error:
        parser.error(str(error))
    judge, warning = config.pick_judge(args.old, args.new, args.judge)
    if warning:
        print(f"Note: {warning}")
    for issue in params_lint.lint(args.new, params):
        print(f"{issue.effect.upper()} on {args.new}: {issue.param}: {issue.why} ({issue.source})")

    # Everything local is valid. Now the checks that talk to the network, then the run.
    if args.no_opik:
        import opik

        opik.set_tracing_active(False)
    else:
        preflight.opik_ready()
    preflight.models_ready(args.old, args.new, judge)
    cases = cases or load_cases(None, args.dataset, settings.project, system)
    cases = cases[: args.limit]
    llm.set_deadline(args.deadline_minutes)
    summary, path = run_comparison(cases, args.old, args.new, args.dataset or "model-migration-cases", judge,
                                   settings=settings, params=params, system=system, noise_floor=args.noise_floor,
                                   use_opik=not args.no_opik)
    print_summary(summary, path)
    if summary["status"] == "unusable":
        sys.exit(EXIT_UNUSABLE)
    if args.fail_on_changed is not None and summary["meaning_changed"] > args.fail_on_changed:
        sys.exit(EXIT_TOO_MANY_CHANGED)


if __name__ == "__main__":
    main()
