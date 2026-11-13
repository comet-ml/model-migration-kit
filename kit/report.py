"""One static HTML page: the counts first, then every case where something changed."""

import html
import json
from pathlib import Path

CSS = """
:root{--bg:#fff;--fg:#1d2430;--muted:#5b6575;--line:#e3e6eb;--hot:#b42318;--hotbg:#fef3f2;--ok:#067647}
@media (prefers-color-scheme:dark){:root{--bg:#14181f;--fg:#e6e9ee;--muted:#9aa3b2;--line:#2a313c;--hot:#f97066;--hotbg:#2a1715;--ok:#47cd89}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,sans-serif;margin:0 auto;max-width:1200px;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}.muted{color:var(--muted)}
.tiles{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.tile{border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:150px}
.tile b{display:block;font-size:24px}.hot b{color:var(--hot)}
table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{border-top:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}
td pre{white-space:pre-wrap;word-break:break-word;margin:0;font:12.5px/1.45 ui-monospace,Menlo,monospace;max-height:260px;overflow:auto}
tr.changed td:first-child{border-left:3px solid var(--hot)}.tag{display:inline-block;background:var(--hotbg);color:var(--hot);border-radius:4px;padding:0 6px;margin:0 4px 4px 0;font-size:12px}
a{color:inherit}.wrap{overflow-x:auto}
.cta{border:2px solid var(--fg);border-radius:8px;padding:12px 16px;font-size:16px}.lead{font-size:18px;margin:12px 0 0}
.warn{background:var(--hotbg);color:var(--hot);border-radius:6px;padding:8px 12px}footer{margin-top:32px;font-size:13px}
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def num(value, fmt: str) -> str:
    return "n/a" if value is None else fmt.format(value)


def opik_box(summary: dict, link: dict) -> str:
    """The first link on the page: both experiments side by side in Opik, or how to get there."""
    if summary.get("compare_url"):
        return (f'<p class="cta"><a href="{_e(summary["compare_url"])}"><b>Compare both experiments in Opik</b></a>'
                ' <span class="muted">every answer side by side, with each check\'s score and the judge\'s reason</span></p>')
    if not summary.get("opik", True):
        return (f'<p class="cta">This run stayed on your machine (--no-opik). Run it again without --no-opik to open both '
                f'answers side by side in Opik: <a href="{_e(link["signup"])}">free Opik Cloud account</a> or '
                f'<a href="{_e(link["self_host"])}">self-host Opik</a>.</p>')
    return ""


def tiles(summary: dict) -> list[tuple[str, str, str]]:
    o, n = summary["old_stats"], summary["new_stats"]
    noise = summary.get("noise")
    changed_note = (f"answers changed meaning ({noise['meaning_changed']} of {noise['judged']} expected from run-to-run "
                    "noise)" if noise else "answers changed meaning. Not compared with run-to-run noise: "
                    "add --noise-floor")
    unjudged = summary.get("unjudged", 0)
    return [
        ("hot", f"{summary['meaning_changed']} of {summary['judged']}", changed_note),
        ("hot" if summary.get("judge_failed") else "", f"{unjudged}",
         f"not judged ({summary.get('judge_failed', 0)} judge failures)"),
        ("", f"{sum(1 for r in summary['rows'] if r['fired'])} of {summary['cases']}", "cases where any check fired on the new model"),
        ("", f"new {summary['preference']['new']} · same {summary['preference']['same']} · old {summary['preference']['old']}",
         "judge: which answer is better"),
        ("", f"{num(o['median_latency_s'], '{:.2f}s')} → {num(n['median_latency_s'], '{:.2f}s')}",
         "median latency of successful calls (retry waits not counted)"),
        ("", f"{num(o['total_cost_usd'], '${:.4f}')} → {num(n['total_cost_usd'], '${:.4f}')}",
         f"estimated model-call cost (LiteLLM prices), excluding the judge "
         f"({num(summary.get('judge_cost_usd'), '${:.4f}')})"),
        ("hot" if summary.get("failed_on_new") else "", f"{len(summary.get('failed_on_new', []))}",
         "requests that ran on the old model and failed on the new one"),
        ("", f"{o['errors']} → {n['errors']}", "calls that failed after retries"),
    ]


def footer(link: dict) -> str:
    from kit.config import NEW_ISSUE, REPO

    return (
        '<footer class="muted"><p>Opik is an open-source LLM observability and agent evaluation platform built by Comet. '
        f'This report came from the <a href="{REPO}">model migration kit</a>.</p>'
        f'<p><a href="{_e(link["rules"])}">Keep these checks running after you switch</a> (Opik online evaluation rules; '
        f'<code>python -m kit.rules</code> sets one up) · <a href="{NEW_ISSUE}">Report a wrong date</a></p></footer>'
    )


def render(summary: dict) -> str:
    from kit.compare import headline
    from kit.config import links

    link = links("report")
    old_name, new_name = summary["old_model"], summary["new_model"]
    tile_html = "".join(f'<div class="tile {cls}"><b>{_e(big)}</b><span class="muted">{_e(small)}</span></div>'
                        for cls, big, small in tiles(summary))
    fired = "".join(f"<li><b>{_e(name)}</b>: {count}</li>" for name, count in summary["fired_counts"].items()) or "<li>none</li>"
    old_fired = "".join(f"<li><b>{_e(name)}</b>: {count}</li>" for name, count in summary.get("old_fired_counts", {}).items())
    links_html = "".join(
        f'<li>{_e(role)}: <a href="{_e(exp["url"])}">{_e(exp["name"])}</a></li>'
        for role, exp in summary["experiments"].items() if exp.get("url")
    )
    lint_items = "".join(
        f'<li><b>{_e(i["effect"])}</b> {_e(i["param"])}: {_e(i["why"])} (<a href="{_e(i["source"])}">source</a>)</li>'
        for i in summary.get("params_lint", [])
    )
    if not lint_items:
        lint_items = ("<li>Nothing flagged by the migration guide.</li>" if summary.get("params_lint_has_rules")
                      else "<li>No sourced rules for this model yet; failures are recorded per case below.</li>")
    params_html = (f"<h2>Request parameters sent to both models</h2><p><code>{_e(json.dumps(summary.get('params', {})))}</code></p>"
                   f"<ul>{lint_items}</ul>")
    changed = [r for r in summary["rows"] if r["meaning_changed"] or r["fired"] or r.get("old_fired")
               or r["old_error"] or r["new_error"] or r.get("scoring") == "judge_failed"]
    body_rows = []
    for row in changed:
        tags = "".join(f'<span class="tag" title="{_e(f["reason"])}">{_e(f["check"])}</span>' for f in row["fired"]
                       if f["check"] != "same_meaning")  # shown as the "meaning: <kind>" tag
        tags += "".join(f'<span class="tag" title="{_e(f["reason"])}">old {_e(f["check"])}</span>'
                        for f in row.get("old_fired", []))
        if row["meaning_changed"]:
            tags = f'<span class="tag">meaning: {_e(row["meaning_kind"])}</span>' + tags
        if row.get("scoring") == "judge_failed":
            tags = '<span class="tag">judge failed</span>' + tags
        details = "<br>".join(_e(f"{f['check']}: {f['reason']}") for f in row["fired"])
        errors = "".join(f"<br><b>{side} error:</b> {_e(row[side + '_error'])}" for side in ("old", "new") if row[side + "_error"])
        body_rows.append(
            f'<tr class="{"changed" if row["meaning_changed"] else ""}"><td><b>{_e(row["case"])}</b><br>'
            f'<span class="muted">{_e(row["category"])}</span></td><td><pre>{_e(row["request"])}</pre></td>'
            f'<td><pre>{_e(row["old"])}</pre></td><td><pre>{_e(row["new"])}</pre></td>'
            f'<td>{tags}<br><span class="muted">{details}</span>{errors}</td>'
            f'<td>{_e(row["meaning_reason"])}<br><span class="muted">better: {_e(row["better"])}</span></td></tr>'
        )
    if body_rows:
        table = (
            '<div class="wrap"><table><thead><tr><th>Case</th><th>Request</th>'
            f"<th>Old ({_e(old_name)})</th><th>New ({_e(new_name)})</th><th>Checks fired</th><th>Judge</th></tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table></div>"
        )
    elif summary.get("status", "ok") == "ok":
        table = "<p>Nothing changed on any check.</p>"
    else:
        table = f"<p>No result to show: {_e(summary.get('status_reason'))}.</p>"
    status = summary.get("status", "ok")
    banner = (f'<p class="warn"><b>{_e(status.capitalize())}:</b> {_e(summary.get("status_reason"))}.</p>'
              if status != "ok" else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Migration report</title><style>{CSS}</style></head>
<body><h1>{_e(old_name)} → {_e(new_name)}</h1>
<p class="muted">{summary['cases']} requests · one answer per model per request · run {_e(summary['run_at'])} ·
judge {_e(summary['judge_model'])} · run {_e(summary['run'])}</p>
{opik_box(summary, link)}
<p class="lead">{_e(headline(summary))}</p>
{banner}
<div class="tiles">{tile_html}</div>
<h2>Checks that fired on the new model</h2><ul>{fired}</ul>
{f"<h2>Checks that already fired on the old model</h2><ul>{old_fired}</ul>" if old_fired else ""}
{params_html}
{f"<h2>Each experiment in Opik</h2><ul>{links_html}</ul>" if links_html else ""}
<h2>Every case where something changed ({len(changed)})</h2>
<p class="muted">Changed meaning first. Hover a check for its reason.</p>
{table}
{footer(link)}
</body></html>"""


def write(summary: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    path = out_dir / "report.html"
    path.write_text(render(summary), encoding="utf-8")
    return path
