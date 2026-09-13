# ADR: Rebuild quayside as a beta module inside the Remote Hands portal

## ADR Author/s

Erik Williams (decisions), Claude Fable 5.1 (drafting)

## Update Date

2026-09-13

## Status

Accepted

## Who should be notified of ADR changes?

@production-engineer

## Context

quayside is a Django plus MongoDB app built in 2023 and 2024 by a student team and a loose volunteer group. Erik's verdict on 2026-09-13: "the software was written by ameteurs." The production Google Cloud project is being allowed to lapse on purpose, the Mongo to Postgres migration (fork PR #8) never merged, and a code sweep the same day found seven security defects in the auth path (constant OAuth state, one secret used as both JWT signing key and Fernet key, a committed Django secret, two endpoints that skip the membership check, cookie mutations with no CSRF token, client secrets printed to stdout).

Two things changed to make this urgent. Remote Hands is leaving HubSpot and needs a system of record for tasks and contacts, and Erik ruled on 2026-08-15 that quayside is that system. And the requirements register now exists: a Google Sheet of 198 rows covering every behavior of the old app plus the vision material from 2018 to 2026, so a rebuild can be scoped against a list instead of against memory.

Constraints:

- Remote Hands data may not run on beadedcloud infrastructure (Erik, 2026-08-21).
- The first real user is Remote Hands operations: Erik, Twyla, and the HubSpot exit.
- Erik wants Vercel. Full parity with everything the old app does or planned to do is the destination, but the first deploy is the smallest thing that can be validated live; the feature list is worked through slice by slice after that (decision 54, revised the same day: "I know I said everything in the app, but I really think that we should get started with a small thing first, and we're just gonna chug through that feature list as we go").
- From the old database he wants only "people's contact info and the projects they were working on."

## Options Considered

### Option 1: Rescue the Django app

- **Pros:** Postgres branch is green with 103 tests; no new stack to learn.
- **Cons:** Keeps the bottom-up architecture the vision rejects; seven auth defects to unpick; Cloud Run hosting is gone; Python is foreign to every other Remote Hands app.

### Option 2: New standalone Next.js app in the quayside repo, deployed to quayside.app on Vercel

- **Pros:** Clean product boundary; the domain is already owned.
- **Cons:** Needs its own login and user store on day one; Remote Hands staff would have a second place to sign in; nothing connects it to the portal data it is meant to replace HubSpot for.

### Option 3: Beta module inside the Remote Hands portal (chosen)

- **Pros:** Staff login, roles and deploy pipeline exist; merge to main ships; the ABA app already proved the pattern of a separate schema in the same Supabase project; hosting is Remote Hands owned by construction.
- **Cons:** quayside as a product is coupled to one customer's repo until it is extracted; the portal's conventions constrain the code; quayside.app has nothing to point at until the module is public.

### Option 4: Do Nothing

- **Pros:** Zero cost.
- **Cons:** HubSpot exit has no destination; the task system stays in markdown files and chat scrollback.

## Decision

Build quayside as a beta route inside `remote-hands-ak` (Next.js, Supabase, Vercel), behind a feature flag, with its own `quayside` schema in the Remote Hands Supabase project and row level security on from the first table. The quayside repo holds the requirements sheet, this ADR and the spec until the module is extracted. Carry forward only the data model shape from the Postgres branch, renamed to the portal's conventions. From Atlas, import users as contacts and their projects with tasks; skip feedback and test projects.

Erik's words, 2026-09-13: "Versailles [Vercel] would be a great place to do things on if we can. And we'll build in the Kuwait side [quayside] repo, but we will... let's actually have this hosted as a beta feature on their Mote Hands [Remote Hands] app."

## Consequences

### Positive

- First deploy is one merge away from staff use; no new login, no new hosting account.
- The org boundary rule is satisfied structurally, not by policy.
- The HubSpot contacts get a home in the same database as the rest of Remote Hands.

### Negative

- Extraction to a standalone quayside.app is a future project with its own migration.
- Full parity including planned features is a long list; the spec slices it and Slice 0 (schema, gate, nav, an empty beta page) is the first live validation, per decision 54 as revised.
- The requirements sheet is a Google Sheet, outside git; the spec references row IDs and the sheet is the source of truth for them.

## Spec

- Spec: [docs/specs/2026-09-13-quayside-portal-module.md](../specs/2026-09-13-quayside-portal-module.md)

## References

- Requirements register: https://docs.google.com/spreadsheets/d/1xSLNc6Y9vlIriipU_w_GrWAKqodkFzcM9T3XNvOLHbE (rows 9 to 221)
- Old app Postgres model: `production-engineer/quayside` PR #8, `api/models.py`
- Source documents: Quay PM Tool UX draft (2018), Vision for quayside (2024), From Concept to Completion (2024), beadedcloud Vision: Future of Insights (2026)
- Prior ADR on the old stack: [2026-06-24-postgres-django-orm.md](./2026-06-24-postgres-django-orm.md) on the `pg-migration` branch

## Consensus

Erik Williams, by picker answers 51 to 54 on 2026-09-13.
