# Quayside MongoDB → PostgreSQL Migration Specification

Status: Draft v1

ADR: [docs/decisions/2026-06-24-postgres-django-orm.md](../decisions/2026-06-24-postgres-django-orm.md)

Purpose: Replace quayside's MongoDB/MongoEngine persistence with PostgreSQL and the native Django ORM, preserving the existing API contract, auth flow, and live data.

---

## 1. Problem Statement

Quayside persists all domain data in MongoDB Atlas via MongoEngine and `rest_framework_mongoengine`. This specification defines how to move that persistence to PostgreSQL using Django's native ORM, with no loss of data and no change to the external API or authentication contract.

It solves these operational problems:

- **Boot coupling to Atlas.** The app opens an Atlas connection at startup (`api/apps.py:ready`), so any host outside the Atlas IP allowlist (including CI) cannot boot. This blocks issue #5.
- **No real test database.** Without a Django-managed DB, tests cannot use Django's transactional test harness; the current API tests are unrunnable. This blocks issue #6.
- **Schemaless drift.** `strict=False` on every model permits unknown fields and mixed object/dict access; there is no enforced schema.
- **Stack divergence.** The rest of the stack is PostgreSQL; MongoEngine isolates quayside from shared tooling, hosting, and skills.

### Important boundary

This migration is **not** responsible for:

- Redesigning the domain model or the REST API shape. Field names, endpoint paths, request/response JSON, and status codes are preserved.
- Adopting Django's auth framework, sessions, or password login. The custom JWT-in-cookie + encrypted `apiKey` flow is preserved exactly.
- Reimplementing feature PRs that were written against Mongo (notably the Kanban customization PR #2). Those are reimplemented on the new stack *after* this migration lands.
- Normalizing list-membership relations (userIDs, teamIDs, contributor lists) into join tables. These are preserved as Postgres array columns with identical membership semantics (Section 4.6).

---

## 2. Goals and Non-Goals

### 2.1 Goals

- Quayside runs on PostgreSQL via the Django ORM; `DATABASES["default"]` is a real Postgres connection driven by `DATABASE_URL`.
- All four domain entities (`User`, `Project`, `Task`, `Feedback`) plus the new `Status` table are native Django models, with the embedded Mongo `Status` list promoted to a related table.
- Primary keys are the original 24-hex Mongo ObjectId strings, so all cross-references and all existing `apiToken` cookies / stored `apiKey` JWTs remain valid.
- Live Atlas data (~105 users, ~423 projects, ~1171+ tasks, plus feedback) is migrated with every cross-reference intact, by an idempotent, verifiable ETL command.
- All 7 DRF views and their serializers operate on the Django ORM; `rest_framework_mongoengine` is removed.
- `app/templatetags/whatsnext.py` querysets are ported to the ORM; `api/progress.py` is unchanged.
- The full test suite is green as real Django tests, closing #5 and #6.
- `mongoengine`, `pymongo`, `dnspython`, and `rest_framework_mongoengine` are removed from `requirements.txt`, and the file is hash-pinned (`--require-hashes`), closing the deferred item of #4.

### 2.2 Non-Goals

- No change to API endpoint URLs, JSON field names, or status codes.
- No change to the auth mechanism (JWT cookie + encrypted apiKey).
- No conversion of array-membership fields to M2M join tables.
- No new features. Kanban PR #2 is explicitly deferred to a follow-up.
- No data backfill, cleanup, or enrichment beyond what is required to satisfy referential integrity during ETL (orphans are reconciled and reported, not enriched).

---

## 3. System Overview

### 3.1 Main components

1. `models` (`api/models.py`)
   - Native Django models with ObjectId `CharField` PKs.
   - Postgres `ArrayField` for list-of-ObjectId and list-of-string fields.
   - `Status` as a related table (FK to `Project`, `related_name="taskStatuses"`).

2. `serializers` (`api/serializers.py`)
   - `rest_framework.serializers.ModelSerializer` subclasses.
   - `ProjectSerializer` keeps a nested writable `taskStatuses` (StatusSerializer), reproducing today's create/update behavior on the related table.

3. `views` (`api/views/v1/*.py`)
   - Same 7 `APIView` classes, same routes, same auth decorator.
   - All MongoEngine queries replaced with ORM queries (Section 6).

4. `etl` (`api/management/commands/migrate_mongo.py`)
   - One-shot, idempotent management command. Reads Atlas via PyMongo, writes Postgres via the ORM, preserves ObjectId PKs, reconciles orphans, verifies counts.

5. `whatsnext` tag (`app/templatetags/whatsnext.py`)
   - Querysets ported to ORM; record-building adjusted for FK `_id` accessors. `api/progress.py` consumes records and is untouched.

6. `config` (`quayside/settings.py`, `api/apps.py`, `.env`)
   - `DATABASES["default"]` populated from `DATABASE_URL`. The Atlas `connect_database()` startup hook is removed.

### 3.2 Abstraction layers

- **Data layer:** models + migrations. Source of truth for schema.
- **Serialization layer:** serializers. Translate models ↔ JSON; own the nested-status logic.
- **View layer:** input parsing, auth, calling the data layer, returning responses. No business logic beyond what exists today (parity port).
- **Pure domain layer:** `api/progress.py`. DB-agnostic; unchanged.
- **Migration layer:** the ETL command. Lives outside the request path; run once at cutover (and re-runnable).

### 3.3 External dependencies

- **PostgreSQL** (dev: local; prod: Neon) via `psycopg[binary]` + `dj-database-url`.
- **MongoDB Atlas** — read-only, during ETL only, via `pymongo`. Removed from the runtime after cutover.
- **OpenAI** (`openai==1.12.0`, `CHATGPT_API_KEY`) — unchanged; used by `generatedTasks`.
- **JWT/Fernet** (`PyJWT`, `cryptography`) — unchanged; the auth utilities in `api/utils.py` are DB-agnostic and untouched.

---

## 4. Core Domain Model

All models live in `api/models.py`. All PKs are the original ObjectId string.

### 4.1 Shared conventions

- **Primary key.** Every model declares:
  ```python
  id = models.CharField(primary_key=True, max_length=24, default=new_id, editable=False)
  ```
  where `new_id` returns a fresh 24-hex string for rows created via the API:
  ```python
  import secrets
  def new_id() -> str:
      return secrets.token_hex(12)  # 24 hex chars, ObjectId-shaped, no bson dependency
  ```
  The ETL supplies the real ObjectId and overrides the default (Section 5).

- **Field naming.** Model field names match the existing Mongo/JSON names exactly (`projectID`, `parentTaskID`, `statusId`, `userIDs`, `firstName`, …) so that `ModelSerializer(fields="__all__")` produces byte-identical JSON keys. This intentionally violates Python snake_case convention to preserve the API contract; it is a deliberate, documented exception.

- **FK id access.** A ForeignKey named `projectID` exposes the related object as `task.projectID` and the raw id string as `task.projectID_id`. Code that needs the ObjectId string (record building, comparisons) uses the `_id` accessor.

- **Timestamps.** Where Mongo used `datetime.now(timezone.utc)` as a field default (an import-time-evaluated bug in `Feedback.dateCreated`), the Django model uses the callable `django.utils.timezone.now`, fixing the bug.

### 4.2 `User`

Represents an account. Auth identity; referenced by ObjectId across projects/tasks/feedback.

Fields:

- `id` (CharField PK, 24) — ObjectId.
- `email` (EmailField, `unique=True`) — required, unique. ETL must resolve duplicates/missing (Section 5.4).
- `username` (CharField, `blank=True`, `default=""`) — not unique (matches today; uniqueness "messes up updates" per the Mongo comment).
- `firstName` (CharField, `blank=True`, `default=""`).
- `lastName` (CharField, `blank=True`, `default=""`).
- `teamIDs` (ArrayField of CharField(24), `default=list`, `blank=True`) — ObjectId list.
- `apiKey` (TextField, `null=True`, `blank=True`) — Fernet-encrypted JWT; can be long, so TextField not CharField.

Indexes: `email` (unique, implicit).

### 4.3 `Project`

Represents a project. Owns an ordered list of `Status` rows; referenced by tasks and feedback.

Scalar fields:

- `id` (CharField PK, 24).
- `name` (CharField, `blank=True`, `default=""`).
- `description` (TextField, `null=True`, `blank=True`).
- `startDate` (DateField, `null=True`, `blank=True`).
- `endDate` (DateField, `null=True`, `blank=True`).
- `budget` (CharField, `blank=True`, `default=""`).
- `completionStatus` (CharField, `blank=True`, `default=""`).

ObjectId-array fields (`ArrayField(CharField(24), default=list, blank=True)`):

- `userIDs`, `projectManagerIDs`, `contributorIDs`, `otherProjectDependencies`, `teams`.

String-array fields (`ArrayField(TextField(), default=list, blank=True)`):

- `types`, `objectives`, `assumptions`, `scopesIncluded`, `scopesExcluded`, `risks`, `sponsors`, `completionRequirements`, `qualityAssurance`, `KPIs`, `informationLinks`.

Relations:

- `taskStatuses` — reverse accessor from `Status.project` (FK with `related_name="taskStatuses"`). Ordered by `Status.order`.

Model behavior:

- `default_task_statuses()` — module/class helper returning the three default status dicts (Todo `323232` o1, In-Progress `EFA610` o2, Done `01796E` o3), used when a project is created without statuses (preserves current `create_default_task_statuses`).

### 4.4 `Status`

Represents one Kanban column for a project. **New table** — promoted from the embedded `Project.Status` list.

Fields:

- `id` (CharField PK, 24) — ObjectId (preserved from the embedded doc's id so `Task.statusId` FK resolves 1:1).
- `project` (FK → `Project`, `on_delete=CASCADE`, `related_name="taskStatuses"`).
- `name` (CharField, required).
- `color` (CharField, required) — hex color, no `#`.
- `order` (IntegerField, required) — column order on the board.

Constraints:

- Uniqueness of status ids is now guaranteed by the PK; the old `Project.clean()` duplicate-id check is dropped as redundant.

Ordering: default `Meta.ordering = ["order"]`.

### 4.5 `Task`

Represents a task in a project's tree.

Scalar fields:

- `id` (CharField PK, 24).
- `name` (CharField, `blank=True`, `default=""`).
- `description` (TextField, `null=True`, `blank=True`).
- `startDate` (DateField, `null=True`, `blank=True`).
- `endDate` (DateField, `null=True`, `blank=True`).
- `priority` (IntegerField, `null=True`, `blank=True`) — within-column order.
- `durationMinutes` (IntegerField, `default=0`) — Mongo declared `null=False`; ETL defaults missing values to 0.

Foreign keys:

- `projectID` (FK → `Project`, `on_delete=CASCADE`) — owning project. Cascade replaces the manual "delete tasks when project deleted" logic in `ProjectsAPIView`.
- `parentTaskID` (FK → `self`, `null=True`, `blank=True`, `on_delete=CASCADE`) — parent in the task tree. Cascade replaces the recursive `deleteAllChildren` helper.
- `statusId` (FK → `Status`, `null=True`, `blank=True`, `on_delete=SET_NULL`) — current column. SET_NULL so deleting a status detaches tasks rather than deleting them (statuses view reassigns explicitly).

ObjectId-array fields (`ArrayField(CharField(24), default=list, blank=True)`):

- `contributorIDs`, `otherProjectDependencies`, `otherTaskDependencies`.

String-array fields (`ArrayField(TextField(), default=list, blank=True)`):

- `objectives`, `scopesIncluded`, `scopesExcluded`.

Indexes: `projectID`, `parentTaskID`, `statusId` (FK indexes, implicit).

### 4.6 `Feedback`

Represents a mood/explanation datapoint.

Fields:

- `id` (CharField PK, 24).
- `userID` (FK → `User`, `on_delete=CASCADE`) — required.
- `projectID` (FK → `Project`, `on_delete=CASCADE`) — required.
- `taskID` (FK → `Task`, `null=True`, `blank=True`, `on_delete=SET_NULL`).
- `dateCreated` (DateTimeField, `default=timezone.now`).
- `mood` (IntegerField, `null=True`, `blank=True`).
- `explanation` (TextField, `null=True`, `blank=True`).

### 4.7 Array-membership semantics (normalization rule)

Mongo list-membership filters port to Postgres `ArrayField` lookups as follows, and **every** ported query must use these forms:

| MongoEngine | Meaning | Django ORM |
|---|---|---|
| `.filter(userIDs=uid)` | uid is in the list | `.filter(userIDs__contains=[uid])` |
| `.filter(userIDs__all=lst)` | all of lst are in the list | `.filter(userIDs__contains=lst)` |
| `ObjectId(uid) in project["userIDs"]` (in-memory) | membership check | `uid in project.userIDs` (plain string compare; PKs are strings) |

All array elements are stored as plain strings; there is no ObjectId type at rest, so comparisons are ordinary string equality.

---

## 5. ETL Subsystem

`api/management/commands/migrate_mongo.py` — `python manage.py migrate_mongo`.

### 5.1 Discovery / inputs

- Source: MongoDB Atlas, read via `pymongo` using `MONGO_USERNAME` / `MONGO_PASSWORD` from `.env` (the same credentials `api/apps.py` used). Connection is read-only by convention; the command never writes to Mongo.
- Destination: the Django `default` Postgres database. The command runs after `migrate` has created the schema.
- Collections read: `User`, `Project`, `Task`, `Feedback` (the uppercase collection names from the Mongo `meta`).

### 5.2 Behavioral contract (ordered phases)

The command runs phases in dependency order so FK targets exist before referrers. Each phase prints a start line, a per-N progress counter, and a summary (`created`, `updated`, `skipped`, `reconciled`).

1. **Users.** For each Mongo user doc: `User.objects.update_or_create(id=str(_id), defaults={...})`. Coerce missing `email`/`username` per Section 5.4.
2. **Projects + Statuses.** For each project doc:
   - Upsert the `Project` (scalars + array fields; `_id` → `id`).
   - For each embedded `taskStatuses` entry: `Status.objects.update_or_create(id=str(status._id or generated), defaults={project, name, color, order})`. Preserve the embedded id so tasks resolve. If an embedded status lacks an id (legacy data), synthesize one with `new_id()` and record the synthesized mapping for that project (used in phase 3 fallback).
3. **Tasks.** For each task doc, in two passes to satisfy the self-FK:
   - Pass A: upsert every task with `parentTaskID=None`, resolving `projectID` and `statusId` (Section 5.3).
   - Pass B: set `parentTaskID` where the parent now exists.
4. **Feedback.** Upsert each feedback row, resolving FKs (Section 5.3).
5. **Verify.** Compare source vs destination counts per entity; print a reconciliation table; exit non-zero if any *unexplained* discrepancy exists (skips that were logged as orphan reconciliations are "explained").

### 5.3 Cross-reference resolution and orphan policy

Because Postgres enforces FKs that Mongo did not, the ETL must reconcile dangling references rather than fail:

| Reference | If target missing |
|---|---|
| `Task.projectID` | **Skip the task**, record in `orphan_tasks` report. A task with no project is meaningless. |
| `Task.parentTaskID` | **Detach** (set null), record in `detached_parents`. |
| `Task.statusId` | **Detach** (set null), record in `dropped_statuses`. |
| `Feedback.userID` or `Feedback.projectID` | **Skip the feedback**, record in `orphan_feedback`. |
| `Feedback.taskID` | **Detach** (set null), record in `detached_feedback_task`. |
| Array fields (`userIDs`, `teamIDs`, contributor lists, dependency lists) | **Copy as-is.** Not FK-enforced; matches Mongo behavior. No reconciliation. |

All reconciliations are counted and printed in the phase 5 report so the operator sees exactly what bad data existed.

### 5.4 User email coercion

`User.email` is `unique=True, required`. Mongo data may contain missing or duplicate emails. Policy:

- Missing/blank email → synthesize `placeholder+<id>@quayside.invalid` (the `.invalid` TLD is reserved and unroutable), record in `synthesized_emails`. This preserves the user row (and their auth identity / projects) without inventing a real address.
- Duplicate email → keep the first by `_id` order, synthesize as above for the rest, record in `deduped_emails`.

### 5.5 Idempotency and recovery

- Every write is `update_or_create` keyed on `id`, so re-running converges to the same state.
- Each phase is wrapped in its own `transaction.atomic()` so a mid-phase crash rolls back that phase only; completed earlier phases persist and a re-run resumes cleanly.
- The command accepts `--dry-run` (read + reconcile + report, no writes) and `--only={users,projects,tasks,feedback}` for targeted re-runs.

### 5.6 Named errors

- `AtlasUnreachable` — Mongo connection fails. Abort before any write; instruct the operator to check credentials/allowlist. (Read-only; safe to retry.)
- `SchemaNotMigrated` — a destination table is missing. Abort; instruct to run `migrate` first.
- `VerificationFailed` — phase 5 finds an unexplained count gap. Exit non-zero with the per-entity diff. Does not roll back (data is already written); signals investigation.

---

## 6. View / Serializer Port

Parity rewrite. Same classes, routes, auth, and response shapes; only the persistence calls change. The full inventory of MongoEngine call sites is in the implementation notes; the rules below govern every conversion.

### 6.1 Serializers (`api/serializers.py`)

- Base class `rest_framework_mongoengine.serializers.DocumentSerializer` → `rest_framework.serializers.ModelSerializer`.
- `StatusSerializer`: `ModelSerializer` over `Status`, fields `id, name, color, order` (exclude `project`; it is set from the parent).
- `ProjectSerializer.taskStatuses = StatusSerializer(many=True, required=False)`. Custom `create`/`update` rewritten:
  - `create`: create the `Project`, then create one `Status` row per entry with `project=instance`. If no entries given, create the three defaults.
  - `update`: update scalar/array fields; then **replace** the project's statuses with the provided set (delete-absent / upsert-present by `id`), preserving today's "append provided statuses" outcome while keeping ids stable for `Task.statusId`.
- `UserSerializer`, `TaskSerializer`, `FeedbackSerializer`: plain `ModelSerializer`, `fields="__all__"`.
- FK fields serialize as their related PK (the ObjectId string) via DRF's default `PrimaryKeyRelatedField`, preserving `"projectID": "<id>"` style output.

### 6.2 Query conversion rules (apply everywhere)

| Pattern today | Ported form |
|---|---|
| `Model.objects.get(id=x)` | unchanged (`Model.DoesNotExist` instead of mongo errors) |
| `Model.objects(field=x)` (call form) | `Model.objects.filter(field=x)` |
| `.filter(listField=x)` | `.filter(listField__contains=[x])` (Section 4.7) |
| `.filter(listField__all=lst)` | `.filter(listField__contains=lst)` |
| `ObjectId(uid) in obj["listField"]` | `uid in obj.listField` |
| `obj["field"]` dict access | `obj.field` (or `obj.field_id` for FK id) |
| `.limit(n)` | `[:n]` slice |
| `qs.update(...)` (mongo, unreliable) | `qs.update(**fields)` (ORM bulk) or `obj.save(update_fields=[...])` |
| `from bson ... ObjectId(...)` | removed; ids are plain strings |
| `NotUniqueError` | `django.db.IntegrityError` |
| `mongoengine ValidationError` | `django.core.exceptions.ValidationError` / DRF `ValidationError` |

### 6.3 Per-view notes

- **users.py** — `Q(id__in=...) | Q(email__in=...)` → Django `Q`. `User.objects.create(**data)` unchanged. `NotUniqueError` → `IntegrityError`. `getUsers` classmethod (called by the context processor) keeps its signature and return shape.
- **projects.py** — `userIDs__all` → `userIDs__contains`. Membership auth check `ObjectId(uid) not in project["userIDs"]` → `uid not in project.userIDs`. Drop the manual task-cascade call (FK CASCADE handles it). Default statuses created via the serializer.
- **tasks.py** — convert `.objects(...)` call-forms to `.filter(...)`. `Project.objects.filter(userIDs=uid)` → `__contains=[uid]`. Membership checks as above. Delete the recursive `deleteAllChildren` helper (CASCADE on `parentTaskID` handles subtree deletion); deleting a task deletes its descendants.
- **statuses.py** — this view changes the most. Today it loads the whole project, mutates the embedded `taskStatuses` list, and re-saves. Ported: operate directly on `Status` rows (`Status.objects.create/get/filter/delete` scoped by `project_id`). Reordering writes `order` on the affected rows. GET returns the project's statuses ordered by `order`.
- **kanban.py** — `Task.objects.filter(projectID=...)` and `priority__gt/__gte` are already ORM-shaped; convert call-forms, replace per-task `.save()` loops with `bulk_update(tasks, ["priority", "statusId"])` where a batch is reordered. Replace `ObjectId(stat['id'])` casts with the plain id string. Normalize the mixed `x["priority"]`/`x.priority` access to attribute access.
- **feedback.py** — convert filters; fix the `projectID__all` misuse (projectID is a single ref) to `.filter(projectID=...)`. Chained `.get(...).delete()` unchanged in spirit.
- **generatedTasks.py** — no direct DB access; delegates to `TasksAPIView.createTasks` (ported). OpenAI path unchanged.

### 6.4 Auth (`api/decorators.py`, `app/context_processors.py`)

- `@apiKeyRequired`: `User.objects.filter(id=userID).first()` is already ORM-shaped; change `user["apiKey"]` → `user.apiKey`. Narrow the bare `except Exception` to the specific failure (decrypt/lookup) per the code-review checklist.
- `global_context`: unchanged except it now reaches Postgres through the ported `UsersAPIView.getUsers`. The JWT/ObjectId `userID` is unchanged, so existing cookies authenticate.

---

## 7. `whats_next` Template Tag Port

`app/templatetags/whatsnext.py` only. `api/progress.py` and the templates are untouched.

- Imports: drop `bson`, `mongoengine.errors`, `pymongo.errors`. Add `from django.db import Error as DBError` and `from django.core.exceptions import ValidationError`.
- `whats_next(project_id)`:
  - `Project.objects.get(id=project_id)` (catch `Project.DoesNotExist`, `ValueError`).
  - statuses from `project.taskStatuses.all()` (ordered by `order`).
  - `Task.objects.filter(projectID=project_id).only("name", "statusId", "priority", "parentTaskID")`.
  - record building uses `task.statusId_id`, `task.parentTaskID_id`, `task.id`.
- `whats_next_all(user_id)`:
  - drop `ObjectId(user_id)`; use the string directly.
  - `Project.objects.filter(userIDs__contains=[user_id]).only("name")` (statuses fetched via `prefetch_related("taskStatuses")` to avoid N+1).
  - `Task.objects.filter(projectID__in=project_ids).only("name", "statusId", "priority", "parentTaskID", "projectID")[:TASK_SCAN_LIMIT]`.
  - group by `task.projectID_id`.
- Exception surface returns `{"available": False}` on `DBError`/`ValidationError`/`ValueError`/`Project.DoesNotExist`, matching today's fail-soft behavior.

---

## 8. Configuration & Cutover

### 8.1 Dependencies (`requirements.txt`)

Add:

- `psycopg[binary]` (Postgres driver).
- `dj-database-url` (parse `DATABASE_URL`).

Remove at cutover (Section 8.3):

- `mongoengine`, `pymongo`, `dnspython`, `django-rest-framework-mongoengine`, and the Mongo-only use of `certifi`.

Note: `pymongo` is **kept installed until the ETL has run**, then removed. The ETL is the last consumer.

### 8.2 Settings (`quayside/settings.py`)

Replace the empty `DATABASES = {}` with:

```python
import dj_database_url
DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL"),
        conn_max_age=600,
        conn_health_checks=True,
    )
}
```

- `DATABASE_URL` is required in every environment (dev/CI/prod). Type: string (libpq URL). No default; absence is a startup error (fail safe — the app must not silently run dbless).
- CI sets `DATABASE_URL` to a local/service Postgres; prod sets the Neon URL. The legacy `GOOGLE_POSTGRES_*` keys are removed from `.env` and `env_check_file`.

### 8.3 Cutover sequence

1. Land models + config + serializers + views + tests on the branch (DB switched to Postgres in settings); `pymongo`/`mongoengine` still present so the ETL can run. Full suite green against Postgres.
2. Provision Neon (prod) / confirm local Postgres (dev). Run `migrate`.
3. Run `python manage.py migrate_mongo` against Atlas → Postgres. Review the reconciliation report.
4. Smoke-test the running app on Postgres (auth via existing cookie, list projects, open a board, "What's Next").
5. Remove `api/apps.py:connect_database` and its `ready()` call; remove the Mongo deps from `requirements.txt`; delete the ETL command (or keep it one release as a documented rollback aid — decided at cutover).
6. Hash-pin `requirements.txt` (`pip-compile --generate-hashes` or `pip hash`); CI installs with `--require-hashes`. Closes #4's deferred item.

### 8.4 Rollback

Until step 5, MongoEngine code is removed but Atlas is untouched and read-only-accessed only by the ETL, so reverting the branch restores the Mongo runtime. After step 5, rollback means re-adding the deps and reverting settings; Atlas data is still intact (never written). The ETL never mutates the source.

---

## 9. Observability

- **ETL logging:** per-phase start/summary lines to stdout; counters every 100 records; a final reconciliation table (`entity | source | written | skipped | reconciled`). No PII in logs (ids and counts only; never email/explanation bodies).
- **App logging:** unchanged. The existing `print` in `global_context` on user-fetch failure is replaced with a proper logger call (cut while touching the file, per tech-debt rule).
- **Metrics:** none added; out of scope.

---

## 10. Failure Model

| Class | Trigger | Behavior |
|---|---|---|
| Config | `DATABASE_URL` missing | App fails to start (loud). Fail safe — never run dbless. |
| ETL connectivity | Atlas unreachable | `AtlasUnreachable`, abort before writes, retryable. |
| ETL schema | destination table missing | `SchemaNotMigrated`, abort, run `migrate` first. |
| ETL integrity | dangling FK in source | Reconciled per Section 5.3, counted, reported; not fatal. |
| ETL verification | unexplained count gap | `VerificationFailed`, non-zero exit, no rollback, investigate. |
| Request-time DB error | query fails in a view | Existing error responses preserved; `whatsnext` fails soft to `{"available": False}`. |

Restart recovery: the app is stateless w.r.t. the DB; on restart it reconnects via `DATABASE_URL` (pooled, health-checked). The ETL re-run converges (idempotent).

---

## 11. Security

- **Trust boundary:** unchanged. Authenticated callers present a valid JWT (`apiToken`) whose `apiKey` matches the encrypted value stored on the user row. `@apiKeyRequired` gates every protected view; authorization (project membership) is checked, not just authentication.
- **PK exposure:** ObjectId PKs were already exposed in the API; no new exposure. They are non-sequential, so switching to them as PKs does not enable enumeration any more than today.
- **Secrets:** `DATABASE_URL`, `API_SECRET`, `CHATGPT_API_KEY`, and Mongo creds stay in `.env` (gitignored) and the deploy secret store; never logged. The hardcoded `SECRET_KEY` in settings is pre-existing debt flagged but out of scope for this migration (tracked separately).
- **SQL safety:** all access via the ORM; no raw SQL with string interpolation.
- **Supply chain:** net dependency reduction (Mongo stack removed). New deps (`psycopg`, `dj-database-url`) go through the `/cso --supply-chain` checklist and are hash-pinned with the rest of `requirements.txt`.

---

## 12. Reference Algorithms

### 12.1 ETL main loop (pseudocode)

```
function migrate_mongo(dry_run, only):
    assert_schema_migrated()              # else SchemaNotMigrated
    mongo = connect_atlas_readonly()      # else AtlasUnreachable
    report = new Report()

    if want(only, "users"):
        with atomic():
            for doc in mongo.User.find():
                email = coerce_email(doc, report)        # 5.4
                upsert(User, id=str(doc._id), fields=user_fields(doc, email), dry_run)
            report.users = counts()

    if want(only, "projects"):
        with atomic():
            for doc in mongo.Project.find():
                upsert(Project, id=str(doc._id), fields=project_fields(doc), dry_run)
                for s in doc.get("taskStatuses", []):
                    sid = str(s.get("id") or new_id())
                    upsert(Status, id=sid, fields={project_id: str(doc._id), name, color, order}, dry_run)
            report.projects = counts()

    if want(only, "tasks"):
        with atomic():
            # pass A: roots + FK resolution
            for doc in mongo.Task.find():
                if not Project.exists(str(doc.projectID)):
                    report.orphan_tasks += 1; continue
                status_id = resolve_status(doc.statusId, report)     # detach if missing
                upsert(Task, id=str(doc._id),
                       fields=task_fields(doc, project=projectID, status=status_id, parent=None), dry_run)
            # pass B: parent links
            for doc in mongo.Task.find({"parentTaskID": {"$ne": null}}):
                if Task.exists(str(doc._id)) and Task.exists(str(doc.parentTaskID)):
                    set_parent(str(doc._id), str(doc.parentTaskID), dry_run)
                else:
                    report.detached_parents += 1
            report.tasks = counts()

    if want(only, "feedback"):
        with atomic():
            for doc in mongo.Feedback.find():
                if not (User.exists(str(doc.userID)) and Project.exists(str(doc.projectID))):
                    report.orphan_feedback += 1; continue
                task_id = resolve_task(doc.taskID, report)           # detach if missing
                upsert(Feedback, id=str(doc._id), fields=feedback_fields(doc, task=task_id), dry_run)
            report.feedback = counts()

    verify_counts(mongo, report)          # else VerificationFailed
    print(report.table())
```

### 12.2 Project serializer update (status replace)

```
function ProjectSerializer.update(instance, validated):
    statuses = validated.pop("taskStatuses", UNSET)
    apply_scalar_and_array_fields(instance, validated)
    instance.save()
    if statuses is not UNSET:
        incoming_ids = { s["id"] for s in statuses if "id" in s }
        instance.taskStatuses.exclude(id__in=incoming_ids).delete()   # remove dropped columns
        for s in statuses:
            Status.objects.update_or_create(
                id=s.get("id", new_id()),
                defaults={ "project": instance, "name": s["name"], "color": s["color"], "order": s["order"] })
    return instance
```

---

## 13. Test and Validation Matrix

Tests run with `pytest` + `pytest-django` against a transactional Postgres test DB. The Atlas dependency is gone, so this is the mechanism that closes #5 and #6.

### 13.1 Core conformance (required to land)

**Models / migrations**
- `makemigrations --check` is clean after the models land (migrations committed).
- Creating each model with only required fields succeeds; ObjectId-shaped PK is auto-generated (24 hex).
- `User.email` uniqueness is enforced (duplicate insert raises `IntegrityError`).
- `Status` cascade: deleting a `Project` deletes its `Status` rows and `Task` rows.
- `Task.parentTaskID` cascade: deleting a parent task deletes descendants.
- `Task.statusId` SET_NULL: deleting a `Status` nulls referring tasks, does not delete them.
- ArrayField membership: `Project.objects.filter(userIDs__contains=[uid])` returns the right rows.

**Serializers**
- `ProjectSerializer.create` with `taskStatuses` creates the project and one `Status` row per entry.
- `ProjectSerializer.create` with no `taskStatuses` creates the three defaults.
- `ProjectSerializer.update` replacing statuses: dropped columns deleted, kept columns retain their `id`, new columns created.
- Invalid status (missing required `name`/`color`/`order`) raises `ValidationError`.
- (Rewrite the broken `tests/test_apis.py`, which currently asserts non-existent fields `User(name=...)`, `taskStatuses[{status,task}]`.)

**Views / API (closes #6)**
- Every protected endpoint returns 401 without a valid token, 200/expected with one (auth parity).
- Users: GET/POST/PUT happy paths + duplicate-email → handled error.
- Projects: CRUD; non-member is forbidden from GET/PUT/DELETE of a project they are not in (`userIDs` check).
- Tasks: CRUD; deleting a task deletes its subtree; create under a project the caller does not own is rejected.
- Statuses: create/rename/recolor/reorder/delete operate on `Status` rows; GET returns columns ordered by `order`.
- Kanban: GET returns tasks grouped by status ordered by priority; PUT reorder persists `priority`/`statusId` via `bulk_update`.
- Feedback: create/list/delete; `projectID` filter returns only that project's feedback (the old `__all` misuse is fixed).
- generatedTasks: with OpenAI mocked, the parsed tree is created via the task endpoint.

**What's Next**
- `api/progress.py`: the existing 20 tests pass unchanged.
- `whats_next(project_id)`: returns segments/in_flight/next_up for a seeded project; returns `{"available": False}` for a missing/invalid project id.
- `whats_next_all(user_id)`: aggregates across the user's projects; returns `{"available": True, "projects": [], "more": 0}` for a user with no projects; `{"available": False}` for empty user_id.

**ETL**
- Round-trip: seed a fake Mongo (or fixture) with cross-referenced docs; run the command; assert all rows + FKs land with ObjectId PKs preserved.
- Idempotency: running twice yields identical row counts and no duplicates.
- Orphan reconciliation: a task with a dangling `projectID` is skipped and counted; a dangling `statusId`/`parentTaskID` is detached and counted; orphan feedback skipped and counted.
- Email coercion: missing/duplicate emails are synthesized to `*.invalid` and counted.
- `--dry-run` writes nothing.

### 13.2 Real integration (run at cutover, needs creds/network)

- Against a copy/staging of Atlas: full ETL completes, the verification table shows source==written+reconciled for every entity, exit code 0.
- App boots with only `DATABASE_URL` set (no Mongo creds), serves an authenticated request using a pre-migration `apiToken` cookie (proves auth continuity).

### 13.3 Definition of done

- All Core conformance tests pass in CI against Postgres; `mongoengine`/`rest_framework_mongoengine`/`pymongo` absent from `requirements.txt`; the file is hash-pinned and CI installs `--require-hashes`.
- #5 and #6 closed; #4's deferred hash-pin item closed.
- ETL has run against production data with a clean reconciliation report; the app serves traffic on Postgres.

---

## 14. Implementation Checklist (maps to task list)

1. Models (`api/models.py`) + `new_id` helper + `default_task_statuses`; `makemigrations`; commit migration.
2. Settings: `dj-database-url`, `DATABASE_URL`, populate `DATABASES`. Add `psycopg`, `dj-database-url` to requirements.
3. Failing tests first (models, serializers, views, whatsnext, ETL) per Section 13 — `/tdd`.
4. Serializers port.
5. Views port (7 files) + decorator/context-processor tweaks.
6. `whatsnext.py` port.
7. ETL command + its tests.
8. Green suite on Postgres → `/simplify`.
9. Cutover (Section 8.3): provision, migrate, run ETL, smoke test, remove Mongo stack, hash-pin.
10. Close #5/#6, update #4; PR targets the fork's `dev`.

## 15. Open items resolved by decision (2026-06-24)

- PK strategy → ObjectId `CharField` (auth continuity, no remap).
- Prod hosting → Neon; dev → local Postgres.
- User model → plain `models.Model`, custom auth preserved.
- List-membership fields → `ArrayField` (not M2M) for parity.

## 16. What this spec does not prescribe

- The exact Neon project/region and connection-pool sizing (implementation-defined at provisioning).
- Whether the ETL command is deleted immediately post-cutover or kept one release as a rollback aid (decided at step 5).
- CI's specific Postgres service definition (any Postgres 14+ that accepts `DATABASE_URL`).
