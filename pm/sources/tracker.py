import csv
import re
from pathlib import Path

from pm import signals
from pm.model import SourceResult, WorkItem, parse_day

COLUMN_PREFIXES = [
    ("number", "task #"),
    ("title", "task name"),
    ("description", "task description"),
    ("status_update", "status update"),
    ("status", "status"),
    ("priority", "priority"),
    ("due", "due date"),
    ("lead", "task lead"),
    ("added", "date added"),
    ("updated", "last update"),
]
STATUS_BY_LABEL = {"to do": "open", "todo": "open", "": "open", "backlog": "backlog", "in progress": "in_progress",
                   "done": "done"}
PRIORITIES = {"critical", "high", "medium", "low"}
DONE_WORDS = re.compile(r"(?<!not )(?<!not yet )\b(?:done|shipped|merged|live|completed?)\b", re.IGNORECASE)


def column_map(headers: list[str]) -> dict[str, str]:
    mapping = {}
    for header in headers:
        normalized = " ".join((header or "").lower().split())
        for key, prefix in COLUMN_PREFIXES:
            if key not in mapping and normalized.startswith(prefix):
                mapping[key] = header
                break
    return mapping


def row_item(position: int, row: dict, columns: dict, me: str) -> WorkItem | None:
    def cell(key):
        header = columns.get(key)
        return (row.get(header) or "").strip() if header else ""

    title = cell("title")
    if not title:
        return None
    number = cell("number")
    status_label = " ".join(cell("status").lower().split())
    status = STATUS_BY_LABEL.get(status_label, "unknown")
    update = cell("status_update")
    description = cell("description")
    body = "\n".join([title, description, update])
    lead = cell("lead") or None
    activity = [day for day in (parse_day(cell("added")), parse_day(cell("updated")), *signals.dates_in(update)) if day]
    priority = cell("priority").lower()
    waits = signals.erik_waits(body, me)
    if lead and lead.split()[0].lower() == me.lower():
        waits.insert(0, f"task lead is {me}")
    return WorkItem(
        source="tracker",
        id=f"tracker:{number or f'row{position}'}",
        title=title,
        project="remote-hands",
        kind="task",
        status=status,
        owner=lead,
        created=parse_day(cell("added")),
        last_activity=max(activity) if activity else None,
        links=signals.find_links(body),
        refs=signals.find_refs(body),
        blocked_on=signals.blocked_on(body),
        waiting_on_erik=waits,
        critical_hints=signals.critical_hints(body),
        priority=priority if priority in PRIORITIES else None,
        done_hints=[update[:160]] if status != "done" and DONE_WORDS.search(update) else [],
        evidence=[f"tracker status {cell('status') or '(blank)'}"],
    )


def collect(path: Path, me: str = "Erik") -> SourceResult:
    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames
            if not headers:
                return SourceResult("tracker", [], [f"tracker CSV has no header row: {path}"])
            columns = column_map(headers)
            if "title" not in columns:
                return SourceResult("tracker", [], [f"tracker CSV has no Task name column: {path}"])
            rows = list(reader)
    except (OSError, csv.Error) as problem:
        return SourceResult("tracker", [], [f"could not read tracker CSV {path}: {problem}"])
    items = [item for position, row in enumerate(rows, start=2) if (item := row_item(position, row, columns, me))]
    return SourceResult("tracker", items, [])
