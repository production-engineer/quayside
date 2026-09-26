import re
from pathlib import Path

from pm import signals
from pm.model import SourceResult, WorkItem, parse_day

TASK_LINE = re.compile(r"^- \[( |x|X)\] (\d+)\. (.+?)(?: \(added ([^)]*)\))?\s*$")
SECTION = re.compile(r"^## (.+?)\s*$")
TASK_DEPENDENCY = re.compile(r"\btask (\d+)\b", re.IGNORECASE)
TASK_SECTIONS = {"open", "done"}


def parse_blocks(text: str) -> list[dict]:
    blocks, section, current = [], None, None
    for line in text.splitlines():
        heading = SECTION.match(line)
        if heading:
            section = heading.group(1).strip().lower()
            current = None
            continue
        if section not in TASK_SECTIONS:
            continue
        task = TASK_LINE.match(line)
        if task:
            box, number, title, added = task.groups()
            current = {"number": number, "title": title.strip(), "added": added, "checked": box != " ",
                       "section": section, "lines": []}
            blocks.append(current)
        elif current is not None and line.strip():
            current["lines"].append(line.strip())
    return blocks


def dependency(block: dict, numbers: set[str], done_numbers: set[str]) -> str | None:
    phrase = signals.blocked_on(" ".join(block["lines"]))
    if phrase is None:
        return None
    task = TASK_DEPENDENCY.search(phrase)
    if task is None or "tracker" in phrase.lower() or task.group(1) not in numbers:
        return phrase
    number = task.group(1)
    return None if number in done_numbers else f"task {number} (open)"


def collect(path: Path, me: str = "Erik") -> SourceResult:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as problem:
        return SourceResult("tasks", [], [f"could not read {path}: {problem}"])
    blocks = parse_blocks(text)
    numbers = {block["number"] for block in blocks}
    done_numbers = {block["number"] for block in blocks if block["checked"] or block["section"] == "done"}
    items = []
    for block in blocks:
        body = "\n".join([block["title"], *block["lines"]])
        created = parse_day(block["added"])
        items.append(WorkItem(
            source="tasks",
            id=f"tasks:{block['number']}",
            title=block["title"],
            project="quayside",
            kind="task",
            status="done" if block["number"] in done_numbers else "open",
            created=created,
            last_activity=created,
            links=signals.find_links(body),
            refs=signals.find_refs(body),
            status_refs=signals.find_refs(body),
            blocked_on=dependency(block, numbers, done_numbers),
            waiting_on_erik=signals.erik_waits(body, me),
            critical_hints=signals.critical_hints(body),
            evidence=[f"TASKS.md section {block['section']}"],
        ))
    return SourceResult("tasks", items, [])
