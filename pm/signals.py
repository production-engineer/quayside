import re
from datetime import date

from pm.model import parse_day

SNIPPET_RADIUS = 60

GITHUB_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/(?:pull|issues)/(\d+)")
QUALIFIED_REF = re.compile(r"(?<![\w/.-])([A-Za-z0-9][\w.-]*)/([\w.-]+?)(?:#| (?:PR|issue|ticket) #)(\d+)\b")
SHORT_REF = re.compile(r"(?<![\w/.#-])([A-Za-z][\w.-]*)#(\d+)\b")
HTTP_LINK = re.compile(r"https?://[^\s)<>\]\"'`]+")
ISO_DAY = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

CRITICAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (r"\btop of (?:the )?queue\b", r"\bnext thing to pick up\b", r"\bcritical path\b",
                    r"\bblocks? (?:the )?MVP\b")
]

AGENT_MARK = re.compile(r"Generated with \[?Claude Code|Co-Authored-By:\s*Claude\b", re.IGNORECASE)
DONE_HEADING = re.compile(r"\b(?:done|shipped|landed|completed?)\b", re.IGNORECASE)
TRACKING_HEADING = re.compile(r"\b(?:status|tracked|tracking|progress|next)\b", re.IGNORECASE)
CHECKED_LINE = re.compile(r"^\s*[-*]\s*\[[xX]\]")
UNCHECKED_LINE = re.compile(r"^\s*[-*]\s*\[ \]")
DONE_BANNER = re.compile(r"^\s*>\s*\*\*\s*done\b", re.IGNORECASE)
BANNER = re.compile(r"^\s*>\s*\*\*")
DONE_LINE = re.compile(r"^\s*(?:[-*]\s*)?\**(?:done|shipped)\b", re.IGNORECASE)
TRACKING_LINE = re.compile(r"^\s*(?:[-*]\s*)?\**(?:status|tracked)\b", re.IGNORECASE)
HEADING_LINE = re.compile(r"^#{1,6}\s")
COMPLETION_WORD = re.compile(r"\b(?:merged|closed|fixed|resolved|shipped|landed)\b", re.IGNORECASE)
GRANTED_PREFIX = re.compile(r"\b(?:with|from|after)\s+$", re.IGNORECASE)

BLOCKED_PATTERN = re.compile(r"\b(?:blocked (?:on|by)|depends on) ([^.;\n]{2,80})", re.IGNORECASE)


def wait_patterns(name: str) -> list[re.Pattern]:
    who = re.escape(name)
    return [
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            rf"\bwait(?:s|ing)? (?:on|for) {who}\b",
            rf"\bneeds? {who}\b",
            rf"\bblocked (?:on|by) {who}\b",
            rf"\b(?:ask|tell) {who}\b",
            rf"\b(?:decide|confirm|check) with {who}\b",
            rf"\b{who} (?:has|needs) to\b",
            rf"\b{who}(?:'s)? (?:call|decision|review|approval|sign-off)\b",
            rf"\b{who} (?:confirms|decides|approves|reviews)\b",
            rf"\b{who}'s (?:in-session )?go (?:at|before|on)\b",
        )
    ]


def snippet(text: str, match: re.Match) -> str:
    start = max(0, match.start() - SNIPPET_RADIUS)
    end = min(len(text), match.end() + SNIPPET_RADIUS)
    words = text[start:end].split()
    if start > 0 and not text[start - 1].isspace():
        words = words[1:]
    if end < len(text) and not text[end].isspace():
        words = words[:-1]
    return " ".join(words)


def granted(text: str, match: re.Match) -> bool:
    return bool(GRANTED_PREFIX.search(text[max(0, match.start() - 8):match.start()]))


def matches(text: str, patterns: list[re.Pattern]) -> list[str]:
    hits = sorted((match for pattern in patterns for match in pattern.finditer(text) if not granted(text, match)),
                  key=lambda match: match.start())
    found, reach = [], -1
    for match in hits:
        if match.start() > reach:
            found.append(snippet(text, match))
        reach = max(reach, match.end())
    return found


def find_refs(text: str) -> list[str]:
    refs = set()
    for owner, repo, number in GITHUB_URL.findall(text):
        refs.add(f"{owner}/{repo}#{number}".lower())
    for owner, repo, number in QUALIFIED_REF.findall(text):
        refs.add(f"{owner}/{repo}#{number}".lower())
    for repo, number in SHORT_REF.findall(text):
        refs.add(f"{repo}#{number}".lower())
    return sorted(refs)


def find_links(text: str) -> list[str]:
    links = []
    for match in HTTP_LINK.finditer(text):
        link = match.group(0).rstrip(".,;:!?")
        if link not in links:
            links.append(link)
    return links


def erik_waits(text: str, name: str = "Erik") -> list[str]:
    return matches(text, wait_patterns(name))


def critical_hints(text: str) -> list[str]:
    return matches(text, CRITICAL_PATTERNS)


def blocked_on(text: str) -> str | None:
    for match in BLOCKED_PATTERN.finditer(text):
        if text[max(0, match.start() - 4):match.start()].lower() == "not ":
            continue
        return match.group(1).strip()
    return None


def agent_marked(text: str) -> bool:
    return bool(AGENT_MARK.search(text))


def line_context(line: str, section: str | None) -> str | None:
    if CHECKED_LINE.match(line) or DONE_BANNER.match(line) or DONE_LINE.match(line):
        return "done"
    if UNCHECKED_LINE.match(line) or BANNER.match(line) or TRACKING_LINE.match(line):
        return "tracking"
    return section


def status_contexts(text: str) -> tuple[str, str]:
    tracking, done, section = [], [], None
    for line in text.splitlines():
        if HEADING_LINE.match(line):
            section = "done" if DONE_HEADING.search(line) else "tracking" if TRACKING_HEADING.search(line) else None
            continue
        context = line_context(line, section)
        if context == "done" and (CHECKED_LINE.match(line) or DONE_BANNER.match(line) or COMPLETION_WORD.search(line)):
            done.append(line)
        elif context == "tracking":
            tracking.append(line)
    return "\n".join(tracking), "\n".join(done)


def dates_in(text: str) -> list[date]:
    return [day for day in (parse_day(token) for token in ISO_DAY.findall(text)) if day]
