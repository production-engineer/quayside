# quayside Portal Module Specification

Status: Draft v2 (2026-09-13; v1 the same day)

Purpose: quayside answers "what's next?" for a project by holding its goal, sensing reality from the places work already happens, and ranking the next action; this spec describes it as a beta module inside the Remote Hands staff portal.

Companion documents: ADR [2026-09-13-rebuild-as-remote-hands-portal-module.md](../decisions/2026-09-13-rebuild-as-remote-hands-portal-module.md) and the requirements register at https://docs.google.com/spreadsheets/d/1xSLNc6Y9vlIriipU_w_GrWAKqodkFzcM9T3XNvOLHbE. Row numbers below (R9, R220) are that sheet's ID column and are permanent.

## 1. Problem Statement

quayside is a project management tool whose thesis is top-down: a project starts from a goal, the software senses progress instead of waiting for data entry, and every contributor can see the one next thing to do. The 2023 to 2024 Django app implemented the bottom-up half (tasks, columns, a tree) and none of the loop. Remote Hands needs a system of record for tasks and contacts as it leaves HubSpot, and Erik ruled that quayside is that system.

Operational problems this module solves:

- Remote Hands staff track work in a Google Sheet, Discord threads and memory files that drift from reality.
- Nobody can answer "what should I work on next" for a project without asking the person who holds it in their head.
- HubSpot contacts and organizations have no destination once the subscription ends.
- The 108 users and 423 projects in the old quayside database are stranded on a Mongo cluster whose hosting is lapsing.
- The old app's features exist only as code nobody trusts; the register has 209 rows describing them and there is no running system that matches it.

Important boundary: this module is not responsible for payroll, assignments, work items, GOTV or any existing portal feature. It reads nothing from the `public` or `voting` schemas except the signed-in user's identity and role. It does not replace GitHub issues for the Remote Hands code repos.

## 2. Goals and Non-Goals

### 2.1 Goals

- Every behavior in the register marked v1 (R9 to R18, R24 to R26, R28, R29, R44, R47 to R232 where Version is v1) exists in the module, and the 16 rows carried as fixes behave correctly rather than as the old app did.
- A Remote Hands admin can sign in to the portal once and reach quayside from the sidebar; no second login (decision 51).
- All quayside data lives in a `quayside` schema in the Remote Hands Supabase project with row level security on every table from the first migration (decision 52).
- Contacts and projects from the old Atlas database are imported once, idempotently, with their old ObjectIds preserved as `legacy_id` (decision 53).
- The module ships in slices (Section 18); each slice is a merge to `main` that deploys and is usable on its own. Slice 0 goes live first and is validated by Erik before Slice 1 starts (decision 54, revised 2026-09-13).

### 2.2 Non-Goals

- A standalone quayside.app deployment (Option 2 in the ADR); pointing the domain at this module is a later decision.
- Bids, escrow, marketplace, reputation (R30).
- Monte Carlo estimation (R34), portfolio view (R35), billing (R36).
- XP for completed work (R223): v2 by decision 57. The `tasks` model carries nothing for it in v1; when it comes, XP is a derived sum over `audit_log` completions, not a stored counter.
- Rebuilding Django, Mongo, Cloud Run, gunicorn, D3 or pytest specifics (the 39 rows marked superseded); the intent behind each is met by the new stack and named where it matters.
- Feedback documents from Atlas (30 rows of mood entries); not imported.
- Any write to HubSpot.

## 3. System Overview

### 3.1 Main Components

1. `quayside-routes`: Next.js App Router pages under `app/(dashboard)/quayside/`.
   - Home (What's Next across projects), project views (space, workspace, board, tree, map), task detail, contacts, imports, settings.
   - Each leaf is `page.tsx` plus `error.tsx`, composing `ErrorBoundary`, `Suspense` and a `*-server.tsx` component, per portal convention.
2. `quayside-feature`: `src/features/quayside/<subfeature>/{domain,application,infrastructure,presentation}`.
   - Subfeatures: projects, tasks, statuses, whats-next, charter, contacts, feeds, imports, notifications.
   - Supabase is touched only in `infrastructure/repositories/*.impl.ts` via `createClient().schema("quayside")`.
3. `quayside-schema`: Postgres schema `quayside` in project `rqkezltvhepkhowyravz`, exposed through PostgREST alongside `public` and `voting`.
4. `quayside-importer`: a one-shot, re-runnable command that reads Atlas and writes the schema (Section 9).
5. `quayside-feeds`: connectors that turn external events into `signals` rows (Section 10). Slice 5 and later.
6. `quayside-notifier`: daily and weekly messages to Discord and email (Section 11). Slice 5 and later.
7. `quayside-ranker`: the What's Next computation (Section 8), a pure function over project state.

### 3.2 Layers

- Domain: entities and repository interfaces; no framework imports.
- Application: zod schemas for inputs, use cases that call one repository.
- Infrastructure: DTOs, mappers, repository implementations, Atlas reader, LLM client, Discord client.
- Presentation: `queries/*.queries.ts` (React `cache()`, `assertAdmin()` or `assertRole()`), `actions/*.actions.ts` (`"use server"`, `safeAction`, `revalidatePath`), components under `components/features/quayside/`.

### 3.3 External Dependencies

- Supabase Auth and Postgres (existing portal project).
- Vercel (existing portal deployment; merge to `main` deploys).
- Mongo Atlas cluster `quayside-cluster.ry3otj1.mongodb.net`, database `quayside`, read only, for the import.
- An LLM provider for the charter conversation and task generation, behind one interface (Section 7). The old app used a chat completion API; this spec does not prescribe the provider.
- Discord webhook or bot for the daily and weekly messages; Resend for email (both already configured in the portal).
- Google Sheets API for the sheet mirror (R13), Slice 6.

## 4. Core Domain Model

All tables live in schema `quayside`. Primary keys are `uuid` with `default gen_random_uuid()`. Every table has `created_at timestamptz default now()` and `updated_at timestamptz default now()` maintained by a trigger. Column names are snake_case; the old camelCase API names (R58) are not carried.

### 4.1 `projects`

One unit of work with a goal.

Fields:
- `id` (uuid)
- `legacy_id` (text, unique, nullable): the Atlas ObjectId, 24 hex characters.
- `name` (text, not null, 1 to 200 characters after trim)
- `slug` (text, not null): lowercase letters, digits and hyphens, 1 to 64 characters, unique per organization; derived from `name` on create and unchanged on rename in v1 (R222, Section 6.3).
- `description` (text, nullable)
- `goal` (text, nullable in the schema, required by the UI for new projects; R9)
- `done_when` (text, nullable, same rule as goal)
- `start_date`, `end_date` (date, nullable)
- `budget_cents` (bigint, nullable): the old app stored budget as free text; the importer parses digits and stores null when it cannot.
- `state` (text, check in `planning`, `active`, `archived`): `planning` is the project space, `active` the workspace (R29); imported projects arrive `archived` (Section 9).
- `charter` (jsonb, default `{}`): objectives, assumptions, scopes_included, scopes_excluded, risks, sponsors, completion_requirements, quality_assurance, kpis, information_links, types. Replaces the eleven string-array columns of the old model (R26, R50).
- `organization_id` (uuid, nullable, references `organizations`): the org segment of the URL; null projects address as `/quayside/-/<project>` in v1.
- `owner_id` (uuid, not null, references `auth.users`)
- `created_by_import` (boolean, default false)

### 4.2 `project_members`

Who can see and edit a project.

Fields:
- `project_id` (uuid, references `projects` on delete cascade)
- `user_id` (uuid, references `auth.users`)
- `role` (text, check in `owner`, `member`): two roles in v1 (R17).
- Primary key (`project_id`, `user_id`).

### 4.3 `statuses`

Board columns, per project.

Fields:
- `id` (uuid), `project_id` (uuid, cascade)
- `name` (text, not null, 1 to 64 characters after trim; unique per project case-insensitively, R146)
- `color` (text, not null, six or eight uppercase hex characters, no `#`)
- `position` (integer, not null): 1 to n, compacted on every reorder (R145).
- `background_image_url` (text, nullable, max 2048; R60, R147)

Defaults on project creation: Todo `323232` 1, In-Progress `EFA610` 2, Done `01796E` 3 (R52). The done column is the highest `position` (R105).

### 4.4 `tasks`

A work block (R24).

Fields:
- `id` (uuid), `legacy_id` (text, unique, nullable)
- `project_id` (uuid, cascade), `parent_id` (uuid, references `tasks`, cascade, nullable): unlimited nesting.
- `status_id` (uuid, references `statuses`, on delete set null)
- `name` (text, not null, 1 to 200 characters), `description` (text, nullable)
- `start_date`, `due_date` (date, nullable)
- `duration_minutes` (integer, default 0, check >= 0)
- `position` (integer, nullable): order within a column (R138, fixes R143).
- `budget_cents` (bigint, nullable)
- `requirements` (text[], default `{}`)
- `capability` (text, nullable, check in `ai_doable`, `ai_assisted`, `human_only`, `unknown`; R59)
- `source` (text, not null, default `quayside`, check in `quayside`, `import`, `github`, `email`, `discord`, `sheet`)
- `external_ref` (text, nullable, unique where not null): for example `owner/repo#12`.
- `number` (text, not null): the work-breakdown number, `4.1.2` for the second child of `4.1` (R222). Unique per project. Assigned on create as parent number plus the next free integer among siblings; on re-parent or reorder the moved subtree is renumbered depth-first from the new position, and the old numbers are kept in `audit_log`, so an old URL resolves through the history to the task's current number (Section 6.3).
- `attention` (text, nullable, check in `needs_review`, `action_requested`): the two person-set states of R225. In progress is the status column, done is the done column, critical path is computed (Section 8.5); none of those three is stored on the row.

### 4.5 `task_links`

Explicit dependencies (predecessor, successor) and cross-project references.

Fields:
- `from_task_id`, `to_task_id` (uuid, cascade), `kind` (text, check in `blocks`, `relates`). Primary key on all three. A `blocks` edge from A to B means B cannot start until A is done.

### 4.6 `task_assignees`

- `task_id` (uuid, cascade), `contact_id` (uuid, references `contacts`). Primary key on both. Assignees are contacts, not only portal users, so imported owners and HubSpot people can be assigned.

### 4.7 `contacts` and `organizations`

People and organizations (R15).

`organizations`: `id`, `legacy_hubspot_id` (text, unique, nullable), `name` (text, not null), `slug` (text, not null, unique; same shape as `projects.slug`), `domain` (text, nullable, lowercased), `notes` (text).

`contacts`: `id`, `legacy_id` (text, unique, nullable; Atlas user id), `legacy_hubspot_id` (text, unique, nullable), `user_id` (uuid, nullable, references `auth.users`; set when a contact is also a portal user), `email` (text, unique, lowercased, trimmed), `first_name`, `last_name` (text), `organization_id` (uuid, nullable), `phone` (text, nullable), `source` (text, check in `atlas`, `hubspot`, `manual`), `notes` (text).

### 4.8 `feedback`

Mood entries (R117 to R121). Kept for parity; not imported.

- `id`, `project_id` (cascade), `task_id` (set null, nullable), `user_id` (auth.users), `mood` (smallint, check between 1 and 5), `explanation` (text), `created_at`.

### 4.9 `signals`

The reality feed (R10). Slice 5.

- `id`, `project_id` (nullable until matched), `task_id` (nullable), `source` (text, check in `github`, `discord`, `gmail`, `sheet`, `calendar`, `manual`), `external_id` (text, unique per source), `occurred_at` (timestamptz), `actor` (text), `summary` (text), `payload` (jsonb), `match_state` (text, check in `matched`, `unmatched`, `ignored`).

### 4.10 `imports`

One row per importer run (Section 9).

- `id`, `source` (text), `started_at`, `finished_at`, `dry_run` (boolean), `counts` (jsonb), `errors` (jsonb), `run_by` (uuid).

### 4.11 `audit_log`

Every change to a project or task, viewable per task (R232, "All history recorded").

- `id` (bigint identity), `occurred_at` (timestamptz, default `clock_timestamp()`)
- `actor_id` (uuid, nullable, references `auth.users`; null for the importer and cron routes, which set `actor_label` instead)
- `actor_label` (text, nullable): `import`, `cron`, `discord`, or null when `actor_id` is set
- `table_name` (text, check in `projects`, `statuses`, `tasks`, `task_links`, `task_assignees`, `project_members`)
- `row_id` (uuid), `project_id` (uuid, not null, denormalized so a project's history is one query)
- `op` (text, check in `insert`, `update`, `delete`)
- `before` (jsonb, nullable), `after` (jsonb, nullable): the full row image; `update` stores both, `insert` only `after`, `delete` only `before`.

Written by one row-level trigger attached to each listed table, never by application code, so an import and a drag on the board leave the same kind of record. "All history" in R232 is read as project and task history: `contacts`, `organizations`, `feedback` and `signals` are not audited in v1, so names, emails and phones never land in a second table (Section 15); `imports` is its own log. Rows are never updated or deleted by any policy; the only write path is the trigger. Retention is unbounded in v1.

### 4.12 Normalization Rules

- Emails: trim, lowercase, compare exactly.
- Names for uniqueness (statuses): trim, collapse internal whitespace, compare case-insensitively.
- Hex colors: strip a leading `#`, uppercase; accept 6 or 8 characters; anything else is a validation error, never silently replaced (the old app fell back to grey, R56 and R106).
- Duration input: tokens `Nw`, `Nd`, `Nh`, `Nm` in any order, decimals allowed; week = 5 working days, day = 8 hours (the spec value, fixing the old code's 24-hour day, R73); a bare number is minutes; result rounded to the nearest minute.
- Legacy ids: exactly 24 lowercase hex characters or the import row is rejected.
- WBS numbers (R222): dot-separated positive integers with no leading zeros; the root level is `1`, `2`, `3`; compared segment by segment as integers, so `4.10` sorts after `4.9`. A URL segment that fails this shape is a `404`, not a search.

## 5. Access and Gating

### 5.1 Edge gate

`{ path: '/quayside', roles: ['admin'] }` in `PROTECTED_ROUTES` in `lib/supabase/proxy.ts` (shipped, PR #73). Unauthenticated requests redirect to `/login`; authenticated non-admins are redirected to the portal home. Widening to `organization_member` is a one-line change and a deploy.

### 5.1.1 Beta switch (decision 56, revised 2026-09-13)

The route is also hidden behind a per-user opt-in. `user_metadata.beta_features` on the auth user is a string array parsed by `src/features/shared/auth/application/beta-features.ts` (unknown values dropped, missing key means nothing on). The session exposes it as `user.betaFeatures`; the nav item carries `beta: "quayside"` and is filtered out until the flag is present; `app/(dashboard)/quayside/layout.tsx` redirects an admin without the flag to `/settings/beta`, where a switch writes the array with `auth.updateUser` and then `auth.refreshSession` so the new JWT carries it at once. The switch only unhides; the role rule above still decides who may reach the route, which is why a user-writable claim is acceptable here. Erik's words on the first preview: "the beta feature needs to be under my profile ... Otherwise, the quayside side button should not be present." The earlier email-allowlist idea is withdrawn.

### 5.2 Server gate

Every query and action under `src/features/quayside/` calls `assertAdmin()` (or `assertRole()` once widened) before touching a repository. `ForbiddenError` is thrown, never a silent empty result. This is the fix for R42 and R43, the two old endpoints that skipped the membership check.

### 5.3 Row level security

Every table enables RLS in the migration that creates it. Policies are created idempotently inside a `do $$ ... $$` block and are scoped `to authenticated`. Admin authority is `exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin')`, matching the portal's `is_admin()` convention, not `app_metadata`. Project visibility for non-admins is membership in `project_members`. No grant to `anon`; default privileges for `anon` are cleared on the schema, copying `20260910203727_voting_revoke_anon.sql`.

### 5.4 Navigation

The `quayside` entry in `navigationItems` has `roles: ['admin']` and `beta: "quayside"` (Section 5.1.1), Compass icon in `iconMap`; today it links to `/quayside/home`. From Slice 2 it gains children: Home, Projects, Contacts, Imports. The module's own left directory (R227) lives inside the quayside pages, not in the portal sidebar.

## 6. Projects, Tasks and Boards (parity subsystem)

### 6.1 Behavioral contract

- Creating a project requires `name`, `goal` and `done_when` (R9) and seeds the three default statuses (R52). The creator becomes `owner` in `project_members`.
- A project starts in `planning` (project space). Moving to `active` (workspace) is an explicit action that records `activated_at` in the charter and notifies members (R29).
- Tasks are created as roots or under a parent; deleting a task re-parents its children to the grandparent by default, or deletes the subtree when `deleteChildren` is true (R71).
- Deleting a status sets `status_id` null on its tasks; the board renders null-status tasks in the leftmost column (R129, R135).
- Moving a task to a column at a position rewrites `position` for the affected rows in one transaction and never leaves gaps (R137, fixes R143).
- Board (R141), tree (R148 to R150) and map (R221) are three views over the same task query; none of them fetches separately.
- List queries return `200` with an empty array when nothing matches (fixes R163). Unknown query parameters are a `400` validation error, never a `500` (fixes R164).
- Every mutation is a server action with `safeAction`; the browser never calls Supabase directly for writes (fixes R31, the CSRF exposure).

### 6.2 Validation and error surface

Named errors: `ValidationError` (400), `ForbiddenError` (403), `NotFoundError` (404), `ConflictError` (409, duplicate status name or reorder mismatch), `CycleError` (409, a `blocks` edge that would create a cycle). All are rendered by the route's `error.tsx` with a message a person can act on; no `alert()` and no plain-text 500 pages (fixes R174).

### 6.3 Addressing and numbering (R222)

- Every task has a WBS `number` (Section 4.4) and the URL for a task is `/quayside/<org>/<project>/<number>`, where `<org>` and `<project>` are slugs (lowercase, hyphenated, unique per parent; stored on `organizations.slug` and `projects.slug`). Breadcrumb shows `org / project / number`, and the task header shows the number before the name.
- Creating a child of `4.1` gives it `4.1.N` where N is one more than the largest sibling segment; creating a root gives the next root integer. Renumbering on move is deterministic (R222): the moved subtree takes the destination's next free number and its descendants are renumbered depth-first in `position` order, in the same transaction as the move. The register asks only for determinism; this particular rule is the spec's choice.
- An old number in a URL is resolved through `audit_log` (`after.number` history) to the task's current row and redirects with a 308; a number that never existed is a 404.
- Slugs are separate from names: renaming a project does not change its slug in v1 (a redirect table is a recommended extension).

### 6.4 Task states and the three buttons (R225)

A task card shows Start, Track and Done:

- Start moves the task into the first non-done column whose name is In-Progress or, when none is, the second column, and clears `attention`. The card turns green (in progress).
- Track sets `attention = needs_review`: the task keeps its column and turns yellow, asking a teammate to look. A reviewer can set `attention = action_requested` (red) with a comment recorded in `audit_log`; the assignee clears it by pressing Start again.
- Done moves the task to the done column (highest `position`) and clears `attention`.
- Critical path (purple) is never set by a person; it is computed (Section 8.5) and drawn on map edges and node borders.

This reading of Start, Track and Done is the spec's interpretation of the 2023 sketch, which labels the buttons but does not define them; Erik confirms or corrects it before Slice 2 builds the card. Only these four colors plus the neutral appear on nodes, edges and card buttons, and the map carries the legend (Section 12).

### 6.5 Shell: directory, search and utilities (R227, R228, R230)

- The quayside pages have a left directory in the GitHub style: New project, New task, Starred orgs, Projects, Team, Objectives, each a collapsible group, with the current path as a breadcrumb that matches the URL (R227). Starred orgs pin to the top; the directory's open or closed state is per user and per device (`localStorage`, not the database).
- A search box sits in the quayside top bar; pressing `/` anywhere outside an input focuses it (R228). Results span projects, tasks and contacts the user can see; Enter opens the top result. The ranking (exact name match, then prefix, then substring, twenty per group) is the spec's proposal, since R228 fixes only the hotkey, the three indexes and Enter; Erik confirms it before Slice 8. Search is a server query with the same RLS as every list; nothing is indexed client-side in v1. Search ships in Slice 8 with the task filters (R79); the directory and utilities below ship in Slice 2 (Section 18).
- Invite, Tutorial and Feedback sit at the bottom of the directory (R230). Invite opens the project-member invite (R124); Tutorial opens the register's Home page walk-through; Feedback opens the mood entry (R117). Marketplace is absent in v1 (R30).

## 7. Charter and Task Generation

### 7.1 Charter conversation (R25)

Creating a project opens a conversation, not a form. The assistant asks for the goal, the done-when statement, scope in and out, constraints and the end state, then proposes a plan built backward from the end state. The user can skip ahead at any turn; the minimum to finish is `name`, `goal` and `done_when`.

### 7.2 Task generation (R97 to R101)

Given the charter, the generator returns a hierarchical outline where each leaf carries a duration; the parser turns it into `tasks` rows with correct `parent_id` and summed parent durations. Generation runs after the project row exists, in a server action with a 60 second budget. On provider failure the project remains with zero tasks and the UI shows a retry control; no 500 page (fixes R101).

### 7.3 Provider interface

`generateOutline(charter): Outline` and `converse(history): Turn` behind one module; the provider name and model come from environment variables `QUAYSIDE_LLM_PROVIDER` (string, no default, required in production, startup fails without it) and `QUAYSIDE_LLM_MODEL` (string, no default). API keys follow the portal's secret conventions and are never logged.

## 8. What's Next

### 8.1 Inputs

Project goal and done-when, tasks with status and position, `task_links` of kind `blocks`, signals matched to the project (Section 10), and drift (Section 8.3).

### 8.2 Ranking (R12, R104, R105)

Reference algorithm:

```
function whats_next(project):
    done_position = max(position for status in project.statuses)
    open_leaves = [t for t in project.tasks if t has no children and t.status.position < done_position]
    unblocked = [t for t in open_leaves if every blocker of t is done]
    if unblocked is empty and open_leaves is empty: return DONE
    if unblocked is empty: return BLOCKED(open_leaves with their blockers)
    ranked = sort unblocked by (critical_path_length desc, due_date asc, status.position desc, position asc, id)
    top = ranked[0]
    return Card(title=top.name, why=explain(top), first_action=top.description or top.name,
                done_when=top.requirements or "moved to " + done column name)
```

`critical_path_length` is the duration-weighted longest chain of `blocks` edges from the task to any leaf; a cycle raises `CycleError` and the card shows the cycle instead of a ranking. The same function feeds the project card, the home page (in-flight projects first, then most active, then alphabetical, capped at 8 with "+ N more", R104), the chat answer and the daily message.

### 8.3 Drift (R11)

Per project: schedule drift = today minus `end_date` when the done ratio is below 1; scope drift = tasks created after activation over tasks at activation; budget drift = spent over `budget_cents` where spend signals exist. Each drift line links to the signals that produced it.

### 8.4 Chat (R116, R226)

Qpa answers "what's next", "why", "why not X" and "re-rank" by calling `whats_next` and `explain`; it never invents a task that is not in the table.

The assistant panel opens with four fixed prompts and a free-text box (R226): "What should I work on next?" (calls `whats_next` for the current project, or the home ranking when no project is open), "What should I review next?" (tasks with `attention = needs_review` the user did not last edit, oldest first, then tasks in the done column with no reviewer entry in `audit_log`), "How can our team collaborate more effectively?" (the drift panel plus the blocked list with blocker owners), and "How can our team accelerate productivity?" (the critical path with its slack-zero tasks and the longest idle unblocked task). Each answer cites the rows it used; a question the data cannot answer says so instead of guessing. R226 names the four questions and nothing more; what each one computes, above, is the spec's interpretation, and Erik confirms or corrects it before Slice 4 builds the panel.

### 8.5 Criticality (R224)

For each open task, `slack = latest_start - earliest_start` from a forward and backward pass over the `blocks` graph using `duration_minutes` (tasks with zero duration count as one hour for scheduling only). `criticality = 1 - slack / project_span`, clamped to 0 to 1, where `project_span` is the longest path length in the project; shown on the card as a percentage. Tasks with `slack = 0` are the critical path and their `blocks` edges are drawn purple (R225); when several chains tie, all are critical. A cycle raises `CycleError` and the card shows the cycle. Criticality is recomputed on read and never stored. R224 fixes only that the number derives from critical-path position and slack; the formula, the one-hour floor and the clamp are the spec's proposal, and Erik confirms them before Slice 4.

## 9. Importer (decision 53)

### 9.1 Source

Atlas, read only, collections `User`, `Project`, `Task`. `Feedback` is not read. Credentials `MONGO_USERNAME` and `MONGO_PASSWORD` are read from the environment of the machine running the import and never stored in the portal.

### 9.2 Behavioral contract

1. Users become `contacts` with `source = atlas`, `legacy_id` = ObjectId, email normalized; a contact whose email matches a portal user gets `user_id` set.
2. Projects become `projects` with `state = archived`, `created_by_import = true`, `owner_id` = the portal user matching the first `userIDs` entry, or the importing admin when none matches; the eleven string arrays go into `charter`; `taskStatuses` become `statuses` with `position` from `order`; `budget` is parsed to cents or null.
3. Tasks become `tasks` in two passes (parents first); `statusId` maps through the status legacy ids; a dangling `parentTaskID` becomes a root and is counted; `otherTaskDependencies` become `blocks` edges when both ends exist.
4. Every write is `upsert` on `legacy_id`, so re-running is idempotent (R181).
5. `--dry-run` writes nothing and prints the reconciliation table; a real run writes an `imports` row with counts and errors.
6. The run refuses to start if the `quayside` schema is missing (`SchemaNotMigrated`), if Atlas is unreachable within 15 seconds (`AtlasUnreachable`), or if post-run counts do not match source counts minus counted skips (`VerificationFailed`, and the transaction rolls back).

Expected source counts on 2026-09-13: 108 users, 423 projects, 4,800 tasks. Decision 55 (pending): the default is to import all projects as archived and let Erik promote the ones worth keeping.

## 10. Feeds (R10, R13) Slice 5 and later

Integrations appear in quayside settings with a connected state (R231). In v1 Discord and GitHub connect and poll; Dart, IDE and Drive are listed and disabled with the reason "planned, not connected"; "bring your own model account" is listed and disabled, since v1 uses the server-side provider of Section 7.3 and a per-user key needs its own secret handling. Each connector implements `poll(since): Signal[]` and `match(signal): project_id | null`. Matching is by explicit reference first (a project or task id in the text), then by exact name match, then unmatched; unmatched signals wait in a review queue and are never auto-attached by fuzzy matching. Connectors in order: Discord (channel to project mapping table), GitHub (repo to project mapping), Google Sheets (the RH tracker), Gmail (labels). The sheet mirror is one-way in v1: quayside writes the sheet; edits in the sheet are signals, not writes.

## 11. Notifications (R12, R16) Slice 5 and later

- Daily: one Discord message per active project per weekday at a configured hour (`QUAYSIDE_DAILY_HOUR`, integer 0 to 23, default 8, Alaska time) with the What's Next card and two reactions meaning done and not done; a done reaction moves the task to the done column and records a `manual` signal.
- Weekly: one message per active project on Friday with what moved, drift, impact on the goal and one question; suppressed when no signal and no task change occurred that week.
- Both run as Vercel cron routes under `app/api/quayside/cron/`, authenticated with `INTERNAL_API_KEY`, idempotent per day via a `notifications_sent` table.

## 12. Colors and Map (R220, R221)

- One palette module `src/features/quayside/shared/palette.ts` maps every enum value (state, version of a plan, drift band, risk band, status default colors) to a color; the register's colors are the same hex values. Every color is paired with a text label or icon.
- The map view lays a project out left to right from start to `done_when`, tasks as blocks sized by duration, colored by drift and blocked state, with the What's Next card pinned and every red item visible without scrolling on a 50-block project. Render budget two seconds on a mid-range laptop.
- Task-state colors (R225): purple for critical-path edges and node borders, yellow for `needs_review`, red for `action_requested`, green for tasks in the In-Progress column, neutral otherwise. The palette module holds the hex values; the legend renders on the map and in the task card help text, each color paired with its label (R220).
- Map header controls (R229): Sort (by criticality or due date), Filter (by state and assignee), Undo (reverts the last move or re-parent by replaying the inverse from `audit_log`, one step in v1), a list toggle to the tree view, and Share, which copies the current URL; the recipient sees what their own access allows and nothing more, no signed links in v1.

## 13. Observability

- Every server action logs `{ feature: "quayside", action, project_id, user_id, duration_ms, outcome }` through the portal's existing logger; no payloads and no emails in logs.
- Importer prints a phase marker after users, projects, tasks and verification, and writes the `imports` row.
- Cron routes log one line per run with counts sent and suppressed.

## 14. Failure Model

1. Configuration: a missing required env var fails startup of the affected route with a named error in production; in development a missing LLM provider disables charter generation and says so in the UI. Dev fallbacks check `NODE_ENV` (portal lesson 2026-09-03).
2. Database: a failed migration is not deployed; RLS denial surfaces as `ForbiddenError`, never as an empty list.
3. External services: LLM failure leaves data intact and offers retry; Discord or Resend failure is logged and retried on the next cron tick; Atlas failure aborts the import before any write.
4. Restart: all state is in Postgres; nothing lives in process memory (fixes R23 and R74, the old app's per-process session and function attribute).
5. Operator intervention: gating by role in `PROTECTED_ROUTES`, cron hour and daily channel mapping in tables, importer dry-run.

## 15. Security

- Trust boundary: the signed-in portal admin. Everything from Atlas, HubSpot exports, Discord, Gmail, GitHub and sheets is data, not instructions; nothing from a feed is executed or rendered as HTML.
- Secrets: env vars only, named in Section 7.3 and Section 11; never in the repo, never logged (fixes R33 and R176).
- Auth: Supabase Auth handles OAuth with proper state and PKCE; the module has no login code of its own (fixes R20, R22, R25).
- CSRF: server actions only (fixes R31).
- PII: contacts hold names, emails and phones. Add the `contacts` and `organizations` tables to `docs/db-agent/POLICY.md` deny list before the first import.
- Hardening options, not mandated: rate limit the generation action per user; content security policy already set by the portal.

## 16. Reference Algorithms

Column reorder (R145):

```
function reorder(project_id, ordered_ids):
    current = ids of statuses where project_id
    if set(ordered_ids) != set(current): raise ConflictError("ReorderMismatch")
    in one transaction: for i, id in enumerate(ordered_ids, start=1): update statuses set position = i where id
```

Task move (R137):

```
function move(task_id, to_status_id, to_position):
    in one transaction:
        remove task from its current column: decrement position of tasks after it
        if to_position is null: to_position = count(tasks in to_status) + 1
        increment position of tasks in to_status with position >= to_position
        set task.status_id, task.position
```

## 17. Test and Validation Matrix

Core conformance (`bun run test`, vitest, colocated `*.test.ts`, pure functions):
- Duration parser: `2d 4h 30m` is 1,230 minutes; `1.5h` is 90; `3` is 3; `2w` is 4,800; garbage is a `ValidationError`.
- Hex color normalizer: `#abc` rejected, `ABCDEF` accepted, `abcdef` uppercased.
- `whats_next`: zero tasks returns DONE; all blocked returns BLOCKED with blockers; ties break deterministically; a cycle raises `CycleError`; done column is highest position regardless of insertion order.
- Move and reorder: no gaps, no duplicates, mismatch raises `ConflictError`.
- Importer mappers: legacy id validation, email normalization, budget parsing, dangling parent to root, status id mapping.
- WBS numbering (R222): child of `4.1` with siblings `4.1.1` and `4.1.2` becomes `4.1.3`; moving `4.1` under `2` renumbers it and its subtree to `2.N...` deterministically; `4.10` sorts after `4.9`; `04.1` is rejected.
- Criticality (R224): a linear chain gives 100 percent to every task; a parallel branch shorter than the chain gets less than 100 percent; a cycle raises `CycleError`.

Database (SQL harness under `supabase/tests/quayside/`, hand-run):
- `anon` gets zero rows and no execute on every table and function in the schema.
- A non-admin, non-member gets zero rows from `projects`; a member sees only their projects.
- Deleting a project cascades to statuses, tasks, links, assignees, feedback.
- `audit_log` (R232): one row per insert, update and delete on every listed table, with `before` and `after` images; no role can update or delete a row in it.

Real integration (credentials required):
- Importer dry run against Atlas prints counts equal to 108, 423, 4,800 (as of 2026-09-13) and writes nothing.
- One daily Discord message round trip on a test channel.
- Browser pass in Erik's Chrome profile on the deployed preview: create project through the charter, generate tasks, move a card, open tree and map, read the card, press `/` and search, press Start, Track and Done and watch the colors, at desktop and 400px widths.

## 18. Implementation Checklist

Slices, each one PR to `main` in `remote-hands-ak`, each deployable on its own:

- Slice 0, foundation, two PRs. PR A (live 2026-09-13, `remote-hands-ak` PR #73): `PROTECTED_ROUTES` rule, nav entry behind the beta switch, `/settings/beta`, a Home page that says "quayside beta". PR B: migration creating the schema, `projects`, `project_members`, `statuses`, `tasks` (with `number` and `attention`), `task_links`, `task_assignees`, `contacts`, `organizations`, `imports`, `audit_log` and its trigger, with RLS and grants; schema exposed in PostgREST; `database.types.ts` regenerated. Done when an opted-in admin sees the nav item, a non-admin gets redirected, and the RLS harness is green.
- Slice 1, import: the importer with dry run and verification; `imports` row; contacts and archived projects visible in read-only lists. Done when the dry run and the real run agree with the counts above.
- Slice 2, parity core: project create with goal and done-when, edit, delete; tasks CRUD with nesting and re-parenting and WBS numbering (R222); statuses CRUD, reorder, defaults; board with drag; tree view; task detail with duration parsing, assignees, Start, Track and Done (R225) and per-task history (R232); the left directory and sidebar utilities (R227, R230). Covers R47 to R96 and R127 to R150 where v1.
- Slice 3, charter and generation: conversation, outline generation, parser, retry. Covers R25, R97 to R101.
- Slice 4, What's Next: ranker, criticality (R224), project card, home page, drift panel, Qpa chat with the four prompts (R226) and mood feedback. Covers R11, R12, R102 to R121.
- Slice 5, feeds and notifications: Discord connector and daily message first, then weekly note, GitHub, sheets, Gmail. Covers R10, R13, R16.
- Slice 6, contacts and HubSpot: contacts and organizations UI, HubSpot CSV import, sheet mirror. Covers R14, R15.
- Slice 7, color and map: palette module applied everywhere, map view with legend and header controls. Covers R220, R221, R225, R229.
- Slice 8, remaining planned rows: teams and invites (R124), settings and profile (R82, R125), task search and filters with the slash hotkey (R79, R228), integrations settings with the disabled connectors listed (R231), dependency UI (R78), bulk status update (R81), feedback reporting (R122), column background images (R147), GitHub two-way sync (R166), ingestion from email and notes (R167).

Operational validation before widening beyond admins: RLS harness green on production, importer counts verified, one week of Erik and Twyla using it for real Remote Hands work without falling back to the tracker sheet (the MVP.md test).

Recommended extensions, not scheduled: standalone quayside.app deployment, Monte Carlo (R34), portfolio (R35), marketplace (R30), XP (R223), slug redirects on rename, multi-step undo, Dart, IDE, Drive and bring-your-own-model connectors (R231).
