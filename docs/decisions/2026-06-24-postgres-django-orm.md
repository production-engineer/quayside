# ADR: Migrate persistence from MongoDB/MongoEngine to PostgreSQL + Django ORM

## ADR Author/s

Erik Williams (with Claude)

## Update Date

2026-06-24

## Status

Accepted

## Who should be notified of ADR changes?

@production-engineer

## Context

Quayside stores all data in MongoDB Atlas through MongoEngine, mapped into a Django project via `rest_framework_mongoengine`. This choice is now actively costing us:

- **Schemaless drift.** Every model sets `strict=False` (`api/models.py`), so unknown fields are silently tolerated. Views read documents both as objects (`task.priority`) and as dicts (`task["priority"]`) interchangeably, and filters like `Feedback.objects.filter(projectID__all=...)` exist that do not match the field's cardinality. There is no schema enforcing what a `Project` or `Task` actually is.
- **The Atlas boot blocker.** `api/apps.py` opens a MongoDB Atlas connection at app startup (`AppConfig.ready`). Any environment whose IP is not in the Atlas allowlist cannot boot the app, including CI. This is the direct cause of issue **#5** (Mongo connection fail when implementing API tests).
- **Test gymnastics.** Because there is no Django-managed database, tests cannot use Django's transactional test DB. The existing `tests/test_apis.py` is written against fields that do not exist on the models (`User.objects.create(name=...)`, `taskStatuses[{'status','task'}]`) and cannot pass. Issue **#6** (MongoDB API Tests) is the standing request for real, runnable API tests.
- **Stack divergence.** The rest of the stack (circumpolar.ai, beadedcloud.com) is PostgreSQL. Tooling, hosting patterns, hire-ability, and reusable skills all assume Postgres. MongoEngine keeps quayside on an island.

The data model is, in practice, relational: `Task` references `projectID`, `parentTaskID`, and `statusId`; `Project` owns an ordered list of embedded `Status` documents; cross-references between users, projects, and tasks are everywhere. Nothing about the domain needs a document store.

The decision to migrate (target = PostgreSQL + native Django ORM, migrate the DB before reimplementing any Mongo-coupled feature PRs) was confirmed by Erik on 2026-06-23. This ADR records the rationale; the companion spec records the how.

### Constraints

- **Auth must survive untouched.** Authentication is a JWT-in-cookie (`apiToken`) plus an encrypted `apiKey` stored per user. The JWT payload encodes `userID` as the Mongo ObjectId string; `@apiKeyRequired` (`api/decorators.py`) and `app/context_processors.py` both decode that ObjectId and look the user up by it. Any PK change that invalidates those ObjectIds logs every user out and invalidates every stored API key.
- **Live data must come across intact.** Atlas holds roughly 105 users, 423 projects, and 1171+ tasks, with ObjectId cross-references that must remain valid after migration.
- **The shipped "What's Next" feature must keep working.** `api/progress.py` is pure and DB-agnostic (20 passing tests) and survives unchanged; only the querysets in `app/templatetags/whatsnext.py` need porting.

## Options Considered

### Option 1: PostgreSQL + native Django ORM (chosen)

- **Pros:**
  - Enforced schema kills the `strict=False` drift class of bugs at the database layer.
  - Django's transactional test database makes #5 and #6 ordinary `TestCase` work: no Atlas, no allowlist, no mongoengine/pytest gymnastics.
  - Aligns quayside with circumpolar/beadedcloud: same DB engine, same hosting story, same skills.
  - First-class relations (FK, cascade, `select_related`/`prefetch_related`) replace hand-rolled ObjectId joins and the in-memory `ObjectId(uid) in project["userIDs"]` checks.
  - Mature migration tooling (`makemigrations`/`migrate`) gives versioned, reviewable schema history.
- **Cons:**
  - Foundational rearchitecture: every model, serializer, view query, and test changes. One large coordinated change.
  - Requires a one-time ETL from Atlas with cross-reference preservation.
  - List fields (`userIDs`, `teamIDs`, contributor lists) must be modeled deliberately (see spec); a naive port loses the membership-query semantics.

### Option 2: Stay on MongoDB, fix the test harness only

- **Pros:** Smallest immediate diff; no ETL; no model rewrite.
- **Cons:** Leaves every root cause in place: schemaless drift, the Atlas boot/allowlist blocker, and stack divergence all remain. `mongomock` or a containerized Mongo would patch #5/#6 but entrench the document store and the `rest_framework_mongoengine` dependency. It is throwaway effort that we would undo at the first feature that needs real relational integrity.

### Option 3: A different relational database (e.g. SQLite for dev, MySQL)

- **Pros:** Also gets us schema enforcement and a real test DB.
- **Cons:** SQLite diverges from production behavior (no strict typing parity, weaker concurrency, no `ArrayField`/JSON parity). MySQL gains us nothing over Postgres and still diverges from the rest of the stack. Postgres is the stack standard; picking anything else creates a second island.

### Option 4: Do nothing

- **Pros:** Zero effort now.
- **Cons:** #5 and #6 stay open, the app remains unbootable wherever the Atlas allowlist does not reach, drift bugs keep compounding, and quayside stays divergent from every other project. The cost grows with every feature added on top of MongoEngine.

## Decision

Migrate quayside to **PostgreSQL with the native Django ORM**, removing MongoEngine, PyMongo, and `rest_framework_mongoengine`.

Three foundational choices anchor the migration (rationale here; mechanics in the spec):

1. **Primary keys preserve the Mongo ObjectId** as a 24-character `CharField` PK on every table. This keeps every cross-reference valid 1:1 with no remap, and — decisively — keeps every existing `apiToken` cookie and stored `apiKey` JWT valid, so no user is logged out and no key is reissued. The alternative (Django `BigAutoField` + an ObjectId→int remap) was rejected because it breaks the auth contract and multiplies ETL risk for no domain benefit.

2. **The embedded `Status` list becomes a related `Status` table** (FK to `Project`, with `name`, `color`, `order`). `Task.statusId` becomes an FK to `Status`. This turns the hand-rolled "find the status in the list and re-save the whole project" logic in `api/views/v1/statuses.py` into ordinary row operations.

3. **`User` stays a plain `models.Model`**, not Django's `AbstractUser`. The custom JWT-in-cookie + encrypted-`apiKey` flow is preserved exactly; `@apiKeyRequired` and the context processor are unchanged. Adopting Django's auth framework would force an int PK (conflicting with choice 1), add password/session machinery we do not use, and expand the migration's scope beyond parity. Django auth can be revisited later as its own decision.

**Production hosting is Neon** (serverless Postgres, branch-per-PR, pooled connections), wired via a single `DATABASE_URL`. Development uses local Postgres. The existing `GOOGLE_POSTGRES_*` keys in `.env` (a prior Cloud SQL intent) are superseded; the spec documents the cutover of config.

We **migrate the database first**, then reimplement the Kanban-customization PR (#2) on the new stack. We do not reimplement Mongo-coupled feature PRs before the migration — that would be throwaway work.

## Consequences

### Positive

- #5 and #6 are resolved by construction: tests become real Django `TestCase`s against a transactional test DB. Both issues close with this work.
- The `strict=False` drift class disappears; the schema is enforced and reviewable as migrations.
- The app boots anywhere with a `DATABASE_URL`; no IP allowlist gate on startup or CI.
- Quayside converges with the rest of the stack.
- `rest_framework_mongoengine`, `mongoengine`, `pymongo`, `dnspython`, and `certifi`-for-Mongo leave the dependency tree, shrinking supply-chain surface. Combined with this work we finish the deferred item of issue **#4**: hash-pin `requirements.txt`.

### Negative

- A large, coordinated change touching models, serializers, all 7 views, the `whatsnext` tag, and the full test suite. Mitigated by phasing (models + config → ETL → view/serializer port → cutover) and by keeping `progress.py` untouched.
- A one-time ETL with a correctness burden: every ObjectId cross-reference must survive. Mitigated by preserving ObjectId PKs (no remap) and by an idempotent, re-runnable, verify-after script (spec §ETL).
- ObjectId-as-`CharField`-PK is mildly non-idiomatic for Django and slightly wider than a `bigint` key. This is an accepted, deliberate trade for auth continuity and ETL safety.
- Real foreign keys make referential integrity strict: data that was loosely referenced in Mongo (orphan `projectID`s, dangling `statusId`s) must be reconciled during ETL rather than silently tolerated. This is a feature, but it surfaces latent bad data that the ETL must handle explicitly.

## Spec

- Spec: [docs/specs/2026-06-24-mongo-to-postgres-migration.md](../specs/2026-06-24-mongo-to-postgres-migration.md)

## References

- Related issues: #2 (Kanban customization, reimplement after), #4 (supply chain; hash-pin requirements as part of this), #5 (Mongo connection fail in tests; closed by this), #6 (MongoDB API tests; closed by this)
- Source of truth ported unchanged: `api/progress.py` and `tests/test_progress.py`
- Stack precedent: circumpolar.ai and beadedcloud.com (PostgreSQL)

## Consensus

Erik Williams (decision confirmed 2026-06-23; PK/hosting/User-model choices confirmed 2026-06-24).
