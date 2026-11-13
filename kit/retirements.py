"""Load kit/retirements.yaml and render it as the tables in README.md and providers/*.md.

    uv run python -m kit.retirements           # print the README table
    uv run python -m kit.retirements --write   # rewrite every table between the retirements markers

A date before the newest checked_on renders as "retired", so the tables stay
true for whoever reads them after the date.
"""

import argparse
import re
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
RETIREMENTS_FILE = Path(__file__).with_name("retirements.yaml")
REQUIRED_KEYS = {"model", "provider", "litellm", "retires", "replacement", "kind", "source", "checked_on"}
KINDS = {"shutoff": "requests fail", "reroute": "requests rerouted to the replacement", "depends": None}
MARKERS = re.compile(r"(<!-- retirements:start -->\n).*?(<!-- retirements:end -->)", re.DOTALL)
# Which rows each page shows. README shows them all.
PAGES = {
    "README.md": None,
    "providers/gemini.md": ("gemini",),
    "providers/openai.md": ("openai", "azure-openai"),
    "providers/anthropic.md": ("anthropic", "bedrock"),
}


def load(path: Path = RETIREMENTS_FILE) -> list[dict]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))
    for row in rows:
        missing = REQUIRED_KEYS - row.keys()
        if missing:
            raise ValueError(f"{row.get('model', '?')}: missing {sorted(missing)}")
        if row["kind"] not in KINDS:
            raise ValueError(f"{row['model']}: kind must be one of {sorted(KINDS)}")
        if row["kind"] == "depends" and not row.get("note"):
            raise ValueError(f"{row['model']}: kind depends needs a note saying how")
        if not isinstance(row["retires"], date):
            raise ValueError(f"{row['model']}: retires must be a YYYY-MM-DD date")
    return sorted(rows, key=lambda row: row["retires"])


def show_date(day: date) -> str:
    return f"{day:%b} {day.day}, {day.year}"  # %-d isn't available on Windows


def markdown_table(rows: list[dict], providers: tuple[str, ...] | None = None) -> str:
    as_of = max((row["checked_on"] for row in rows), default=date.today())
    lines = [
        "| Model | Provider | Date | What happens | Replacement | Source (checked) |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        if providers and row["provider"] not in providers:
            continue
        when = show_date(row["retires"]) + (" (retired)" if row["retires"] < as_of else "")
        happens = KINDS[row["kind"]] or row["note"]
        lines.append(
            f"| `{row['model']}` | {row['provider']} | {when} | {happens} "
            f"| `{row['replacement']}` | [link]({row['source']}) ({row['checked_on']}) |"
        )
    return "\n".join(lines)


def write_pages(rows: list[dict], root: Path = ROOT) -> list[str]:
    """Rewrite the table in every page that has the markers. Returns the pages that changed."""
    changed = []
    for page, providers in PAGES.items():
        path = root / page
        text = path.read_text(encoding="utf-8")
        new = MARKERS.sub(lambda m: m.group(1) + markdown_table(rows, providers) + "\n" + m.group(2), text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(page)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="rewrite the tables in README.md and providers/*.md")
    if parser.parse_args().write:
        print("updated: " + (", ".join(write_pages(load())) or "nothing, already current"))
    else:
        print(markdown_table(load()))
