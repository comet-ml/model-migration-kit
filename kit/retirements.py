"""Load kit/retirements.yaml and render it as the README's Markdown table.

    uv run python -m kit.retirements     # print the table to paste into README.md
"""

from datetime import date
from pathlib import Path

import yaml

RETIREMENTS_FILE = Path(__file__).with_name("retirements.yaml")
REQUIRED_KEYS = {"model", "provider", "litellm", "retires", "replacement", "kind", "source", "checked_on"}


def load(path: Path = RETIREMENTS_FILE) -> list[dict]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))
    for row in rows:
        missing = REQUIRED_KEYS - row.keys()
        if missing:
            raise ValueError(f"{row.get('model', '?')}: missing {sorted(missing)}")
        if row["kind"] not in ("shutoff", "reroute"):
            raise ValueError(f"{row['model']}: kind must be shutoff or reroute")
        if not isinstance(row["retires"], date):
            raise ValueError(f"{row['model']}: retires must be a YYYY-MM-DD date")
    return sorted(rows, key=lambda row: row["retires"])


def show_date(day: date) -> str:
    return f"{day:%b} {day.day}, {day.year}"  # %-d isn't available on Windows


def markdown_table(rows: list[dict]) -> str:
    lines = [
        "| Model | Provider | Date | What happens | Replacement | Source (checked) |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        happens = "requests rerouted to the replacement" if row["kind"] == "reroute" else "requests fail"
        lines.append(
            f"| `{row['model']}` | {row['provider']} | {show_date(row['retires'])} | {happens} "
            f"| `{row['replacement']}` | [link]({row['source']}) ({row['checked_on']}) |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(markdown_table(load()))
