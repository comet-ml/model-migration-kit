"""Turn what you find in traces into tests that run on every model you try.

    uv run python -m kit.suite --checks examples/support-bot/checks.yaml \\
        --cases examples/support-bot/cases.jsonl --system examples/support-bot/system_prompt.md \\
        --models gemini/gemini-2.5-flash gemini/gemini-3.5-flash-lite

The compare report shows what changed. Reading a few of those answers in Opik
usually turns up a pattern worth keeping an eye on, like a refund reply that
drops its condition. Write it as one sentence in a checks file (see
examples/support-bot/checks.yaml). This command:

1. Saves the checks as an Opik test suite: each check is an assertion on the
   cases it names, or on every case if it names none. The suite is versioned in
   Opik, so the checks stay with your requests.
2. Runs the suite on each model in --models, as one Opik experiment per model.
   An LLM judge (--judge) decides whether each answer passes each assertion.
3. Prints which checks pass on each model, and exits 3 if any fail on the last
   model listed (for CI).
"""

import argparse
import sys
from pathlib import Path

import yaml

from kit import capture, compare, config, llm, preflight

EXIT_FAILED = 3
ERROR_PREFIX = "[no answer: the model call failed] "  # an errored case fails every check in this command's count
# Added to every item so Opik's own pass/fail marks a failed model call as failed too.
ANSWERED_CHECK = "The output is a reply to the user, not a message saying the model call failed."


def load_checks(path: str | Path) -> list[dict]:
    """[{check, cases (list or None), found}] from a YAML list. Raises ValueError on a bad file."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    except yaml.YAMLError as error:
        raise ValueError(f"{path}: not valid YAML ({error})") from error
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of checks, each with a 'check' sentence")
    checks = []
    for number, entry in enumerate(raw, 1):
        text = entry.get("check") if isinstance(entry, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{path}: item {number} needs a 'check' sentence")
        cases = entry.get("cases")
        if cases is not None and (not isinstance(cases, list) or not cases or not all(isinstance(c, str) for c in cases)):
            raise ValueError(f"{path}: item {number}: 'cases' must be a non-empty list of case names "
                             "(leave it out to run the check on every case)")
        checks.append({"check": " ".join(text.split()), "cases": cases, "found": entry.get("found")})
    if not checks:
        raise ValueError(f"{path}: no checks")
    return checks


def plan(checks: list[dict], cases: list[dict]) -> tuple[list[str], dict[str, list[str]]]:
    """(checks for every case, {case name: its own checks}). Raises ValueError for a case name not in the file."""
    names = {case["case"] for case in cases}
    everywhere = [c["check"] for c in checks if c["cases"] is None]
    per_case: dict[str, list[str]] = {}
    for check in checks:
        for name in check["cases"] or []:
            if name not in names:
                raise ValueError(f"check {check['check'][:60]!r}... names case {name!r}, which isn't in the cases file")
            per_case.setdefault(name, []).append(check["check"])
    return everywhere, per_case


def suite_items(cases: list[dict], per_case: dict[str, list[str]], everywhere: list[str]) -> list[dict]:
    """The cases the checks cover, as Opik test suite items. With checks for every case, that's all of them."""
    items = []
    for case in cases:
        if not everywhere and case["case"] not in per_case:
            continue
        data = {key: case[key] for key in capture.FIELDS if key in case}
        items.append({"data": data, "assertions": per_case.get(case["case"], []), "description": case["case"]})
    return items


def sync_suite(name: str, items: list[dict], everywhere: list[str], runs: int, project: str):
    """Create or update the suite so it holds exactly these items and checks. Items are matched by case name."""
    import opik

    client = opik.Opik()
    suite = client.get_or_create_test_suite(name, project_name=project,
                                            description="Checks written from traces of a model migration")
    suite.update_test_settings(global_assertions=[*everywhere, ANSWERED_CHECK],
                               global_execution_policy={"runs_per_item": runs, "pass_threshold": runs})
    existing = {item["data"].get("case"): item for item in suite.get_items()}
    wanted = {item["data"]["case"] for item in items}
    updates = [{**item, "id": existing[item["data"]["case"]]["id"]} for item in items if item["data"]["case"] in existing]
    inserts = [item for item in items if item["data"]["case"] not in existing]
    if updates:
        suite.update(updates)
    if inserts:
        suite.insert(inserts)
    # Only items this command wrote (they carry a case name); anything added by hand stays.
    stale = [item["id"] for case, item in existing.items() if case and case not in wanted]
    if stale:
        suite.delete(stale)
    return suite


def judge_input(data: dict, system: str | None) -> str:
    """What the assistant was given, for the judge: its instructions and the whole conversation."""
    prompt = system if system is not None else (data.get("system") or "")
    turns = data.get("messages") or [{"role": "user", "content": data.get("input", "")}]
    text = "\n\n".join(f"{turn['role'].upper()}: {turn['content']}" for turn in turns)
    return f"ASSISTANT INSTRUCTIONS:\n{prompt}\n\n{text}" if prompt else text


def suite_task(model: str, params: dict | None, system: str | None):
    """The function the suite calls per item: the same model call kit.compare makes."""
    run_case = compare.make_task(model, params=params, system=system)

    def task(data: dict) -> dict:
        result = run_case(data)
        output = ERROR_PREFIX + result["error"] if result.get("error") else result["output"]
        return {"input": judge_input(data, system), "output": output}

    return task


def tally(result) -> dict[str, dict]:
    """{check: {"passed", "total", "failures": [(case, reason)], "judge_errors"}} for one model's run.

    A failed model call fails every check. A failed judge call isn't counted either way.
    """
    from opik.api_objects.dataset.test_suite.test_suite_result import is_score_passed

    by_check: dict[str, dict] = {}
    for item in result.item_results.values():
        for run in item.test_results:
            case = (run.test_case.dataset_item_content or {}).get("case", item.dataset_item_id)
            output = str((run.test_case.task_output or {}).get("output") or "")
            errored = output.startswith(ERROR_PREFIX)
            for score in run.score_results:
                row = by_check.setdefault(score.name, {"passed": 0, "total": 0, "failures": [], "judge_errors": 0})
                if score.scoring_failed and not errored:
                    row["judge_errors"] += 1
                    continue
                row["total"] += 1
                if errored:
                    row["failures"].append((case, output))
                elif is_score_passed(score):
                    row["passed"] += 1
                else:
                    row["failures"].append((case, (score.reason or "").strip()))
    return by_check


def print_results(results: dict[str, dict], checks: list[dict]) -> None:
    models = list(results)
    print("\nChecks, passed / runs on each model:")
    for check in checks:
        text = check["check"]
        counts = []
        for model in models:
            row = results[model].get(text)
            note = f" ({row['judge_errors']} not judged)" if row and row["judge_errors"] else ""
            counts.append(f"{model.split('/')[-1]} {row['passed']}/{row['total']}{note}" if row else f"{model} n/a")
        print(f"\n  {text}\n    " + " · ".join(counts))
        for model in models:
            for case, reason in (results[model].get(text) or {}).get("failures", [])[:3]:
                print(f"    failed on {model.split('/')[-1]}, {case}: {reason[:200]}")


def main(argv=None) -> None:
    settings = config.load()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checks", required=True, help="YAML file of checks (see examples/support-bot/checks.yaml)")
    parser.add_argument("--cases", required=True, help=".jsonl or .csv of requests, the same file kit.compare reads")
    parser.add_argument("--system", help="file with the system prompt; replaces each case's own")
    parser.add_argument("--models", nargs="+", required=True, help="LiteLLM names to test, old model first")
    parser.add_argument("--suite", default="model-migration-checks", help="Opik test suite name")
    parser.add_argument("--judge", default=settings.judge, help="LiteLLM name of the model that checks the assertions")
    parser.add_argument("--runs", type=compare.positive_int, default=1,
                        help="answers per case per model; a case passes only if every run passes (default 1)")
    parser.add_argument("--params", help='JSON of the request parameters your app sends, e.g. \'{"max_tokens": 1024}\'')
    parser.add_argument("--params-file", help="the same JSON, read from a file")
    parser.add_argument("--project", default=settings.project, help=f"Opik project for the suite ({settings.project})")
    args = parser.parse_args(argv)
    params = compare.read_params(parser, args.params, args.params_file)
    try:
        system = Path(args.system).read_text(encoding="utf-8") if args.system else None
        cases = capture.load_file(args.cases, system)
        checks = load_checks(args.checks)
        everywhere, per_case = plan(checks, cases)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    items = suite_items(cases, per_case, everywhere)
    judge, warning = config.pick_judge(args.models[0], args.models[-1], args.judge)
    if warning:
        print(f"Note: {warning}")

    import opik

    preflight.opik_ready()
    preflight.models_ready(*args.models, judge=judge)
    llm.set_deadline(30)
    suite = sync_suite(args.suite, items, everywhere, args.runs, args.project)
    print(f"Opik test suite '{args.suite}': {len(checks)} checks on {len(items)} cases, judge {judge}")
    results, experiments = {}, []
    try:
        for model in args.models:
            print(f"\n{model}", flush=True)
            result = opik.run_tests(test_suite=suite, task=suite_task(model, params, system), model=judge,
                                    experiment_name_prefix=f"{args.suite}-{model.split('/')[-1]}",
                                    experiment_config={"model": model, "judge_model": judge,
                                                       "params": compare.redact(params)},
                                    experiment_tags=["model-migration-kit", "suite", model.split("/")[-1]],
                                    scoring_tool_strategy="never",  # one judge call per assertion
                                    worker_threads=settings.threads, verbose=1, generate_report=False)
            results[model] = tally(result)
            experiments.append((result.experiment_id, result.experiment_url))
            print(f"  {result.items_passed} of {result.items_total} cases passed · {result.experiment_url}")
    finally:
        compare.flush_opik()
    print_results(results, checks)
    link = compare.compare_url(experiments[0][1], [eid for eid, _ in experiments]) if len(experiments) > 1 else None
    if link:
        print(f"\nCompare the models' answers and assertion results in Opik:\n  {link}")
    last = results[args.models[-1]]
    if any(row["passed"] < row["total"] for row in last.values()):
        sys.exit(EXIT_FAILED)


if __name__ == "__main__":
    main()
