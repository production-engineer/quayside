# pm: the read-only project manager prototype

`pm` gathers work items from the places Erik's work actually lives, puts them into one model, and answers four questions: what to work on next, what is stuck, what looks done but is not closed, and what is waiting on Erik. It also sets aside agent and bot PRs awaiting a verdict and archive candidates, and says what changed since the last run. It is the first dogfood slice of quayside as "the AI project manager that has full visibility and actually gets projects done" (Erik, 2026-09-26).

It only reads. It never comments, labels, closes, renames, or edits anything in any source. It uses the Python 3 standard library and the `gh` CLI, and nothing else. It lives in its own folder and does not touch the legacy Django app.

## Run it

From the repository root:

```bash
python3 -m pm
python3 -m pm --tracker-csv ~/Downloads/rh-task-tracker.csv
python3 -m pm --no-github --out /tmp/pm-out
python3 -m pm --from-snapshot /tmp/pm-out/snapshot.json --out /tmp/pm-out
```

It writes three files to `--out`: `report.md`, `snapshot.json`, and `board.html` (a static page with no external requests). The default output folder is the scratchpad of the session that built this prototype. The tool refuses to write anywhere inside this repository, so generated snapshots can never be committed by accident.

| Flag | Default | What it does |
|---|---|---|
| `--out` | session scratchpad `pm-out/` | Output folder; must be outside the repository |
| `--keep` | `~/repos/Keep` | Folder holding `portal-*.md` handoffs |
| `--tasks` | `~/repos/quayside_personal/TASKS.md` | quayside task list |
| `--tracker-csv` | none | RH Task Tracker exported from Google Sheets as CSV; skipped when absent |
| `--owner` | you plus every org you belong to | GitHub owner to scan; repeatable |
| `--exclude-repo` | `beadedcloud/beadedcloud.com` (frozen) | GitHub repo to skip; repeatable; replaces the default |
| `--no-github` | off | Skip GitHub entirely |
| `--since-days` | 14 | Window for recently merged PRs and recently closed tickets |
| `--max-pages` | 10 | GitHub search pages (100 results each) per query |
| `--today` | today | Reference day for every age calculation |
| `--me` | `Erik` | Name used to spot work waiting on you |
| `--top` | 15 | Items per section in the report and board |
| `--archive-days` | 90 | Idle days after which open work becomes an archive candidate |
| `--state-dir` | `~/.quayside/pm` | Where the previous run is kept; must be outside the repository |
| `--no-memory` | off | Neither compare with nor record the previous run |

A source that fails (no `gh` login, a missing file, a malformed CSV) is recorded under `sources.<name>.errors` in the snapshot and printed to stderr; the other sources still run and the report is still written.

## Sources

Each source is one module under `pm/sources/` with a `collect(...)` function that returns a `SourceResult(name, items, errors)`. Adding a source means adding one module and one line in `pm/cli.py`.

| Source | Module | Status comes from | Last activity comes from |
|---|---|---|---|
| Portal handoffs | `portals.py` | Filename suffix (`-not-started`, `-in-progress`, `-done`, `-paused`); a `> **Paused` banner pauses it | Latest of filename date, dates in `> **` banners, the file's last git commit |
| quayside tasks | `tasks.py` | `## Open` or `## Done` section, or a checked box | The `(added YYYY-MM-DD)` date |
| GitHub | `github.py` | Open, draft, ready for review, merged, closed | `updatedAt` |
| RH Task Tracker CSV | `tracker.py` | `Status` column (To Do, Backlog, In progress, Done) | Latest of Date added, Last update, dates in Status Update |

GitHub is read with four GraphQL searches per owner: open tickets, open PRs, PRs merged in the window, and tickets closed in the window. Any `owner/repo#N` that another source mentions but the searches did not return is then fetched one by one (at most 150), so cross-source checks see its real state. Excluded repos are never looked up. Ticket and PR bodies are scanned for signals and then dropped; they are never written to the snapshot.

The tracker adapter maps columns by header name, so reordered columns still work. The tool itself never calls the Google API; export the sheet as CSV and pass its path.

## The model

Every source produces `WorkItem` records (`pm/model.py`):

| Field | Meaning |
|---|---|
| `source`, `id` | Where it came from and a stable id (`portal:2026-09-14-quayside-schema`, `tasks:4`, `github:owner/repo#12`, `tracker:98`) |
| `title`, `project`, `kind` | What it is |
| `status` | One of `open`, `backlog`, `in_progress`, `review`, `paused`, `done`, `unknown` |
| `owner`, `claimed_by` | Assignee or claiming session, when known |
| `created`, `last_activity` | Calendar days in Alaska time; unparseable dates become empty rather than guessed, and dates after the reference day never count as activity |
| `links`, `refs` | http(s) links, and GitHub references normalized to `owner/repo#N` |
| `blocked_on` | First "blocked on", "blocked by", or "depends on" phrase, or a `blocked` label |
| `waiting_on_erik` | Evidence snippets that the next move is Erik's |
| `critical_hints` | Evidence snippets such as "top of queue" or "critical path" |
| `priority` | `critical`, `high`, `medium`, `low` from the tracker or GitHub labels |
| `done_hints`, `closes` | Text saying the work is done; tickets a merged PR says it closes |
| `status_refs`, `done_refs` | The subset of `refs` that tracks status, and the subset the text claims is done (see below) |
| `agent_authored`, `bot_authored` | Body or head commit carries "Generated with Claude Code" or "Co-Authored-By: Claude"; author is a bot |
| `evidence` | Short notes on how the status was read |

## How each question is answered

All weights and thresholds are constants at the top of `pm/analyze.py`. Every finding carries its reasons, so the ranking can be checked line by line.

### Order of buckets

An open item idle for `--archive-days` or more goes only to **archive candidates** (report only; nothing is closed). An item that looks done goes only to **looks done**. A PR by an agent or a bot, open and idle for 7 days or more, goes to **agent and bot PRs awaiting a verdict** instead of "stuck". Everything else is ranked in "next", and may also appear in "stuck" and "waiting on Erik".

### What to work on next

Every remaining item gets a score:

| Signal | Weight |
|---|---|
| Waiting on Erik | +5 |
| Critical path hint in the text ("top of queue", "next thing to pick up", "critical path", "blocks the MVP") | +4 |
| Priority critical, high, medium | +4, +3, +1 |
| Open PR ready for review | +2 |
| Each full week since last activity | +1, capped at +3 |
| Blocked on someone other than Erik | -4 |
| Claimed by another session (portal `-in-progress`) | -3 |
| Backlog or paused | -2 |

Ties go to the item idle longest, then to the id, so the order is deterministic.

### What is stuck

An item is stuck when it is claimed (in progress, draft PR, PR in review, or a claimed portal) with no activity for 7 days, or open with no activity for 21 days, or has no activity date at all. Claimed items are listed before merely old ones, then longest idle first.

### What looks done but is not closed

- The item's own text says it is done (a `> **Done` portal banner, or a tracker Status Update saying done, shipped, merged, or live) while its status is still open.
- Every tracking link of a portal, task, or tracker row (among the links that could be resolved) is closed or merged.
- A merged PR says it closes an open ticket.
- A done portal, task, or tracker row links to a GitHub item that is still open.
- A portal lists a GitHub item as done while that item is still open.

Only links in a status-bearing context count, so a passing mention in background prose never drives a cross-check. In a portal, tracking links sit on a `Tracked` or `Status` line, an unchecked box, a banner, or under a heading about status, progress, or next steps. Done links sit on a checked box, a `Done` or `Shipped` line or banner, or under a heading about what is done or shipped. Every link in a task or tracker row counts as tracking.

### What is waiting on Erik

- A PR where review is requested from you.
- Someone else's ready PR, not written by an agent or a bot, in a repo you own.
- A tracker row whose task lead is Erik.
- Text that says so: "waiting on Erik", "needs Erik's go", "ask Erik", "decide with Erik", "Erik's call", and similar phrasings in `pm/signals.py`. Approval already granted ("with Erik's go") does not count.

Bots (Dependabot, Renovate, GitHub Actions) never produce waiting-on-Erik items.

## What changed since last run

After each run the snapshot is kept at `~/.quayside/pm/last-snapshot.json` (folder mode 700, file mode 600, outside every repository). The next run lists items that are new, closed, gone from the sources, newly stuck, or whose status flipped. A missing or unreadable previous run is reported and treated as a first run.

## Plugging in a model later

This version makes no LLM call. The seam is the snapshot: `snapshot.json` (schema 1) holds `sources`, `items` (every `WorkItem` field), and `findings`, where each finding is `{id, score, reasons}`. A later step, whether a hosted model or a self-hosted Hermes model, reads the snapshot and writes findings in the same shape; `python3 -m pm --from-snapshot` then renders them. Nothing in the model or the renderers assumes a provider.

## Known limits

- Signals are regular expressions over prose. They miss unusual phrasings and occasionally match boilerplate; every signal shows its snippet so a wrong one is easy to spot.
- `blocked_on` takes the first matching phrase in a whole portal, which can be historical context rather than a current blocker.
- Status contexts are recognized by headings and line prefixes; a portal that writes status in free prose is not cross-checked.
- Agent authorship is read from the PR body and head commit only; an agent PR with neither marker counts as human.
- Short refs like `repo#12` resolve only when exactly one owner has a repo by that name; bare `#12` and `PR #73` are ignored.
- GitHub search returns at most 1000 results per query; the report says when a query was truncated.
- TASKS.md has no per-task activity date, so an old task always reads as stuck.
- Lookups and portal git dates run one process at a time. A live run takes about a minute, mostly GitHub search.
- The default `--out` is a session scratchpad path on this Mac; pass `--out` anywhere else.
- Owners, ages, and statuses are only as current as the sources. Run memory keeps one previous snapshot, not a history.

## Tests

```bash
python3 -m unittest discover -s pm/tests -t .
```

Every fixture is invented and labeled as invented. Tests never call `gh`; the GitHub adapter takes an injectable runner.
