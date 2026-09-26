import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from pm import analyze, render
from pm.model import SourceResult, WorkItem, parse_day
from pm.sources import github, portals, tasks, tracker

SNAPSHOT_SCHEMA = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path("/private/tmp/claude-501/-Users-erikwilliams-repos/d3f6b786-4af0-4459-b78b-ea696bf4180d/scratchpad/pm-out")
DEFAULT_KEEP = Path.home() / "repos" / "Keep"
DEFAULT_TASKS = Path.home() / "repos" / "quayside_personal" / "TASKS.md"
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
    cli.add_argument("--from-snapshot", type=Path, help="re-render report and board from an existing snapshot.json")
    return cli


def build_snapshot_dict(results: list[SourceResult], findings: dict, today: date) -> dict:
    return {
        "schema": SNAPSHOT_SCHEMA,
        "generated_on": today.isoformat(),
        "sources": {result.name: {"count": len(result.items), "errors": result.errors} for result in results},
        "items": [item.to_dict() for result in results for item in result.items],
        "findings": {key: [finding.to_dict() for finding in values] for key, values in findings.items()},
    }


def collect_sources(options, gh) -> list[SourceResult]:
    results = [portals.collect(options.keep, me=options.me), tasks.collect(options.tasks, me=options.me)]
    if options.tracker_csv:
        results.append(tracker.collect(options.tracker_csv, me=options.me))
    if options.no_github:
        return results
    hub = github.collect(gh, owners=options.owner, exclude=options.exclude_repo or DEFAULT_EXCLUDED_REPOS,
                         since=options.today - timedelta(days=options.since_days), me=options.me,
                         max_pages=options.max_pages)
    results.append(hub)
    for result in results:
        result.items = analyze.qualify_refs(result.items, hub.repos)
    missing = analyze.unresolved_refs([item for result in results for item in result.items])
    if missing and hub.viewer:
        found, errors = github.lookup(gh, missing[:MAX_LOOKUPS], viewer=hub.viewer, me=options.me)
        results.append(SourceResult("github-lookups", found, errors))
        if len(missing) > MAX_LOOKUPS:
            results[-1].errors.append(f"{len(missing) - MAX_LOOKUPS} linked refs were not looked up (cap {MAX_LOOKUPS})")
    return results


def inside_repository(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    return resolved == REPO_ROOT or REPO_ROOT in resolved.parents


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


def main(argv: list[str] | None = None, gh=github.gh) -> int:
    options = parser().parse_args(argv)
    if inside_repository(options.out):
        print(f"refusing to write inside the repository ({REPO_ROOT}); pick an --out folder outside it", file=sys.stderr)
        return 2
    if options.from_snapshot:
        snapshot = json.loads(options.from_snapshot.read_text(encoding="utf-8"))
    else:
        results = collect_sources(options, gh)
        items = [item for result in results for item in result.items]
        snapshot = build_snapshot_dict(results, analyze.analyze(items, options.today), options.today)
        for name, source in snapshot["sources"].items():
            for error in source["errors"]:
                print(f"{name}: {error}", file=sys.stderr)
    for path in write_outputs(snapshot, options.out, options.top):
        print(path)
    return 0
