import logging
import os
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from api.models import Feedback, Project, Status, Task, User, new_id

logger = logging.getLogger(__name__)

MONGO_HOST = "quayside-cluster.ry3otj1.mongodb.net"
MONGO_DB = "quayside"
PHASES = ("users", "projects", "tasks", "feedback")


class AtlasUnreachable(CommandError):
    pass


class SchemaNotMigrated(CommandError):
    pass


class VerificationFailed(CommandError):
    pass


@dataclass
class Counts:
    source: int = 0
    written: int = 0
    skipped: int = 0
    reconciled: int = 0


@dataclass
class Report:
    users: Counts = field(default_factory=Counts)
    projects: Counts = field(default_factory=Counts)
    statuses: Counts = field(default_factory=Counts)
    tasks: Counts = field(default_factory=Counts)
    feedback: Counts = field(default_factory=Counts)

    synthesized_emails: int = 0
    deduped_emails: int = 0
    orphan_tasks: int = 0
    dropped_statuses: int = 0
    detached_parents: int = 0
    orphan_feedback: int = 0
    detached_feedback_task: int = 0

    dry_run: bool = False
    phases_run: tuple = PHASES

    def table(self) -> str:
        header = f"{'entity':<10}{'source':>8}{'written':>9}{'skipped':>9}{'reconciled':>12}"
        rows = [header, "-" * len(header)]
        for name in ("users", "projects", "statuses", "tasks", "feedback"):
            c = getattr(self, name)
            rows.append(
                f"{name:<10}{c.source:>8}{c.written:>9}{c.skipped:>9}{c.reconciled:>12}"
            )
        return "\n".join(rows)


def _oid(value) -> str:
    return str(value)


def _date(value):
    return value if value not in ("", None) else None


def _as_list(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def _assert_schema_migrated():
    expected = {m._meta.db_table for m in (User, Project, Status, Task, Feedback)}
    existing = set(connection.introspection.table_names())
    missing = expected - existing
    if missing:
        raise SchemaNotMigrated(
            f"Destination tables missing: {sorted(missing)}. Run `migrate` first."
        )


def _coerce_emails(docs, report):
    """Return {user_id: email} with missing/duplicate emails synthesized.

    docs is the ordered list of source user docs; first occurrence of a
    duplicate email wins, the rest get a synthesized placeholder.
    """
    resolved = {}
    seen = set()
    for doc in docs:
        uid = _oid(doc["_id"])
        raw = doc.get("email")
        email = raw.strip() if isinstance(raw, str) else ""
        if not email:
            resolved[uid] = f"placeholder+{uid}@quayside.invalid"
            report.synthesized_emails += 1
            continue
        key = email.lower()
        if key in seen:
            resolved[uid] = f"placeholder+{uid}@quayside.invalid"
            report.deduped_emails += 1
            continue
        seen.add(key)
        resolved[uid] = email
    return resolved


def _upsert(model, pk, defaults, dry_run):
    if dry_run:
        return
    model.objects.update_or_create(id=pk, defaults=defaults)


def _migrate_users(mongo_db, report, dry_run):
    docs = list(mongo_db["User"].find())
    report.users.source = len(docs)
    emails = _coerce_emails(docs, report)
    with transaction.atomic():
        for doc in docs:
            uid = _oid(doc["_id"])
            _upsert(
                User,
                uid,
                {
                    "email": emails[uid],
                    "username": doc.get("username") or "",
                    "firstName": doc.get("firstName") or "",
                    "lastName": doc.get("lastName") or "",
                    "teamIDs": [_oid(x) for x in _as_list(doc.get("teamIDs"))],
                    "apiKey": doc.get("apiKey"),
                },
                dry_run,
            )
            report.users.written += 1
    logger.info("users phase: source=%d written=%d", report.users.source, report.users.written)


def _migrate_projects(mongo_db, report, dry_run):
    docs = list(mongo_db["Project"].find())
    report.projects.source = len(docs)
    with transaction.atomic():
        for doc in docs:
            pid = _oid(doc["_id"])
            _upsert(
                Project,
                pid,
                {
                    "name": doc.get("name") or "",
                    "description": doc.get("description"),
                    "startDate": _date(doc.get("startDate")),
                    "endDate": _date(doc.get("endDate")),
                    "budget": doc.get("budget") or "",
                    "completionStatus": doc.get("completionStatus") or "",
                    "types": _as_list(doc.get("types")),
                    "objectives": _as_list(doc.get("objectives")),
                    "assumptions": _as_list(doc.get("assumptions")),
                    "scopesIncluded": _as_list(doc.get("scopesIncluded")),
                    "scopesExcluded": _as_list(doc.get("scopesExcluded")),
                    "risks": _as_list(doc.get("risks")),
                    "sponsors": _as_list(doc.get("sponsors")),
                    "completionRequirements": _as_list(doc.get("completionRequirements")),
                    "qualityAssurance": _as_list(doc.get("qualityAssurance")),
                    "KPIs": _as_list(doc.get("KPIs")),
                    "informationLinks": _as_list(doc.get("informationLinks")),
                    "userIDs": [_oid(x) for x in _as_list(doc.get("userIDs"))],
                    "projectManagerIDs": [_oid(x) for x in _as_list(doc.get("projectManagerIDs"))],
                    "contributorIDs": [_oid(x) for x in _as_list(doc.get("contributorIDs"))],
                    "otherProjectDependencies": [
                        _oid(x) for x in _as_list(doc.get("otherProjectDependencies"))
                    ],
                    "teams": [_oid(x) for x in _as_list(doc.get("teams"))],
                },
                dry_run,
            )
            report.projects.written += 1

            for entry in _as_list(doc.get("taskStatuses")):
                raw_id = entry.get("id")
                sid = _oid(raw_id) if raw_id not in (None, "") else new_id()
                _upsert(
                    Status,
                    sid,
                    {
                        "project_id": pid,
                        "name": entry.get("name") or "",
                        "color": entry.get("color") or "",
                        "order": entry.get("order") or 0,
                    },
                    dry_run,
                )
                report.statuses.source += 1
                report.statuses.written += 1
    logger.info(
        "projects phase: source=%d written=%d statuses=%d",
        report.projects.source,
        report.projects.written,
        report.statuses.written,
    )


def _migrate_tasks(mongo_db, report, project_ids, status_ids):
    docs = list(mongo_db["Task"].find())
    report.tasks.source = len(docs)
    dry_run = report.dry_run
    written_ids = set()
    with transaction.atomic():
        for doc in docs:
            tid = _oid(doc["_id"])
            project_ref = doc.get("projectID")
            project_id = _oid(project_ref) if project_ref not in (None, "") else None
            if project_id is None or project_id not in project_ids:
                report.orphan_tasks += 1
                report.tasks.skipped += 1
                continue

            status_ref = doc.get("statusId")
            status_id = _oid(status_ref) if status_ref not in (None, "") else None
            if status_id is not None and status_id not in status_ids:
                status_id = None
                report.dropped_statuses += 1
                report.tasks.reconciled += 1

            _upsert(
                Task,
                tid,
                {
                    "projectID_id": project_id,
                    "statusId_id": status_id,
                    "parentTaskID_id": None,
                    "name": doc.get("name") or "",
                    "description": doc.get("description"),
                    "startDate": _date(doc.get("startDate")),
                    "endDate": _date(doc.get("endDate")),
                    "priority": doc.get("priority"),
                    "durationMinutes": doc.get("durationMinutes") or 0,
                    "objectives": _as_list(doc.get("objectives")),
                    "scopesIncluded": _as_list(doc.get("scopesIncluded")),
                    "scopesExcluded": _as_list(doc.get("scopesExcluded")),
                    "contributorIDs": [_oid(x) for x in _as_list(doc.get("contributorIDs"))],
                    "otherProjectDependencies": [
                        _oid(x) for x in _as_list(doc.get("otherProjectDependencies"))
                    ],
                    "otherTaskDependencies": [
                        _oid(x) for x in _as_list(doc.get("otherTaskDependencies"))
                    ],
                },
                dry_run,
            )
            written_ids.add(tid)
            report.tasks.written += 1

        for doc in docs:
            parent_ref = doc.get("parentTaskID")
            if parent_ref in (None, ""):
                continue
            tid = _oid(doc["_id"])
            parent_id = _oid(parent_ref)
            if tid in written_ids and parent_id in written_ids:
                if not dry_run:
                    Task.objects.filter(id=tid).update(parentTaskID_id=parent_id)
                report.tasks.reconciled += 1
            elif tid in written_ids:
                report.detached_parents += 1
                report.tasks.reconciled += 1
    logger.info(
        "tasks phase: source=%d written=%d skipped=%d",
        report.tasks.source,
        report.tasks.written,
        report.tasks.skipped,
    )


def _migrate_feedback(mongo_db, report, user_ids, project_ids, task_ids):
    docs = list(mongo_db["Feedback"].find())
    report.feedback.source = len(docs)
    dry_run = report.dry_run
    with transaction.atomic():
        for doc in docs:
            fid = _oid(doc["_id"])
            user_ref = doc.get("userID")
            project_ref = doc.get("projectID")
            user_id = _oid(user_ref) if user_ref not in (None, "") else None
            project_id = _oid(project_ref) if project_ref not in (None, "") else None
            if (
                user_id is None
                or project_id is None
                or user_id not in user_ids
                or project_id not in project_ids
            ):
                report.orphan_feedback += 1
                report.feedback.skipped += 1
                continue

            task_ref = doc.get("taskID")
            task_id = _oid(task_ref) if task_ref not in (None, "") else None
            if task_id is not None and task_id not in task_ids:
                task_id = None
                report.detached_feedback_task += 1
                report.feedback.reconciled += 1

            defaults = {
                "userID_id": user_id,
                "projectID_id": project_id,
                "taskID_id": task_id,
                "mood": doc.get("mood"),
                "explanation": doc.get("explanation"),
            }
            if doc.get("dateCreated") not in (None, ""):
                defaults["dateCreated"] = doc.get("dateCreated")
            _upsert(Feedback, fid, defaults, dry_run)
            report.feedback.written += 1
    logger.info(
        "feedback phase: source=%d written=%d skipped=%d",
        report.feedback.source,
        report.feedback.written,
        report.feedback.skipped,
    )


def _verify(report):
    for name in report.phases_run:
        c = getattr(report, name)
        if c.source != c.written + c.skipped:
            raise VerificationFailed(
                f"{name}: source={c.source} but written={c.written} + skipped={c.skipped}"
            )


def run_migration(mongo_db, *, dry_run=False, only=None) -> Report:
    _assert_schema_migrated()

    selected = tuple(only) if only else PHASES
    report = Report(dry_run=dry_run, phases_run=selected)

    project_ids = {_oid(d["_id"]) for d in mongo_db["Project"].find({}, {"_id": 1})}
    status_ids = set()
    for doc in mongo_db["Project"].find({}, {"taskStatuses": 1}):
        for entry in _as_list(doc.get("taskStatuses")):
            raw_id = entry.get("id")
            if raw_id not in (None, ""):
                status_ids.add(_oid(raw_id))
    user_ids = {_oid(d["_id"]) for d in mongo_db["User"].find({}, {"_id": 1})}
    task_ids = {_oid(d["_id"]) for d in mongo_db["Task"].find({}, {"_id": 1})}

    if "users" in selected:
        _migrate_users(mongo_db, report, dry_run)
    if "projects" in selected:
        _migrate_projects(mongo_db, report, dry_run)
    if "tasks" in selected:
        _migrate_tasks(mongo_db, report, project_ids, status_ids)
    if "feedback" in selected:
        _migrate_feedback(mongo_db, report, user_ids, project_ids, task_ids)

    _verify(report)
    return report


def _build_client():
    username = os.getenv("MONGO_USERNAME")
    password = os.getenv("MONGO_PASSWORD")
    if not username or not password:
        raise AtlasUnreachable("MONGO_USERNAME and MONGO_PASSWORD must be set.")
    import pymongo
    from pymongo.errors import PyMongoError

    uri = (
        f"mongodb+srv://{quote_plus(username)}:{quote_plus(password)}"
        f"@{MONGO_HOST}/?retryWrites=true&w=majority"
    )
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
    except PyMongoError as exc:
        raise AtlasUnreachable(f"Could not reach Atlas: {exc}") from exc
    return client


class Command(BaseCommand):
    help = "Migrate quayside data from MongoDB Atlas into PostgreSQL (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read, reconcile, and report without writing to Postgres.",
        )
        parser.add_argument(
            "--only",
            default="",
            help="Comma-separated subset of phases: users,projects,tasks,feedback.",
        )

    def handle(self, *args, **options):
        only = [p.strip() for p in options["only"].split(",") if p.strip()]
        unknown = [p for p in only if p not in PHASES]
        if unknown:
            raise CommandError(f"Unknown phase(s): {unknown}. Valid: {list(PHASES)}")

        client = _build_client()
        try:
            report = run_migration(
                client[MONGO_DB], dry_run=options["dry_run"], only=only or None
            )
        finally:
            client.close()

        self.stdout.write("")
        self.stdout.write("Reconciliation:")
        self.stdout.write(report.table())
        if report.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: no rows were written."))
        else:
            self.stdout.write(self.style.SUCCESS("Migration complete."))
