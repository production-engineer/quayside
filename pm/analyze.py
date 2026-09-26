import re
from dataclasses import asdict, dataclass, replace
from datetime import date

from pm.model import WorkItem, idle_days

WAITING_ON_ERIK_WEIGHT = 5
CRITICAL_HINT_WEIGHT = 4
PRIORITY_WEIGHTS = {"critical": 4, "high": 3, "medium": 1, "low": 0}
READY_PR_WEIGHT = 2
AGE_WEEK_WEIGHT = 1
AGE_CAP = 3
BLOCKED_PENALTY = -4
CLAIMED_PENALTY = -3
PARKED_PENALTY = -2
CLAIMED_IDLE_DAYS = 7
OPEN_IDLE_DAYS = 21
CLAIMED_STATUSES = {"in_progress", "review"}
SHORT_REF = re.compile(r"^([\w.-]+)#(\d+)$")


@dataclass
class Finding:
    id: str
    score: int
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def github_index(items: list[WorkItem]) -> dict[str, WorkItem]:
    return {item.github_key: item for item in items if item.github_key}


def qualify_refs(items: list[WorkItem], repos: dict[str, list[str]]) -> list[WorkItem]:
    qualified = []
    for item in items:
        refs = []
        for ref in item.refs:
            short = SHORT_REF.match(ref)
            if short is None:
                refs.append(ref)
                continue
            owners = repos.get(short.group(1), [])
            if len(owners) == 1:
                refs.append(f"{owners[0]}#{short.group(2)}")
        qualified.append(replace(item, refs=sorted(set(refs))))
    return qualified


def unresolved_refs(items: list[WorkItem]) -> list[str]:
    known = github_index(items)
    wanted = {ref for item in items if item.source != "github" for ref in item.refs if "/" in ref}
    return sorted(wanted - set(known))


def looks_done_reasons(item: WorkItem, index: dict[str, WorkItem], closers: dict[str, list[str]],
                       done_linkers: dict[str, list[str]]) -> list[str]:
    if item.status == "done":
        return []
    reasons = [f"says done: {hint}" for hint in item.done_hints]
    if item.source != "github":
        linked = [index[ref] for ref in item.refs if ref in index]
        if linked and all(other.status == "done" for other in linked):
            names = ", ".join(other.github_key for other in linked)
            reasons.append(f"every linked GitHub item it names is closed or merged ({names})")
    for closer in closers.get(item.github_key or "", []):
        reasons.append(f"merged PR {closer} says it closes this")
    for linker in done_linkers.get(item.github_key or "", []):
        reasons.append(f"{linker} is done and links to this open item")
    return reasons


def next_score(item: WorkItem, today: date) -> tuple[int, list[str]]:
    score, reasons = 0, []

    def add(weight: int, reason: str) -> None:
        nonlocal score
        score += weight
        reasons.append(f"{weight:+d} {reason}")

    if item.waiting_on_erik:
        add(WAITING_ON_ERIK_WEIGHT, f"waiting on Erik: {item.waiting_on_erik[0]}")
    if item.critical_hints:
        add(CRITICAL_HINT_WEIGHT, f"critical path hint: {item.critical_hints[0]}")
    if item.priority in PRIORITY_WEIGHTS and PRIORITY_WEIGHTS[item.priority]:
        add(PRIORITY_WEIGHTS[item.priority], f"priority {item.priority}")
    if item.kind == "pr" and item.status == "review":
        add(READY_PR_WEIGHT, "open PR ready to land")
    if item.blocked_on and not item.waiting_on_erik:
        add(BLOCKED_PENALTY, f"blocked on {item.blocked_on}")
    if item.claimed_by:
        add(CLAIMED_PENALTY, f"claimed by {item.claimed_by}")
    if item.status in ("backlog", "paused"):
        add(PARKED_PENALTY, f"status {item.status}")
    idle = idle_days(item, today)
    if idle is None:
        reasons.append("+0 no activity date")
    else:
        add(min(idle // 7 * AGE_WEEK_WEIGHT, AGE_CAP), f"idle {idle} days")
    return score, reasons


def stuck_reasons(item: WorkItem, today: date) -> list[str]:
    idle = idle_days(item, today)
    claimed = item.status in CLAIMED_STATUSES or bool(item.claimed_by)
    if idle is None:
        return ["no activity date recorded"]
    if claimed and idle >= CLAIMED_IDLE_DAYS:
        if item.kind == "pr":
            state = "open for review" if item.status == "review" else "in draft"
            return [f"PR {state} with no activity for {idle} days"]
        who = f" by {item.claimed_by}" if item.claimed_by else ""
        return [f"claimed{who} ({item.status}) with no activity for {idle} days"]
    if idle >= OPEN_IDLE_DAYS:
        return [f"{item.status} with no activity for {idle} days"]
    return []


def analyze(items: list[WorkItem], today: date) -> dict[str, list[Finding]]:
    index = github_index(items)
    closers: dict[str, list[str]] = {}
    done_linkers: dict[str, list[str]] = {}
    for item in items:
        if item.kind == "pr" and item.status == "done":
            for key in item.closes:
                closers.setdefault(key, []).append(item.github_key)
        if item.source != "github" and item.status == "done":
            for key in item.refs:
                done_linkers.setdefault(key, []).append(item.id)
    active = [item for item in items if item.status != "done"]
    looks_done, ranked, stuck, waiting = [], [], [], []
    for item in active:
        idle = idle_days(item, today)
        done_reasons = looks_done_reasons(item, index, closers, done_linkers)
        if done_reasons:
            looks_done.append((idle or 0, Finding(item.id, len(done_reasons), done_reasons)))
            continue
        score, reasons = next_score(item, today)
        ranked.append(Finding(item.id, score, reasons))
        if item.waiting_on_erik:
            waiting.append(Finding(item.id, score, list(item.waiting_on_erik)))
        stuck_why = stuck_reasons(item, today)
        if stuck_why:
            claimed = item.status in CLAIMED_STATUSES or bool(item.claimed_by)
            stuck.append((not claimed, -(idle if idle is not None else 10**6), item.id, Finding(item.id, idle or 0, stuck_why)))
    idle_of = {item.id: idle_days(item, today) or 0 for item in items}
    return {
        "next": sorted(ranked, key=lambda finding: (-finding.score, -idle_of[finding.id], finding.id)),
        "stuck": [entry[-1] for entry in sorted(stuck, key=lambda entry: entry[:3])],
        "looks_done": [finding for _, finding in sorted(looks_done, key=lambda entry: (-entry[0], entry[1].id))],
        "waiting_on_erik": sorted(waiting, key=lambda finding: (-finding.score, -idle_of[finding.id], finding.id)),
    }
