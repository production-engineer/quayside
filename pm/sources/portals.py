import re
import subprocess
from datetime import date
from pathlib import Path

from pm import signals
from pm.model import SourceResult, WorkItem, parse_day

FILENAME = re.compile(r"^portal-(?:(\d{4}-\d{2}-\d{2})-)?(.+?)(?:-(not-started|in-progress|done|paused|blocked))?\.md$")
STATUS_BY_SUFFIX = {"not-started": "open", "in-progress": "in_progress", "done": "done", "paused": "paused",
                    "blocked": "open"}
TITLE_SUFFIX = re.compile(r"\s*(?:[:—-]\s*)?Handoff\s*$", re.IGNORECASE)
CLAIMANT = re.compile(r"\bby (session [\w.-]+|an active session)", re.IGNORECASE)
UNBANNERED_CLAIM = "another session (filename says in-progress)"


def git_last_commit_day(path: Path) -> date | None:
    try:
        completed = subprocess.run(["git", "-C", str(path.parent), "log", "-1", "--format=%cI", "--", path.name],
                                   capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_day(completed.stdout.strip()) if completed.returncode == 0 else None


def banners(text: str) -> list[str]:
    return [line.strip()[1:].strip() for line in text.splitlines() if line.strip().startswith("> **")]


def heading(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            title = TITLE_SUFFIX.sub("", line[2:].strip())
            return title or None
    return None


def parse(path: Path, text: str, me: str, last_commit_day, today: date) -> WorkItem:
    match = FILENAME.match(path.name)
    filename_day, slug, suffix = match.groups()
    evidence = []
    status = STATUS_BY_SUFFIX.get(suffix, "unknown")
    if suffix is None:
        evidence.append("filename has no lifecycle suffix")
    else:
        evidence.append(f"filename says {suffix}")
    created = parse_day(filename_day)
    banner_lines = banners(text)
    tracking_text, done_text = signals.status_contexts(text)
    activity = [created, last_commit_day(path)]
    claimed_by = None
    done_hints = []
    for line in banner_lines:
        activity.extend(signals.dates_in(line))
        lowered = line.lower().lstrip("*")
        if lowered.startswith("done"):
            done_hints.append(line[:160])
        if lowered.startswith("paused") and status != "done":
            status = "paused"
            evidence.append("banner says paused")
        claimant = CLAIMANT.search(line)
        if claimant and "claim" in lowered:
            claimed_by = claimant.group(1)
    if status == "in_progress" and claimed_by is None:
        claimed_by = UNBANNERED_CLAIM
    return WorkItem(
        source="portal",
        id=f"portal:{filename_day + '-' if filename_day else ''}{slug}",
        title=heading(text) or slug,
        project="Keep",
        kind="portal",
        status=status,
        owner=claimed_by if claimed_by != UNBANNERED_CLAIM else None,
        created=created,
        last_activity=max([day for day in activity if day and day <= today], default=None),
        links=signals.find_links(text),
        refs=signals.find_refs(text),
        status_refs=signals.find_refs(tracking_text),
        done_refs=signals.find_refs(done_text),
        blocked_on="filename says blocked" if suffix == "blocked" else signals.blocked_on(text),
        waiting_on_erik=signals.erik_waits(text, me),
        critical_hints=signals.critical_hints(text),
        done_hints=done_hints if status != "done" else [],
        claimed_by=claimed_by if status in ("in_progress", "paused") else None,
        evidence=evidence,
    )


def collect(keep_dir: Path, me: str = "Erik", last_commit_day=git_last_commit_day,
            today: date | None = None) -> SourceResult:
    keep_dir = Path(keep_dir)
    if not keep_dir.is_dir():
        return SourceResult("portals", [], [f"portal folder not found: {keep_dir}"])
    items, errors = [], []
    for path in sorted(keep_dir.glob("portal-*.md")):
        if not FILENAME.match(path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as problem:
            errors.append(f"could not read {path.name}: {problem}")
            continue
        items.append(parse(path, text, me, last_commit_day, today or date.today()))
    return SourceResult("portals", items, errors)
