import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date

from pm import signals
from pm.verdicts import MergedPr, PrState
from pm.model import SourceResult, WorkItem, parse_day

COMMAND_TIMEOUT_SECONDS = 120
PAGE_SIZE = 100
BODY_SCAN_CHARS = 6000
DEFAULT_MAX_PAGES = 10
BOT_MARKERS = ("[bot]", "dependabot", "renovate", "github-actions")
PRIORITY_LABELS = {"critical": "critical", "p0": "critical", "high": "high", "p1": "high", "medium": "medium",
                   "p2": "medium", "low": "low", "p3": "low"}
PRIORITY_RANK = ["low", "medium", "high", "critical"]
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:([\w.-]+/[\w.-]+))?#(\d+)", re.IGNORECASE)
REF_KEY = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")

SEARCH_QUERY = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: %d, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      __typename
      ... on Issue {
        number title url state createdAt updatedAt closedAt body
        repository { nameWithOwner }
        author { login }
        assignees(first: 10) { nodes { login } }
        labels(first: 20) { nodes { name } }
      }
      ... on PullRequest {
        number title url state createdAt updatedAt closedAt body isDraft mergedAt
        repository { nameWithOwner }
        author { login }
        assignees(first: 10) { nodes { login } }
        labels(first: 20) { nodes { name } }
        reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } }
        commits(last: 1) { nodes { commit { message } } }
      }
    }
  }
}
""" % PAGE_SIZE


PRS_PER_QUERY = 25
RECENT_MERGED_PER_REPO = 30
UNKNOWN_RETRY_SECONDS = 5
FAILING_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
FAILING_STATES = {"FAILURE", "ERROR"}
PENDING_STATES = {"PENDING", "EXPECTED"}
PR_STATE_FIELDS = """number title url isDraft mergeable mergeStateStatus reviewDecision createdAt author { login }
      files(first: 100) { nodes { path } }
      commits(last: 1) { nodes { commit { committedDate statusCheckRollup { state contexts(first: 50) { nodes {
        __typename ... on CheckRun { name conclusion status } ... on StatusContext { context state } } } } } } }"""
RECENT_MERGED_FIELDS = """merged: pullRequests(states: MERGED, first: %d, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title url mergedAt files(first: 100) { nodes { path } } } }""" % RECENT_MERGED_PER_REPO


class GhFailure(Exception):
    pass


@dataclass
class GithubResult(SourceResult):
    owners: list[str] = field(default_factory=list)
    repos: dict[str, list[str]] = field(default_factory=dict)
    viewer: str | None = None


def run_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as problem:
        raise GhFailure(f"{command[0]} could not run: {problem}") from problem
    if completed.returncode != 0:
        raise GhFailure(f"{' '.join(command[:3])} exited {completed.returncode}: {completed.stderr.strip()[:300]}")
    return completed.stdout


def gh(args: list[str]) -> str:
    return run_command(["gh", *args])


def is_bot(login: str | None) -> bool:
    return bool(login) and any(marker in login.lower() for marker in BOT_MARKERS)


def logins(connection) -> list[str]:
    return [node["login"] for node in (connection or {}).get("nodes", []) if node and node.get("login")]


def reviewers(connection) -> list[str]:
    found = []
    for node in (connection or {}).get("nodes", []):
        reviewer = (node or {}).get("requestedReviewer") or {}
        if reviewer.get("login"):
            found.append(reviewer["login"])
    return found


def label_tokens(label: str) -> list[str]:
    return [token for token in re.split(r"[\s:/_-]+", label.lower()) if token and token != "priority"]


def label_priority(labels: list[str]) -> str | None:
    found = [PRIORITY_LABELS[tokens[0]] for tokens in map(label_tokens, labels)
             if len(tokens) == 1 and tokens[0] in PRIORITY_LABELS]
    return max(found, key=PRIORITY_RANK.index, default=None)


def closing_refs(body: str, repo: str) -> list[str]:
    return sorted({f"{(qualifier or repo)}#{number}".lower() for qualifier, number in CLOSING.findall(body)})


def head_commit_message(node: dict) -> str:
    commits = (node.get("commits") or {}).get("nodes") or []
    return ((commits[-1] or {}).get("commit") or {}).get("message") or "" if commits else ""


def status_of(node: dict) -> str:
    if node.get("state") != "OPEN":
        return "done"
    if node["__typename"] == "PullRequest":
        return "in_progress" if node.get("isDraft") else "review"
    return "open"


def normalize(node: dict, viewer: str | None, me: str) -> WorkItem:
    repo = node["repository"]["nameWithOwner"]
    is_pull = node["__typename"] == "PullRequest"
    body = (node.get("body") or "")[:BODY_SCAN_CHARS]
    author = (node.get("author") or {}).get("login")
    labels = [name.lower() for name in (label.get("name", "") for label in (node.get("labels") or {}).get("nodes", []))]
    status = status_of(node)
    agent = signals.agent_marked(body) or signals.agent_marked(head_commit_message(node))
    in_your_repo = bool(viewer) and repo.split("/", 1)[0].lower() == viewer.lower()
    waits = []
    if is_pull and status == "review" and viewer and viewer in reviewers(node.get("reviewRequests")):
        waits.append("review requested from you")
    elif (is_pull and status == "review" and in_your_repo and author != viewer and not agent
          and not is_bot(author)):
        waits.append("ready PR in your repo awaiting your merge")
    if status != "done":
        waits.extend(signals.erik_waits(body, me))
    blocked = next((f"label: {label}" for label in labels if label_tokens(label) == ["blocked"]), None)
    assignees = logins(node.get("assignees"))
    return WorkItem(
        source="github",
        id=f"github:{repo}#{node['number']}".lower(),
        title=node.get("title") or "",
        project=repo,
        kind="pr" if is_pull else "issue",
        status=status,
        owner=assignees[0] if assignees else (author if is_pull else None),
        created=parse_day(node.get("createdAt")),
        last_activity=parse_day(node.get("updatedAt")),
        links=[node["url"]] if node.get("url") else [],
        refs=sorted(set(signals.find_refs(body)) - {f"{repo}#{node['number']}".lower()}),
        blocked_on=blocked or (signals.blocked_on(body) if status != "done" else None),
        waiting_on_erik=[] if is_bot(author) else waits,
        critical_hints=signals.critical_hints(body) if status != "done" else [],
        priority=label_priority(labels),
        closes=closing_refs(body, repo) if is_pull and node.get("mergedAt") else [],
        closed_on=parse_day(node.get("mergedAt") or node.get("closedAt")) if status == "done" else None,
        agent_authored=agent,
        bot_authored=is_bot(author),
        evidence=[f"GitHub {node['__typename']} {node.get('state', '').lower()}"
                  + (" draft" if node.get("isDraft") else "")],
    )


def search(run, query: str, max_pages: int) -> tuple[list[dict], str | None]:
    nodes, cursor, matched = [], None, 0
    for _ in range(max_pages):
        args = ["api", "graphql", "-f", f"query={SEARCH_QUERY}", "-f", f"q={query}"]
        if cursor:
            args += ["-f", f"after={cursor}"]
        try:
            payload = json.loads(run(args))
        except json.JSONDecodeError as problem:
            raise GhFailure(f"unreadable GitHub response for [{query}]: {problem}") from problem
        if payload.get("errors"):
            raise GhFailure(f"GitHub error for [{query}]: {payload['errors'][0].get('message')}")
        result = payload["data"]["search"]
        matched = result["issueCount"]
        nodes.extend(node for node in result["nodes"] if node and node.get("__typename") in ("Issue", "PullRequest"))
        cursor = result["pageInfo"]["endCursor"]
        if not result["pageInfo"]["hasNextPage"]:
            return nodes, None
    return nodes, f"[{query}] matched {matched} but only {len(nodes)} were fetched"


def discover_owners(run, viewer: str) -> list[str]:
    orgs = [line.strip() for line in run(["api", "user/orgs", "--jq", ".[].login"]).splitlines() if line.strip()]
    return [viewer, *sorted(set(orgs) - {viewer})]


def repo_index(run, owners: list[str], errors: list[str]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for owner in owners:
        try:
            repos = json.loads(run(["repo", "list", owner, "--limit", "1000", "--json", "nameWithOwner"]))
        except (GhFailure, json.JSONDecodeError) as problem:
            errors.append(f"repo list for {owner} failed: {problem}")
            continue
        for repo in repos:
            full = repo["nameWithOwner"].lower()
            index.setdefault(full.split("/", 1)[1], []).append(full)
    return index


def queries(owner: str, since: date, exclude: list[str]) -> list[str]:
    exclusions = "".join(f" -repo:{repo}" for repo in exclude)
    stamp = since.isoformat()
    return [
        f"user:{owner} is:issue is:open archived:false{exclusions}",
        f"user:{owner} is:pr is:open archived:false{exclusions}",
        f"user:{owner} is:pr is:merged merged:>={stamp}{exclusions}",
        f"user:{owner} is:issue is:closed closed:>={stamp}{exclusions}",
    ]


def collect(run=gh, owners: list[str] | None = None, exclude: list[str] = (), since: date | None = None,
            me: str = "Erik", max_pages: int = DEFAULT_MAX_PAGES) -> GithubResult:
    errors: list[str] = []
    try:
        viewer = run(["api", "user", "--jq", ".login"]).strip()
        owners = list(owners) if owners else discover_owners(run, viewer)
    except GhFailure as problem:
        return GithubResult("github", [], [f"GitHub unavailable: {problem}"])
    items: dict[str, WorkItem] = {}
    for owner in owners:
        for query in queries(owner, since or date.today(), list(exclude)):
            try:
                nodes, truncation = search(run, query, max_pages)
            except GhFailure as problem:
                errors.append(str(problem))
                continue
            if truncation:
                errors.append(truncation)
            for node in nodes:
                item = normalize(node, viewer, me)
                items[item.id] = item
    return GithubResult("github", sorted(items.values(), key=lambda item: item.id), errors,
                        owners=owners, repos=repo_index(run, owners, errors), viewer=viewer)


def lookup(run, keys: list[str], viewer: str | None, me: str = "Erik") -> tuple[list[WorkItem], list[str]]:
    items, errors = [], []
    for key in keys:
        match = REF_KEY.match(key)
        if not match:
            continue
        owner, repo, number = match.groups()
        try:
            record = json.loads(run(["api", f"repos/{owner}/{repo}/issues/{number}"]))
        except (GhFailure, json.JSONDecodeError) as problem:
            errors.append(f"lookup {key} failed: {str(problem)[:200]}")
            continue
        pull = record.get("pull_request") or {}
        is_pull = bool(record.get("pull_request"))
        node = {
            "__typename": "PullRequest" if is_pull else "Issue",
            "number": record.get("number", int(number)),
            "title": record.get("title") or "",
            "url": record.get("html_url"),
            "state": "OPEN" if record.get("state") == "open" else "MERGED" if pull.get("merged_at") else "CLOSED",
            "closedAt": record.get("closed_at"),
            "createdAt": record.get("created_at"),
            "updatedAt": record.get("updated_at"),
            "body": "",
            "isDraft": bool(record.get("draft")),
            "mergedAt": pull.get("merged_at"),
            "repository": {"nameWithOwner": f"{owner}/{repo}"},
            "author": {"login": (record.get("user") or {}).get("login")},
            "assignees": {"nodes": record.get("assignees") or []},
            "labels": {"nodes": record.get("labels") or []},
        }
        item = normalize(node, viewer, me)
        item.evidence.append("looked up because another source links to it")
        items.append(item)
    return items, errors


def check_results(rollup: dict | None) -> tuple[list[str], list[str], bool]:
    contexts = ((rollup or {}).get("contexts") or {}).get("nodes") or []
    failing, pending = [], []
    for context in contexts:
        if not context:
            continue
        if context.get("__typename") == "StatusContext":
            name, state = context.get("context") or "status", context.get("state")
            if state in FAILING_STATES:
                failing.append(name)
            elif state in PENDING_STATES:
                pending.append(name)
            continue
        name = context.get("name") or "check"
        if context.get("status") != "COMPLETED":
            pending.append(name)
        elif context.get("conclusion") in FAILING_CONCLUSIONS:
            failing.append(name)
    return failing, pending, bool(contexts)


def pr_state(key: str, node: dict) -> PrState:
    commits = (node.get("commits") or {}).get("nodes") or []
    commit = ((commits[-1] or {}).get("commit") or {}) if commits else {}
    failing, pending, has_checks = check_results(commit.get("statusCheckRollup"))
    return PrState(
        key=key,
        title=node.get("title") or "",
        url=node.get("url") or "",
        is_draft=bool(node.get("isDraft")),
        mergeable=node.get("mergeable") or "UNKNOWN",
        merge_state=node.get("mergeStateStatus") or "UNKNOWN",
        review_decision=node.get("reviewDecision"),
        failing_checks=failing,
        pending_checks=pending,
        has_checks=has_checks,
        files=[entry["path"] for entry in (node.get("files") or {}).get("nodes") or [] if entry and entry.get("path")],
        bot=is_bot((node.get("author") or {}).get("login")),
        created=parse_day(node.get("createdAt")),
        last_commit=parse_day(commit.get("committedDate")),
    )


def merged_prs(repo: str, connection: dict | None) -> list[MergedPr]:
    return [MergedPr(key=f"{repo}#{node['number']}".lower(), title=node.get("title") or "", url=node.get("url") or "",
                     merged_on=parse_day(node.get("mergedAt")),
                     files=[entry["path"] for entry in (node.get("files") or {}).get("nodes") or [] if entry and entry.get("path")])
            for node in (connection or {}).get("nodes") or [] if node]


def state_query(repos: dict[str, list[int]], with_merged: bool) -> tuple[str, dict[str, str]]:
    blocks, aliases = [], {}
    for position, (repo, numbers) in enumerate(repos.items()):
        owner, name = repo.split("/", 1)
        alias = f"r{position}"
        aliases[alias] = repo
        pulls = "\n    ".join(f"p{number}: pullRequest(number: {number}) {{ {PR_STATE_FIELDS} }}" for number in numbers)
        merged = f"\n    {RECENT_MERGED_FIELDS}" if with_merged else ""
        blocks.append(f"  {alias}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{\n    {pulls}{merged}\n  }}")
    return "query {\n" + "\n".join(blocks) + "\n}", aliases


def fetch_states(run, keys: list[str], with_merged: bool, states: dict, recent: dict, errors: list[str]) -> None:
    for start in range(0, len(keys), PRS_PER_QUERY):
        fetch_chunk(run, keys[start:start + PRS_PER_QUERY], with_merged, states, recent, errors)


def fetch_chunk(run, chunk: list[str], with_merged: bool, states: dict, recent: dict, errors: list[str]) -> None:
    repos: dict[str, list[int]] = {}
    wanted = {}
    for key in chunk:
        owner, repo, number = REF_KEY.match(key).groups()
        repos.setdefault(f"{owner}/{repo}", []).append(int(number))
        wanted[(f"{owner}/{repo}", int(number))] = key
    query, aliases = state_query(repos, with_merged)
    try:
        payload = json.loads(run(["api", "graphql", "-f", f"query={query}"]))
    except (GhFailure, json.JSONDecodeError) as problem:
        if len(chunk) > 1:
            middle = len(chunk) // 2
            fetch_chunk(run, chunk[:middle], with_merged, states, recent, errors)
            fetch_chunk(run, chunk[middle:], with_merged, states, recent, errors)
        else:
            errors.append(f"PR state query failed for {chunk[0]}: {str(problem)[:300]}")
        return
    if payload.get("errors"):
        errors.append(f"PR state query reported: {payload['errors'][0].get('message')}")
    for alias, repo in aliases.items():
        block = (payload.get("data") or {}).get(alias) or {}
        for number in repos[repo]:
            node = block.get(f"p{number}")
            if node:
                states[wanted[(repo, number)]] = pr_state(wanted[(repo, number)], node)
        if with_merged and "merged" in block:
            recent.setdefault(repo.lower(), []).extend(merged_prs(repo, block["merged"]))


def pr_states(run, keys: list[str], sleep=time.sleep) -> tuple[dict[str, PrState], dict[str, list[MergedPr]], list[str]]:
    keys = [key for key in keys if REF_KEY.match(key)]
    states: dict[str, PrState] = {}
    recent: dict[str, list[MergedPr]] = {}
    errors: list[str] = []
    if not keys:
        return states, recent, errors
    fetch_states(run, keys, True, states, recent, errors)
    unknown = [key for key, state in states.items() if state.mergeable == "UNKNOWN" or state.merge_state == "UNKNOWN"]
    if unknown:
        sleep(UNKNOWN_RETRY_SECONDS)
        fetch_states(run, unknown, False, states, recent, errors)
    return states, recent, errors
