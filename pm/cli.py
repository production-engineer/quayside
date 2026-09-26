import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from pm import analyze, memory, render, tenants, verdicts
from pm.model import SourceResult, WorkItem, parse_day
from pm.sources import github, portals, tasks, tracker

SNAPSHOT_SCHEMA = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path("/private/tmp/claude-501/-Users-erikwilliams-repos/d3f6b786-4af0-4459-b78b-ea696bf4180d/scratchpad/pm-out")
DEFAULT_KEEP = Path.home() / "repos" / "Keep"
DEFAULT_TASKS = Path.home() / "repos" / "quayside_personal" / "TASKS.md"
DEFAULT_STATE_DIR = Path.home() / ".quayside" / "pm"
DEFAULT_EXCLUDED_REPOS = ["beadedcloud/beadedcloud.com"]
DEFAULT_SINCE_DAYS = 14
MAX_LOOKUPS = 150


def day_argument(value: str) -> date:
    day = parse_day(value)
    if day is None:
        raise argparse.ArgumentTypeError(f"not a calendar day in YYYY-MM-DD form: {value!r}")
    return day


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="python3 -m pm", description="Read-only project manager report across Erik's work sources.")
    cli.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder, must be outside this repository")
    cli.add_argument("--keep", type=Path, default=DEFAULT_KEEP, help="folder holding portal-*.md files")
    cli.add_argument("--tasks", type=Path, default=DEFAULT_TASKS, help="quayside TASKS.md path")
    cli.add_argument("--tracker-csv", type=Path, help="RH Task Tracker exported as CSV")
    cli.add_argument("--owner", action="append", help="GitHub owner to scan; repeat; default is you plus your orgs")
    cli.add_argument("--exclude-repo", action="append", help=f"GitHub repo to skip; repeat; default {DEFAULT_EXCLUDED_REPOS}")
    cli.add_argument("--no-github", action="store_true", help="skip GitHub entirely")
    cli.add_argument("--since-days", type=positive, default=DEFAULT_SINCE_DAYS, help="window for recently merged or closed")
    cli.add_argument("--max-pages", type=positive, default=github.DEFAULT_MAX_PAGES, help="GitHub search pages per query")
    cli.add_argument("--today", type=day_argument, default=date.today(), help="reference day, YYYY-MM-DD")
    cli.add_argument("--me", default="Erik", help="name used to spot work waiting on you")
    cli.add_argument("--top", type=positive, default=render.DEFAULT_TOP, help="items per section in the report")
    cli.add_argument("--archive-days", type=positive, default=analyze.ARCHIVE_DAYS,
                     help="idle days after which open work becomes an archive candidate")
    cli.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR, help="where the previous run is kept")
    cli.add_argument("--no-memory", action="store_true", help="do not compare with or record the previous run")
    cli.add_argument("--from-snapshot", type=Path, help="re-render report and board from an existing snapshot.json")
    cli.add_argument("--tenant", action="append", choices=tenants.TENANTS, help="tenant to run; repeat; default all")
    cli.add_argument("--combined-view", action="store_true",
                     help="print one view composed from the per-tenant snapshots; writes nothing")
    return cli


def build_snapshot_dict(results: list[SourceResult], findings: dict, today: date, tenant: str | None = None) -> dict:
    return {
        "schema": SNAPSHOT_SCHEMA,
        "tenant": tenant,
        "generated_on": today.isoformat(),
        "sources": {result.name: {"count": len(result.items), "errors": result.errors} for result in results},
        "items": [item.to_dict() for result in results for item in result.items],
        "findings": {key: [finding.to_dict() for finding in values] for key, values in findings.items()},
    }


def local_sources(options, owner_map, remote_owner) -> tuple[dict[str, list[SourceResult]], Counter]:
    collected = [portals.collect(options.keep, me=options.me, today=options.today),
                 tasks.collect(options.tasks, me=options.me)]
    if options.tracker_csv:
        collected.append(tracker.collect(options.tracker_csv, me=options.me, today=options.today))
    by_tenant = {tenant: [] for tenant in tenants.TENANTS}
    unassigned = Counter()
    for result in collected:
        buckets = {tenant: [] for tenant in tenants.TENANTS}
        for item in result.items:
            tenant = tenants.attribute(item, owner_map, remote_owner, tasks_path=options.tasks, home=Path.home())
            if tenant is None:
                unassigned[result.name] += 1
            else:
                buckets[tenant].append(item)
        for tenant in tenants.TENANTS:
            by_tenant[tenant].append(SourceResult(result.name, buckets[tenant], list(result.errors)))
    return by_tenant, unassigned


def github_owners(gh, options) -> tuple[list[str], str | None]:
    try:
        viewer = gh(["api", "user", "--jq", ".login"]).strip()
        return (list(options.owner) if options.owner else github.discover_owners(gh, viewer)), None
    except github.GhFailure as problem:
        return [], f"GitHub unavailable: {problem}"


def github_sources(gh, options, owners: list[str], results: list[SourceResult], tenant: str, owner_map) -> list[SourceResult]:
    excluded = options.exclude_repo or DEFAULT_EXCLUDED_REPOS
    hub = github.collect(gh, owners=owners, exclude=excluded, since=options.today - timedelta(days=options.since_days),
                         me=options.me, max_pages=options.max_pages)
    results = [*results, hub]
    for result in results:
        result.items = analyze.qualify_refs(result.items, hub.repos)
    results.append(classify_prs(gh, hub))
    skipped = {repo.lower() for repo in excluded}
    missing = [ref for ref in analyze.unresolved_refs([item for result in results for item in result.items])
               if ref.split("#", 1)[0] not in skipped and tenants.tenant_of_owner(ref.split("/", 1)[0], owner_map) == tenant]
    if missing and hub.viewer:
        found, errors = github.lookup(gh, missing[:MAX_LOOKUPS], viewer=hub.viewer, me=options.me)
        results.append(SourceResult("github-lookups", found, errors))
        if len(missing) > MAX_LOOKUPS:
            results[-1].errors.append(f"{len(missing) - MAX_LOOKUPS} linked refs were not looked up (cap {MAX_LOOKUPS})")
    return results


def tenant_results(tenant: str, results: list[SourceResult], owner_map, remote_owner, options) -> list[SourceResult]:
    for result in results:
        result.items = [item for item in result.items
                        if tenants.attribute(item, owner_map, remote_owner, tasks_path=options.tasks, home=Path.home()) == tenant]
    return results


def classify_prs(gh, hub: github.GithubResult) -> SourceResult:
    open_prs = [item.github_key for item in hub.items if item.kind == "pr" and item.status in ("review", "in_progress")]
    states, recent, errors = github.pr_states(gh, open_prs)
    classified = []
    for position, item in enumerate(hub.items):
        state = states.get(item.github_key or "")
        if state is None:
            continue
        verdict, evidence = verdicts.verdict_of(state, recent.get(item.project.lower(), []))
        hub.items[position] = replace(item, verdict=verdict, verdict_evidence=evidence)
        classified.append(item.id)
    missing = len(open_prs) - len(classified)
    if missing:
        errors.append(f"{missing} open PRs got no verdict because their state could not be read")
    return SourceResult("pr-verdicts", [], errors)


def inside_repository(path: Path) -> bool:
    return path == REPO_ROOT or REPO_ROOT in path.parents


def write_outputs(snapshot: dict, out: Path, top: int) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = {
        out / "snapshot.json": json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        out / "report.md": render.markdown(snapshot, top),
        out / "board.html": render.html(snapshot, top),
    }
    for path, text in written.items():
        path.write_text(text, encoding="utf-8")
    return list(written)


def combined_view(options) -> int:
    snapshots = []
    for tenant in tenants.TENANTS:
        path = options.out / tenant / "snapshot.json"
        if path.exists():
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
    if not snapshots:
        print(f"no tenant snapshots under {options.out}; run python3 -m pm first")
        return 1
    print(render.combined(snapshots, options.top))
    print("Composed at read time from the per-tenant snapshots; nothing was written.")
    return 0


def run_tenant(tenant: str, results: list[SourceResult], options) -> tuple[list[Path], bool]:
    items = [item for result in results for item in result.items]
    snapshot = build_snapshot_dict(results, analyze.analyze(items, options.today, options.archive_days), options.today, tenant)
    for name, source in snapshot["sources"].items():
        for error in source["errors"]:
            print(f"{tenant} {name}: {error}", file=sys.stderr)
    remember = not options.no_memory
    state = options.state_dir / tenant
    if remember:
        previous, warning = memory.load(state)
        if warning:
            print(f"{tenant} memory: {warning}", file=sys.stderr)
        snapshot["changes"] = memory.diff(previous, snapshot)
    try:
        written = write_outputs(snapshot, options.out / tenant, options.top)
    except OSError as problem:
        print(f"could not write to {options.out / tenant}: {problem}", file=sys.stderr)
        return [], False
    if remember:
        try:
            written.append(memory.save(state, snapshot))
        except OSError as problem:
            print(f"{tenant} memory: could not record this run in {state}: {problem}", file=sys.stderr)
    return written, True


def main(argv: list[str] | None = None, gh=github.gh, remote_owner=tenants.git_remote_owner) -> int:
    options = parser().parse_args(argv)
    options.out = options.out.expanduser().resolve()
    options.state_dir = options.state_dir.expanduser().resolve()
    if options.combined_view:
        return combined_view(options)
    for label, path in (("--out", options.out), ("--state-dir", options.state_dir)):
        if inside_repository(path):
            print(f"refusing to write inside the repository ({REPO_ROOT}); pick a {label} folder outside it", file=sys.stderr)
            return 2
    if options.from_snapshot:
        snapshot = json.loads(options.from_snapshot.read_text(encoding="utf-8"))
        if snapshot.get("tenant") not in tenants.TENANTS:
            print("refusing to re-render a snapshot that names no tenant", file=sys.stderr)
            return 2
        for path in write_outputs(snapshot, options.out / snapshot["tenant"], options.top):
            print(path)
        return 0
    owner_map = tenants.load_owner_map()
    local, unassigned = local_sources(options, owner_map, remote_owner)
    owners, owner_error = ([], None) if options.no_github else github_owners(gh, options)
    for tenant in options.tenant or tenants.TENANTS:
        results = local[tenant]
        if owner_error:
            results = [*results, SourceResult("github", [], [owner_error])]
        elif not options.no_github:
            tenant_owners = [owner for owner in owners if tenants.tenant_of_owner(owner, owner_map) == tenant]
            if tenant_owners:
                results = github_sources(gh, options, tenant_owners, results, tenant, owner_map)
        written, ok = run_tenant(tenant, tenant_results(tenant, results, owner_map, remote_owner, options), options)
        if not ok:
            return 2
        for path in written:
            print(path)
    counts = ", ".join(f"{source} {count}" for source, count in sorted(unassigned.items())) or "none"
    print(f"unassigned: {counts}")
    return 0
