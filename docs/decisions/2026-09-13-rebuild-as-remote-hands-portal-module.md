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

Two things changed to make this urgent. Remote Hands is leaving HubSpot and needs a system of record for tasks and contacts, and Erik ruled on 2026-08-15 that quayside is that system. And the requirements register now exists: a Google Sheet of 209 rows (IDs run 9 to 232 with gaps, since the sheet and the planning chat share one number sequence) covering every behavior of the old app plus the vision material from 2018 to 2026, so a rebuild can be scoped against a list instead of against memory. Rows 222 to 232 came from Erik's hand-drawn wireframe of 2023-09-01 (found and filed in the Drive folder on 2026-09-13): WBS numbering, criticality per task, four task-state colors, the assistant's four prompts, a GitHub-style directory, slash search, map controls, sidebar utilities, an integrations footer and a margin note reading "All history recorded".

Three questions were open when this ADR was first written and are closed as of 2026-09-13:

- 55, which Atlas projects to import: all 423, imported as archived. Erik owns the triage through the "Keep? (Erik)" column on the register's second tab and said it is already handled; the question is not raised again.
- 56, who sees the beta: admins only, and each admin opts in for themselves. Erik's first look at the Slice 0 preview overturned the earlier idea of an email allowlist: "the beta feature needs to be under my profile. So I need to click on my name to add and go into settings to turn on this beta feature. Otherwise, the quayside side button should not be present." The switch shipped in `remote-hands-ak` PR #73 as `user_metadata.beta_features`; the admin role rule in the proxy still decides who may reach the route, the switch only decides who sees it.
- 57, XP for finished work (row 223): stays v2.

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

Build quayside as a beta route inside `remote-hands-ak` (Next.js, Supabase, Vercel), admin-gated and hidden behind a per-user beta switch under Settings, with its own `quayside` schema in the Remote Hands Supabase project and row level security on from the first table. The quayside repo holds the requirements sheet, this ADR and the spec until the module is extracted. Carry forward only the data model shape from the Postgres branch, renamed to the portal's conventions. From Atlas, import users as contacts and their projects with tasks; skip feedback and test projects.

Erik's words, 2026-09-13: "Versailles [Vercel] would be a great place to do things on if we can. And we'll build in the Kuwait side [quayside] repo, but we will... let's actually have this hosted as a beta feature on their Mote Hands [Remote Hands] app."

## Consequences

### Positive

- First deploy is one merge away from staff use; no new login, no new hosting account.
- The org boundary rule is satisfied structurally, not by policy.
- The HubSpot contacts get a home in the same database as the rest of Remote Hands.

### Negative

- Extraction to a standalone quayside.app is a future project with its own migration.
- Full parity including planned features is a long list; the spec slices it and Slice 0 is the first live validation, per decision 54 as revised. Slice 0 landed in two PRs: the gate, nav entry, opt-in switch and beta page went live on portal.remotehandsak.com on 2026-09-13 (PR #73, commit fb0eae6); the schema follows on its own PR so the first live check carried no database risk.
- The requirements sheet is a Google Sheet, outside git; the spec references row IDs and the sheet is the source of truth for them.

## Spec

- Spec: [docs/specs/2026-09-13-quayside-portal-module.md](../specs/2026-09-13-quayside-portal-module.md)

## References

- Requirements register: https://docs.google.com/spreadsheets/d/1xSLNc6Y9vlIriipU_w_GrWAKqodkFzcM9T3XNvOLHbE (rows 9 to 232)
- Wireframe sketch: "quayside.app Wireframe Sketch 2023-09-01.jpg" in the Drive folder "quayside.app Project" (rows 222 to 232)
- Old app Postgres model: `production-engineer/quayside` PR #8, `api/models.py`
- Source documents: Quay PM Tool UX draft (2018), Vision for quayside (2024), From Concept to Completion (2024), beadedcloud Vision: Future of Insights (2026)
- Prior ADR on the old stack: [2026-06-24-postgres-django-orm.md](./2026-06-24-postgres-django-orm.md) on the `pg-migration` branch

## Consensus

Erik Williams, by picker answers 51 to 54 on 2026-09-13; 55 and 57 by chat the same day; 56 revised on the Slice 0 preview the same day.
