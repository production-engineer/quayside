from html import escape

SECTIONS = [
    ("next", "What to work on next"),
    ("stuck", "What is stuck"),
    ("looks_done", "Looks done but is not closed"),
    ("waiting_on_erik", "Waiting on Erik"),
]
DEFAULT_TOP = 15


def safe_link(item: dict) -> str | None:
    return next((link for link in item.get("links", []) if link.startswith(("https://", "http://"))), None)


def entries(snapshot: dict, section: str, top: int) -> list[tuple[dict, dict]]:
    items = {item["id"]: item for item in snapshot["items"]}
    return [(finding, items[finding["id"]]) for finding in snapshot["findings"][section][:top] if finding["id"] in items]


def markdown_title(item: dict) -> str:
    title = (item["title"] or item["id"]).replace("[", "\\[").replace("]", "\\]")
    link = safe_link(item)
    return f"[{title}]({link})" if link else title


def markdown(snapshot: dict, top: int = DEFAULT_TOP) -> str:
    lines = [f"# Project manager report, {snapshot['generated_on']}", ""]
    counts = {key: len(snapshot["findings"][key]) for key, _ in SECTIONS}
    lines.append(f"{len(snapshot['items'])} work items: {counts['next']} ranked, {counts['stuck']} stuck, "
                 f"{counts['looks_done']} look done, {counts['waiting_on_erik']} waiting on Erik.")
    lines += ["", "## Sources", ""]
    for name, source in snapshot["sources"].items():
        lines.append(f"- {name}: {source['count']} items, {len(source['errors'])} errors")
        lines += [f"  - {error}" for error in source["errors"]]
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
        total = len(snapshot["findings"][key])
        columns.append(f"<section><h2>{escape(heading)} ({total})</h2>{cards or '<p class=meta>Nothing here.</p>'}</section>")
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
        f"<div class=board>{''.join(columns)}</div>"
        f"<details><summary>Sources</summary><ul>{sources}</ul></details></main></body></html>\n"
    )
