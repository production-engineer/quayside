from html import escape

from pm import verdicts

SECTIONS = [
    ("next", "What to work on next"),
    ("stuck", "What is stuck"),
    ("looks_done", "Looks done but is not closed"),
    ("waiting_on_erik", "Waiting on Erik"),
    ("agent_prs", "Agent and bot PRs awaiting a verdict"),
    ("archive", "Archive candidates"),
]
CHANGE_LABELS = [("new", "New"), ("closed", "Closed"), ("gone", "Gone from the sources"), ("newly_stuck", "Newly stuck"),
                 ("status_flips", "Status flips")]
DEFAULT_TOP = 15


def safe_link(item: dict) -> str | None:
    return next((link for link in item.get("links", []) if link.startswith(("https://", "http://"))), None)


def findings(snapshot: dict, section: str) -> list[dict]:
    return snapshot["findings"].get(section, [])


def entries(snapshot: dict, section: str, top: int) -> list[tuple[dict, dict]]:
    items = {item["id"]: item for item in snapshot["items"]}
    return [(finding, items[finding["id"]]) for finding in findings(snapshot, section)[:top] if finding["id"] in items]


def change_lines(snapshot: dict, top: int) -> tuple[str, list[tuple[str, int, list[str]]]]:
    changes = snapshot.get("changes")
    if not changes:
        return "Run memory was off for this snapshot.", []
    if not changes.get("previous_generated_on"):
        return "First run: nothing to compare yet.", []
    titles = {item["id"]: item["title"] for item in snapshot["items"]}
    titles.update(changes.get("titles", {}))
    groups = []
    for key, label in CHANGE_LABELS:
        values = changes.get(key, [])
        if key == "status_flips":
            lines = [f"{titles.get(flip['id'], flip['id'])}: {flip['from']} to {flip['to']}" for flip in values[:top]]
        else:
            lines = [titles.get(value, value) for value in values[:top]]
        groups.append((label, len(values), lines))
    return f"Compared with the run from {changes['previous_generated_on']} (changes since {changes['previous_generated_on']}).", groups


def verdict_groups(snapshot: dict, top: int) -> list[tuple[str, int, str, list[tuple[dict, dict]]]]:
    grouped = {verdict: [] for verdict in verdicts.ORDER}
    for finding, item in entries(snapshot, "pr_verdicts", len(findings(snapshot, "pr_verdicts"))):
        grouped.setdefault(item.get("verdict"), []).append((finding, item))
    return [(verdicts.LABELS.get(verdict, verdict), len(members), verdicts.ACTIONS.get(verdict, ""), members[:top])
            for verdict, members in grouped.items() if members]


def markdown_title(item: dict) -> str:
    title = (item["title"] or item["id"]).replace("[", "\\[").replace("]", "\\]")
    link = safe_link(item)
    return f"[{title}]({link})" if link else title


def markdown(snapshot: dict, top: int = DEFAULT_TOP) -> str:
    lines = [f"# Project manager report, {snapshot['generated_on']}", ""]
    counts = {key: len(findings(snapshot, key)) for key, _ in SECTIONS}
    lines.append(f"{len(snapshot['items'])} work items: {counts['next']} ranked, {counts['stuck']} stuck, "
                 f"{counts['looks_done']} look done, {counts['waiting_on_erik']} waiting on Erik, "
                 f"{counts['agent_prs']} agent or bot PRs awaiting a verdict, {counts['archive']} archive candidates.")
    summary, groups = change_lines(snapshot, top)
    lines += ["", "## What changed since last run", "", summary]
    for label, count, entries_text in groups:
        lines += ["", f"{label} ({count}):"] + [f"- {text}" for text in entries_text]
    lines += ["", "## Sources", ""]
    for name, source in snapshot["sources"].items():
        lines.append(f"- {name}: {source['count']} items, {len(source['errors'])} errors")
        lines += [f"  - {error}" for error in source["errors"]]
    lines += ["", "## PR verdicts", "", f"{len(findings(snapshot, 'pr_verdicts'))} open PRs classified."]
    for label, count, action, members in verdict_groups(snapshot, top):
        lines += ["", f"### {label} ({count})", "", f"Suggested action: {action}", ""]
        lines += [f"- {markdown_title(item)} ({item['project']}): {item.get('verdict_evidence') or ''}" for _, item in members]
    for key, heading in SECTIONS:
        lines += ["", f"## {heading}", "", f"Top {top} of {counts[key]}.", ""]
        for position, (finding, item) in enumerate(entries(snapshot, key, top), start=1):
            lines.append(f"{position}. {markdown_title(item)} ({item['source']}, {item['project'] or 'no project'}, "
                         f"{item['status']}, score {finding['score']})")
            lines.append(f"   Why: {'; '.join(finding['reasons'])}")
    return "\n".join(lines) + "\n"


STYLE = """
:root { --ground: #f7f5ef; --card: #ffffff; --ink: #1d1d1b; --muted: #5f5f5a; --rule: #dedbd2; --accent: #1f7a5a;
  color-scheme: light; }
@media (prefers-color-scheme: dark) { :root { --ground: #141513; --card: #1e201d; --ink: #ecebe6; --muted: #a9a8a1;
  --rule: #33352f; --accent: #6fd3a8; color-scheme: dark; } }
body { margin: 0; background: var(--ground); color: var(--ink); font: 14px/1.45 system-ui, -apple-system, sans-serif; }
main { padding: 24px 16px; max-width: 1400px; margin: 0 auto; }
h1 { font-size: 20px; margin: 0 0 4px; }
.summary { color: var(--muted); margin: 0 0 16px; }
.board { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
section h2 { font-size: 15px; margin: 0 0 8px; }
.changes, .verdicts { margin: 16px 0; } .verdicts .board { display: block; } .changes h3 { font-size: 13px; margin: 8px 0 2px; }
article { background: var(--card); border: 1px solid var(--rule); border-radius: 8px; padding: 10px 12px; margin: 0 0 8px; }
article a { color: var(--accent); }
.meta { color: var(--muted); font-size: 12px; }
ul { margin: 6px 0 0; padding-left: 18px; }
details { margin-top: 16px; color: var(--muted); }
"""


def html_card(finding: dict, item: dict) -> str:
    title = escape(item["title"] or item["id"])
    link = safe_link(item)
    heading = f'<a href="{escape(link, quote=True)}">{title}</a>' if link else title
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in finding["reasons"])
    meta = escape(f"{item['source']} · {item['project'] or 'no project'} · {item['status']} · score {finding['score']}")
    return f'<article><div>{heading}</div><div class="meta">{meta}</div><ul>{reasons}</ul></article>'


def html(snapshot: dict, top: int = DEFAULT_TOP) -> str:
    columns = []
    for key, heading in SECTIONS:
        cards = "".join(html_card(finding, item) for finding, item in entries(snapshot, key, top))
        total = len(findings(snapshot, key))
        columns.append(f"<section><h2>{escape(heading)} ({total})</h2>{cards or '<p class=meta>Nothing here.</p>'}</section>")
    summary, groups = change_lines(snapshot, top)
    change_html = "".join(f"<h3>{escape(label)} ({count})</h3><ul>" + "".join(f"<li>{escape(text)}</li>" for text in texts) + "</ul>"
                          for label, count, texts in groups if count)
    verdict_html = "".join(
        f"<h3>{escape(label)} ({count})</h3><p class=meta>Suggested action: {escape(action)}</p>"
        + "".join(html_card({"score": finding["score"], "reasons": [item.get("verdict_evidence") or ""]}, item) for finding, item in members)
        for label, count, action, members in verdict_groups(snapshot, top))
    verdict_section = (f"<section class=verdicts><h2>PR verdicts ({len(findings(snapshot, 'pr_verdicts'))})</h2>"
                       f"<div class=board>{verdict_html or '<p class=meta>No PRs classified.</p>'}</div></section>")
    changes = f"<section class=changes><h2>What changed since last run</h2><p class=meta>{escape(summary)}</p>{change_html}</section>"
    sources = "".join(
        f"<li>{escape(name)}: {source['count']} items"
        + "".join(f"<br>{escape(error)}" for error in source["errors"]) + "</li>"
        for name, source in snapshot["sources"].items())
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        f"<title>Project board {escape(snapshot['generated_on'])}</title><style>{STYLE}</style></head><body><main>"
        f"<h1>Project board</h1><p class=summary>{len(snapshot['items'])} work items, generated "
        f"{escape(snapshot['generated_on'])}. Read only; nothing here changes a source.</p>"
        f"{changes}<div class=board>{''.join(columns)}</div>{verdict_section}"
        f"<details><summary>Sources</summary><ul>{sources}</ul></details></main></body></html>\n"
    )
