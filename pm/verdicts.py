import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePosixPath

MERGE_READY = "MERGE_READY"
NEEDS_REBASE = "NEEDS_REBASE"
SUPERSEDED = "SUPERSEDED"
STALE_DECISION = "STALE_DECISION"
BROKEN = "BROKEN"
DEPENDENCY_BUMP = "DEPENDENCY_BUMP"
UNKNOWN = "UNKNOWN"
ORDER = [MERGE_READY, NEEDS_REBASE, SUPERSEDED, STALE_DECISION, BROKEN, DEPENDENCY_BUMP, UNKNOWN]
LABELS = {MERGE_READY: "Merge ready", NEEDS_REBASE: "Needs rebase", SUPERSEDED: "Superseded",
          STALE_DECISION: "Stale decision", BROKEN: "Broken CI", DEPENDENCY_BUMP: "Dependency bump", UNKNOWN: "Unknown"}
ACTIONS = {
    MERGE_READY: "Merge it.",
    NEEDS_REBASE: "Rebase onto the base branch, then re-check CI.",
    SUPERSEDED: "Close as superseded by the merged PR named in the evidence.",
    STALE_DECISION: "Decide: ship it or close it.",
    BROKEN: "Fix the failing checks or close it.",
    DEPENDENCY_BUMP: "Merge if CI is green and the bump is minor; otherwise check the changelog first.",
    UNKNOWN: "Re-run later; GitHub had not finished computing its state.",
}

TITLE_SIMILARITY = 0.5
FILE_COVERAGE = 0.5
STRONG_TITLE_SIMILARITY = 0.3
STRONG_FILE_COVERAGE = 0.9
STRONG_MIN_FILES = 3
COMMON_FILES = {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb", "vercel.json",
                "tsconfig.json", ".gitignore", "readme.md", "changelog.md", "claude.md", "requirements.txt", "pyproject.toml",
                "poetry.lock", "cargo.lock", "go.mod", "go.sum", ".env.example", "next.config.js", "next.config.mjs"}
COMMON_PREFIXES = (".github/",)
STOPWORDS = {"the", "and", "for", "that", "with", "are", "was", "were", "this", "from", "into", "onto", "its", "of", "to", "a",
             "an", "in", "on", "is", "be"}
WORD = re.compile(r"[a-z0-9]+")


@dataclass
class PrState:
    key: str
    title: str
    url: str
    is_draft: bool
    mergeable: str
    merge_state: str
    review_decision: str | None
    failing_checks: list[str] = field(default_factory=list)
    pending_checks: list[str] = field(default_factory=list)
    has_checks: bool = False
    files: list[str] = field(default_factory=list)
    bot: bool = False
    created: date | None = None
    last_commit: date | None = None


@dataclass
class MergedPr:
    key: str
    title: str
    url: str
    merged_on: date | None
    files: list[str] = field(default_factory=list)


def significant_files(files: list[str]) -> set[str]:
    return {path for path in files
            if PurePosixPath(path).name.lower() not in COMMON_FILES and not path.startswith(COMMON_PREFIXES)}


def title_words(title: str) -> set[str]:
    return {word for word in WORD.findall(title.lower()) if word not in STOPWORDS}


def title_similarity(first: str, second: str) -> float:
    words, others = title_words(first), title_words(second)
    if not words or not others:
        return 0.0
    return len(words & others) / len(words | others)


def pr_number(key: str) -> int:
    return int(key.rsplit("#", 1)[1]) if "#" in key and key.rsplit("#", 1)[1].isdigit() else 0


def superseded_by(pr: PrState, recent_merged: list[MergedPr]) -> tuple[MergedPr, float] | None:
    own = significant_files(pr.files)
    if not own:
        return None
    best = None
    for candidate in recent_merged:
        if pr_number(candidate.key) <= pr_number(pr.key):
            continue
        if pr.created and (candidate.merged_on is None or candidate.merged_on < pr.created):
            continue
        overlap = own & significant_files(candidate.files)
        coverage = len(overlap) / len(own)
        similarity = title_similarity(pr.title, candidate.title)
        normal = overlap and coverage >= FILE_COVERAGE and similarity >= TITLE_SIMILARITY
        strong = len(overlap) >= STRONG_MIN_FILES and coverage >= STRONG_FILE_COVERAGE and similarity >= STRONG_TITLE_SIMILARITY
        if normal or strong:
            if best is None or coverage > best[1]:
                best = (candidate, coverage)
    return best


def ci_summary(pr: PrState) -> str:
    if pr.failing_checks:
        return f"CI failing: {', '.join(pr.failing_checks)}"
    return "CI green" if pr.has_checks else "no CI checks configured"


def verdict_of(pr: PrState, recent_merged: list[MergedPr]) -> tuple[str, str]:
    if pr.bot:
        advice = "merge if the bump is minor" if not pr.failing_checks and pr.mergeable == "MERGEABLE" else "check before merge"
        return DEPENDENCY_BUMP, f"bot PR; {ci_summary(pr)}; mergeable {pr.mergeable}; {advice}"
    superseding = superseded_by(pr, recent_merged)
    if superseding:
        candidate, coverage = superseding
        return SUPERSEDED, (f"merged PR {candidate.key} ({candidate.title}) covers {coverage:.0%} of this PR's "
                            f"non-trivial files and has a similar title, merged {candidate.merged_on}: {candidate.url}")
    if pr.is_draft:
        return STALE_DECISION, f"draft, last commit {pr.last_commit or 'unknown'}; product decision needed"
    if pr.failing_checks:
        extra = f" (also merge state {pr.merge_state})" if pr.merge_state in ("BEHIND", "DIRTY") else ""
        return BROKEN, f"{ci_summary(pr)}{extra}"
    if pr.mergeable == "CONFLICTING" or pr.merge_state == "DIRTY":
        return NEEDS_REBASE, "real conflicts with the base branch (merge state DIRTY)"
    if pr.merge_state == "BEHIND":
        return NEEDS_REBASE, "behind the base branch with no conflicts (merge state BEHIND)"
    if pr.review_decision == "CHANGES_REQUESTED":
        return STALE_DECISION, "changes requested and not yet addressed"
    if pr.mergeable == "UNKNOWN" or pr.merge_state == "UNKNOWN":
        return UNKNOWN, f"mergeable {pr.mergeable}, merge state {pr.merge_state} after one refetch"
    if pr.pending_checks:
        return UNKNOWN, f"checks still running: {', '.join(pr.pending_checks)}"
    if pr.merge_state == "BLOCKED":
        return STALE_DECISION, f"branch protection blocks the merge (review {pr.review_decision or 'not given'})"
    if pr.mergeable == "MERGEABLE" and pr.merge_state in ("CLEAN", "HAS_HOOKS", "UNSTABLE"):
        return MERGE_READY, f"{ci_summary(pr)}, mergeable, review {pr.review_decision or 'not requested'}"
    return UNKNOWN, f"mergeable {pr.mergeable}, merge state {pr.merge_state}"
