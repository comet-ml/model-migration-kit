"""Load real requests into an Opik dataset: from a CSV or JSONL file, or from an
Opik project's recent traces.

    uv run python -m kit.capture --cases my_requests.jsonl --dataset my-app-migration
    uv run python -m kit.capture --from-opik-project my-app --last 100 --dataset my-app-migration

Each case is a dict:
  input            the user's message (required)
  system           the system prompt (optional; --system sets it for every case)
  case             a short ID (optional; made from the row number if missing)
  expects_json     true if the app needs JSON back (optional)
  required_fields  JSON fields the app reads (optional; a list, or "a,b" in a CSV)
"""

import argparse
import csv
import json
from pathlib import Path

import opik
from dotenv import load_dotenv

FIELDS = ("case", "input", "system", "expects_json", "required_fields", "category")


def normalize(row: dict, index: int, system: str | None = None) -> dict:
    if not str(row.get("input") or "").strip():
        raise ValueError(f"row {index + 1}: no 'input'")
    fields = row.get("required_fields") or []
    if isinstance(fields, str):
        fields = [field.strip() for field in fields.split(",") if field.strip()]
    expects = row.get("expects_json", False)
    if isinstance(expects, str):
        expects = expects.strip().lower() in ("1", "true", "yes", "y")
    return {
        "case": str(row.get("case") or f"case-{index + 1:03d}"),
        "category": str(row.get("category") or ""),
        "input": str(row["input"]),
        "system": str(row.get("system") or system or ""),
        "expects_json": bool(expects or fields),
        "required_fields": list(fields),
    }


def load_file(path: str | Path, system: str | None = None) -> list[dict]:
    """Read cases from .jsonl or .csv."""
    path = Path(path)
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    elif path.suffix == ".csv":
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        raise ValueError(f"{path}: use a .jsonl or .csv file")
    cases = [normalize(row, index, system) for index, row in enumerate(rows)]
    ids = [case["case"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: case IDs must be unique")
    return cases


def messages_from_trace_input(trace_input: object) -> tuple[str, str] | None:
    """Pull (system, user message) out of a trace's input.

    Handles the shapes Opik's integrations log: {"messages": [...]} from
    OpenAI / LiteLLM / Anthropic calls, and a plain {"input"|"query"|"question"|
    "prompt"|"message": "..."} or string from @opik.track functions. Returns None
    for anything else, so it's skipped rather than guessed.
    """
    if isinstance(trace_input, str):
        return "", trace_input
    if not isinstance(trace_input, dict):
        return None
    messages = trace_input.get("messages")
    if isinstance(messages, list):
        system = "\n".join(_text(m.get("content")) for m in messages if isinstance(m, dict) and m.get("role") == "system")
        users = [_text(m.get("content")) for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        if users and users[-1].strip():
            return system or str(trace_input.get("system") or ""), users[-1]
        return None
    for key in ("input", "query", "question", "prompt", "message", "user_message"):
        if isinstance(trace_input.get(key), str) and trace_input[key].strip():
            return str(trace_input.get("system") or ""), trace_input[key]
    return None


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content parts: [{"type": "text", "text": "..."}]
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def from_opik_project(project_name: str, last: int = 100) -> list[dict]:
    """The last `last` traces of an Opik project, as cases (one per usable trace)."""
    client = opik.Opik()
    traces = client.search_traces(project_name=project_name, max_results=last, truncate=False)
    cases = []
    for trace in traces:
        found = messages_from_trace_input(trace.input)
        if found:
            system, user = found
            cases.append(normalize({"case": f"trace-{trace.id[-8:]}", "input": user, "system": system}, len(cases)))
    return cases


def from_opik_dataset(dataset_name: str, project_name: str | None = None, system: str | None = None) -> list[dict]:
    """Read the cases back from an existing Opik dataset (the shape to_dataset writes).

    Returns [] when the dataset is empty or has no usable items.
    """
    client = opik.Opik()
    try:
        dataset = client.get_dataset(dataset_name, project_name=project_name)
    except Exception as error:  # noqa: BLE001 (the SDK raises its own not-found error)
        raise SystemExit(f"Opik dataset '{dataset_name}' not found: {error}") from error
    items = [item for item in dataset.get_items() if str(item.get("input") or "").strip()]
    return [normalize({key: item.get(key) for key in FIELDS}, index, system) for index, item in enumerate(items)]


def to_dataset(cases: list[dict], dataset_name: str, project_name: str | None = None) -> tuple[opik.Dataset, list[str]]:
    """Insert cases into an Opik dataset; return it and the item IDs for exactly these cases.

    Opik dedupes on content, so re-running is safe. An edited case is a new
    item and the old one stays, which is why the run is limited to these IDs.
    """
    client = opik.Opik()
    # The dataset's project is where evaluate() logs the experiments and traces.
    dataset = client.get_or_create_dataset(
        dataset_name, description="Requests for a model migration test", project_name=project_name
    )
    dataset.insert(cases)
    wanted = {json.dumps(case, sort_keys=True) for case in cases}
    ids = [
        item["id"]
        for item in dataset.get_items()
        if json.dumps({key: item.get(key) for key in FIELDS}, sort_keys=True) in wanted
    ]
    return dataset, ids


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases", help="a .jsonl or .csv file of requests")
    source.add_argument("--from-opik-project", help="read the project's last N traces")
    parser.add_argument("--last", type=int, default=100, help="how many traces to read (default 100)")
    parser.add_argument("--system", help="a file holding the system prompt for every case")
    parser.add_argument("--dataset", required=True, help="Opik dataset to write to")
    parser.add_argument("--project", default="model-migration-kit", help="Opik project for the dataset")
    args = parser.parse_args()
    system = Path(args.system).read_text() if args.system else None
    cases = load_file(args.cases, system) if args.cases else from_opik_project(args.from_opik_project, args.last)
    _, ids = to_dataset(cases, args.dataset, args.project)
    print(f"{len(cases)} cases in dataset '{args.dataset}' ({len(ids)} matched back)")
