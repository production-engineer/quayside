from dataclasses import dataclass, field, fields
from datetime import date, datetime
from zoneinfo import ZoneInfo

DATE_FIELDS = ("created", "last_activity")
HOME_ZONE = ZoneInfo("America/Anchorage")


def parse_day(value) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(HOME_ZONE).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not text.isascii():
        return None
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(HOME_ZONE).date() if moment.tzinfo else moment.date()


@dataclass
class WorkItem:
    source: str
    id: str
    title: str
    project: str = ""
    kind: str = ""
    status: str = "unknown"
    owner: str | None = None
    created: date | None = None
    last_activity: date | None = None
    links: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    blocked_on: str | None = None
    waiting_on_erik: list[str] = field(default_factory=list)
    critical_hints: list[str] = field(default_factory=list)
    priority: str | None = None
    done_hints: list[str] = field(default_factory=list)
    closes: list[str] = field(default_factory=list)
    claimed_by: str | None = None
    evidence: list[str] = field(default_factory=list)

    @property
    def github_key(self) -> str | None:
        return self.id.removeprefix("github:") if self.source == "github" else None

    def to_dict(self) -> dict:
        record = {}
        for spec in fields(self):
            value = getattr(self, spec.name)
            record[spec.name] = value.isoformat() if isinstance(value, date) else value
        return record

    @classmethod
    def from_dict(cls, record: dict) -> "WorkItem":
        known = {spec.name for spec in fields(cls)}
        values = {key: value for key, value in record.items() if key in known}
        for name in DATE_FIELDS:
            values[name] = parse_day(values.get(name))
        return cls(**values)


@dataclass
class SourceResult:
    name: str
    items: list[WorkItem]
    errors: list[str]


def idle_days(item: WorkItem, today: date) -> int | None:
    if item.last_activity is None:
        return None
    return max(0, (today - item.last_activity).days)
