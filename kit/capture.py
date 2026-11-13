"""Load real requests into an Opik dataset: from a CSV or JSONL file, or from an
Opik project's recent traces.

    uv run python -m kit.capture --cases my_requests.jsonl --dataset my-app-migration
    uv run python -m kit.capture --from-opik-project my-app --last 100 --dataset my-app-migration

Each case is a dict:
  input            the user's last message (required, unless messages is given)
  messages         the whole conversation, OpenAI style: [{"role": "user", "content": "..."}, ...]
                   (optional; replayed as is, so earlier turns count)
  system           the system prompt (optional; --system replaces it on every case)
  case             a short, unique ID (optional; made from the row number if missing)
  expects_json     true if the app needs JSON back (optional)
  required_fields  JSON fields the app reads (optional; a list, or "a,b" in a CSV)

Text only: a conversation with tool calls, tool results or images is skipped
and counted, not half-replayed.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

FIELDS = ("case", "input", "messages", "system", "expects_json", "required_fields", "category")
ROLES = ("user", "assistant")


class Skip(ValueError):
    """A row or trace the kit can't replay faithfully; the message says why."""


def _text(content: object) -> str:
    """Message content as text. Raises Skip for anything that isn't text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content parts: [{"type": "text", "text": "..."}]
        if any(not isinstance(part, dict) or part.get("type", "text") != "text" for part in content):
            raise Skip("non-text content (images, audio or files)")
        return "\n".join(str(part.get("text", "")) for part in content)
    raise Skip("message content that isn't text")


def split_messages(messages: list) -> tuple[str, list[dict]]:
    """(system text, the user/assistant turns as text). Raises Skip for tool use or other content."""
    system, turns = [], []
    for message in messages:
        if not isinstance(message, dict):
            raise Skip("a message that isn't an object")
        role = message.get("role")
        if message.get("tool_calls") or message.get("function_call") or role in ("tool", "function"):
            raise Skip("tool calls")
        if role in ("system", "developer"):
            system.append(_text(message.get("content")))
        elif role in ROLES:
            turns.append({"role": role, "content": _text(message.get("content"))})
        else:
            raise Skip(f"a message with role {role!r}")
    if not turns or turns[-1]["role"] != "user" or not turns[-1]["content"].strip():
        raise Skip("no final user message")
    return "\n".join(system), turns


def _as_text(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def normalize(row: dict, index: int, system: str | None = None, input_column: str = "input") -> dict:
    """One case in the kit's shape. `system`, when given, replaces the row's own system prompt."""
    turns = []
    row_system = row.get("system")
    if isinstance(row.get("messages"), list) and row["messages"]:
        found_system, turns = split_messages(row["messages"])
        row_system = row_system or found_system
        text = turns[-1]["content"]
    else:
        text = _as_text(row.get(input_column))
    if not text.strip():
        raise Skip(f"row {index + 1}: no '{input_column}' (or 'messages')")
    fields = row.get("required_fields") or []
    if isinstance(fields, str):
        fields = [field.strip() for field in fields.split(",") if field.strip()]
    expects = row.get("expects_json", False)
    if isinstance(expects, str):
        expects = expects.strip().lower() in ("1", "true", "yes", "y")
    case = {
        "case": str(row.get("case") or f"case-{index + 1:03d}"),
        "category": str(row.get("category") or ""),
        "input": text,
        # Only a real conversation is stored; a single user turn is just `input`.
        "messages": turns if len(turns) > 1 else [],
        "system": system if system is not None else _as_text(row_system),
        "expects_json": bool(expects or fields),
        "required_fields": list(fields),
    }
    if row.get("id"):
        case["id"] = str(row["id"])  # an existing Opik dataset item: keep its ID
    return case


def check_unique(cases: list[dict], where: str) -> list[dict]:
    dupes = [case for case, count in Counter(c["case"] for c in cases).items() if count > 1]
    if dupes:
        raise ValueError(f"{where}: case IDs must be unique; repeated: {', '.join(dupes[:5])}")
    return cases


def load_file(path: str | Path, system: str | None = None, input_column: str = "input") -> list[dict]:
    """Read cases from .jsonl or .csv. Every row must load; a bad row stops with its row number."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"{path}: no such file")
    if path.suffix == ".jsonl":
        rows = []
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path} line {number}: not JSON ({error.msg})") from error
    elif path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    else:
        raise ValueError(f"{path}: use a .jsonl or .csv file")
    if not rows:
        raise ValueError(f"{path}: no rows")
    cases = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path} row {index + 1}: each line must be a JSON object")
        try:
            cases.append(normalize(row, index, system, input_column))
        except Skip as error:
            raise ValueError(f"{path} row {index + 1}: {error}") from error
    return check_unique(cases, str(path))


def case_from_trace_input(trace_input: object, index: int, case_id: str, system: str | None = None) -> dict:
    """A case from a trace's input. Raises Skip (with the reason) for shapes the kit can't replay.

    Handles the shapes Opik's integrations log: {"messages": [...]} from
    OpenAI / LiteLLM / Anthropic calls, and a plain {"input"|"query"|"question"|
    "prompt"|"message"|"user_message": "..."} or string from @opik.track functions.
    """
    if isinstance(trace_input, str):
        return normalize({"case": case_id, "input": trace_input}, index, system)
    if not isinstance(trace_input, dict):
        raise Skip("input isn't text or an object")
    if isinstance(trace_input.get("messages"), list):
        return normalize({"case": case_id, "messages": trace_input["messages"],
                          "system": trace_input.get("system")}, index, system)
    for key in ("input", "query", "question", "prompt", "message", "user_message"):
        if isinstance(trace_input.get(key), str) and trace_input[key].strip():
            return normalize({"case": case_id, "input": trace_input[key], "system": trace_input.get("system")},
                             index, system)
    raise Skip("no messages or input field")


def from_opik_project(project_name: str, last: int = 100, system: str | None = None) -> tuple[list[dict], Counter]:
    """The last `last` traces of an Opik project as cases, plus why the rest were skipped."""
    import opik

    traces = opik.Opik().search_traces(project_name=project_name, max_results=last, truncate=False)
    cases, skipped = [], Counter()
    for trace in traces:
        try:
            cases.append(case_from_trace_input(trace.input, len(cases), f"trace-{trace.id[-8:]}", system))
        except Skip as error:
            skipped[str(error).split(": ", 1)[-1]] += 1
    return cases, skipped


def from_opik_dataset(dataset_name: str, project_name: str | None = None, system: str | None = None) -> list[dict]:
    """Read the cases back from an existing Opik dataset, keeping each item's ID.

    Returns [] when the dataset is empty or has no usable items.
    """
    import opik

    try:
        dataset = opik.Opik().get_dataset(dataset_name, project_name=project_name)
    except Exception as error:  # noqa: BLE001 (the SDK raises its own not-found error)
        raise SystemExit(f"Opik dataset '{dataset_name}' not found: {error}") from error
    cases = []
    for item in dataset.get_items():
        try:
            cases.append(normalize({key: item.get(key) for key in (*FIELDS, "id")}, len(cases), system))
        except Skip:
            continue
    return check_unique(cases, f"Opik dataset '{dataset_name}'")


def _key(case: dict) -> str:
    return json.dumps({key: case.get(key) for key in FIELDS}, sort_keys=True)


def to_dataset(cases: list[dict], dataset_name: str, project_name: str | None = None):
    """Return (dataset, item IDs for exactly these cases, in order).

    Cases read from a dataset keep their item IDs and nothing is written back.
    Otherwise they're inserted; Opik dedupes on content, so re-running is safe.
    An edited case is a new item and the old one stays, which is why the run is
    limited to these IDs.
    """
    import opik

    client = opik.Opik()
    if cases and all(case.get("id") for case in cases):
        return client.get_dataset(dataset_name, project_name=project_name), [case["id"] for case in cases]
    # The dataset's project is where evaluate() logs the experiments and traces.
    dataset = client.get_or_create_dataset(
        dataset_name, description="Requests for a model migration test", project_name=project_name
    )
    dataset.insert([{key: case[key] for key in FIELDS} for case in cases])
    by_content = {}
    for item in dataset.get_items():
        try:
            by_content[_key(normalize(item, 0))] = item["id"]
        except Skip:
            continue
    missing = [case["case"] for case in cases if _key(case) not in by_content]
    if missing:
        raise SystemExit(f"Opik dataset '{dataset_name}': couldn't find these cases after inserting: {missing[:5]}")
    return dataset, [by_content[_key(case)] for case in cases]


def main(argv=None) -> None:
    from kit import config, preflight

    settings = config.load()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases", help="a .jsonl or .csv file of requests")
    source.add_argument("--from-opik-project", help="read the project's last N traces")
    parser.add_argument("--last", type=int, default=100, help="how many traces to read (default 100)")
    parser.add_argument("--input-column", default="input", help="the column (or JSONL key) holding the request")
    parser.add_argument("--system", help="a file holding the system prompt; replaces it on every case")
    parser.add_argument("--dataset", required=True, help="Opik dataset to write to")
    parser.add_argument("--project", default=settings.project, help=f"Opik project for the dataset ({settings.project})")
    args = parser.parse_args(argv)
    if args.last < 1:
        parser.error("--last must be 1 or more")
    system = Path(args.system).read_text(encoding="utf-8") if args.system else None
    if args.cases:
        try:
            cases = load_file(args.cases, system, args.input_column)
        except ValueError as error:
            parser.error(str(error))
        preflight.opik_ready()
    else:
        preflight.opik_ready()
        cases, skipped = from_opik_project(args.from_opik_project, args.last, system)
        total = len(cases) + sum(skipped.values())
        why = ", ".join(f"{count} {reason}" for reason, count in skipped.most_common())
        print(f"Used {len(cases)} of {total} traces" + (f", skipped {sum(skipped.values())} ({why})" if skipped else ""))
        if not cases:
            sys.exit("No usable traces: the kit replays text conversations only.")
    _, ids = to_dataset(cases, args.dataset, args.project)
    print(f"{len(ids)} cases in dataset '{args.dataset}' (project {args.project})")


if __name__ == "__main__":
    main()
