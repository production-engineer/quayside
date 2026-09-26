# ADR: quayside as the AI project manager, one engine with one tenant per org

## ADR Author/s

Claude Opus 5.5 (drafting, decisions taken while Erik was away), Erik Williams (to review)

## Update Date

2026-09-26

## Status

Proposed. Written while Erik was away under his instruction of 2026-09-26: "If you have an important question, log it, make an educated and well reasoned decision, and continue forward." Every call made on his behalf is listed in "Open decisions for Erik" in the spec, with the alternatives and the reason.

## Who should be notified of ADR changes?

@production-engineer

## Context

Erik's framing, 2026-09-26, verbatim: "the AI project manager that has full visibility and actually gets projects done."

The idea is older than the phrase. The Keep notes put the problem in one line: "There is a constant lag the software has behind reality." They ask "What is quayside sensing? Project completion using GitHub, meeting minutes, documentation." On 2026-08-15 Erik said "the best task system lives in people's chats and and visible on google sheets. we should track these data sources and make sure they are as integrated as possible." On 2026-08-18: "Information needs to be crystalized for the task but expanded out for the next one to recrystalizee. This is why the quayside idea exists. Keep focus on what needs to be done but be able to reach out to all sources." The 2023 sketch's margin reads "All history recorded".

Today the loop runs by hand, across Claude Code sessions, skills and files: `/whats-next` ranks the critical path, `/sweep` labels stale items, `/kept` checks commitments, `/checkout` and the Keep portals claim work, `/close-session` checks that nothing is stranded. Each is useful and none of them remembers, sees every source, or acts between sessions. Two failure patterns keep recurring in memory: work claimed and then abandoned (a portal left `-in-progress` with an empty worktree, as the quayside schema portal was from 2026-09-14 to 2026-09-26), and work called done that was not deployed (the "done means deployed, ancestry check" rule exists because of it).

Constraints that bind the design:

- Decision 51 (2026-09-13): the quayside module lives in `remote-hands-ak` as an admin gated beta route; decision 52 puts its data in a `quayside` schema in the Remote Hands Supabase project.
- The org boundary, in Erik's words: "beadedcloud should not be running anything that is remotehands" (2026-08-21) and "Don't mix rh and bc creds please." (2026-09-07). A plan that spans both orgs loses every option in which one org hosts, stores or authenticates for the other.
- Erik's work spans three contexts: Remote Hands, beadedcloud, and personal (the quayside product itself, the `production-engineer` repos, Keep). Full visibility for Erik means all three; storage for any organization means one.
- Production writes, money, outbound messages, secrets and merges are human gated as a standing rule, restated in the 2026-09-26 away instruction.
- Decision 54: the smallest live slice first, validated by Erik before the next.
- Today's decision log entry 5 (session repos-07) already placed the AI project manager prototype in the quayside fork, because it reads all three contexts and the org boundary keeps cross-org tooling out of the Remote Hands portal repo.

## Options Considered

### Option 1: One cross-org agent and store in the quayside repo

- **Pros:** One view, one database, simplest to build.
- **Cons:** Puts Remote Hands and beadedcloud data and credentials in one store. Forbidden by the org boundary. Rejected on that alone.

### Option 2: Build the whole agent inside `remote-hands-ak`

- **Pros:** Honors decision 51 literally; staff login, cron and database exist.
- **Cons:** Remote Hands infrastructure would read beadedcloud and personal sources, the mirror image of what the boundary forbids. Serves Remote Hands only, so Erik's cross-org view still does not exist.

### Option 3: One engine, one tenant per org, composition only on Erik's machine (chosen)

- **Pros:** Each tenant has its own store, its own credentials and its own host, owned by that org. The Remote Hands tenant is the portal module of decision 51, unchanged in place and extended in schema. Erik's single view is composed at read time on his own machine and persists nothing combined. Sources that are cross-org by nature (Claude Code transcripts, Keep portals) are attributed to exactly one tenant by a deterministic rule before anything leaves the machine.
- **Cons:** Three deployments of one idea. The rules (attribution, staleness, action policy) must stay identical across the portal code and the local runner until the engine is extracted. The beadedcloud tenant has no hosted home yet.

### Option 4: Advisory only, no actions

- **Pros:** No approval queue, no executor, no new risk.
- **Cons:** Fails the second half of the brief, "actually gets projects done". The existing skills already advise.

## Decision

Adopt Option 3.

1. **The loop** is observe, plan, propose, act, verify. The agent writes freely only to its own tables (signals, evidence, proposals, runs). Every change to a human owned record or to anything outside the tenant is a proposal that a human approves, except action kinds Erik explicitly promotes after measured precision. Merges, deploys, money, outbound messages to anyone but Erik (GitHub comments included), sheet writes, secrets and deletes are never promotable.
2. **The Remote Hands tenant** lives where decision 51 put quayside: `remote-hands-ak`, schema `quayside`, Vercel cron for cloud sources. New tables are a delta on the 2026-09-13 spec Section 4, audited by the same `audit_log` trigger, with every agent-caused change carrying the `proposal_id` that authorized it.
3. **The local runner** (`pm/` in this repo, the `pm-prototype` line) runs on Erik's M5, reads local-only sources, attributes each item to one tenant, and in v1 ships only deterministic metadata to a tenant, never transcript content.
4. **The beadedcloud and personal tenants** are read-only reports from the local runner in v1. Where their stores live is an open decision, not a default.
5. **Models and runtime:** every model call goes through one provider neutral interface. The first model-using slice calls the Claude API directly (`claude-opus-5` for planning and triage, triage at low effort through the Message Batches API, server-side refusal fallbacks on); the raw-content reader has no tools. Remote Hands' Hermes stack (RHAi, on `rh-orchestrator` with the Mac Mini's local inference) joins the Remote Hands tenant only, as its Discord face, a long running connector host and a local-inference triage trial, once SSH access and the profile audit close. Erik asked on 2026-09-26 to use Hermes more ("I would like to use our Hermes more."); the reasons it is second and not first are in spec Section 8.1.
6. **First slice (PM0):** the local runner, read only, no model calls, producing one report per tenant of stale claims, done-without-evidence items and connector freshness, over sources already authenticated on the M5 (Keep portals, Claude Code session metadata, GitHub). Erik validates it by marking the flagged items true or false.

## Consequences

### Positive

- The org boundary is satisfied by construction: no store, credential or host serves two orgs.
- Decision 51 stands; the agent is how the portal module's Slice 5 feeds and Slice 4 assistant get built, not a second product.
- Every autonomous act is bounded by an allowlist and traceable from `audit_log` to an approval and its evidence.
- The first slice needs no production write, no new credential and no model spend.

### Negative

- Rules are implemented twice (portal and local runner) until extraction; a shared fixture suite is the control. Ticketed as debt with its upgrade path when the second hosted tenant exists.
- Erik's cross-org view exists only on his machine; nobody else sees across orgs, which is intended.
- Hermes is Remote Hands owned, so it can never be the runtime for the beadedcloud or personal tenants; the provider interface is what keeps one loop across tenants.
- The approval queue can become a new inbox. Promotion of routine kinds and a 72 hour expiry are the controls, and queue age is a tracked metric.
- Spec rows for this work are provisional (IDs from 236) because the requirements sheet could not be read in this session.

## Spec

- Spec: [docs/specs/2026-09-26-ai-project-manager.md](../specs/2026-09-26-ai-project-manager.md)
- Parent: [2026-09-13-rebuild-as-remote-hands-portal-module.md](./2026-09-13-rebuild-as-remote-hands-portal-module.md) and its spec

## References

- Requirements register: https://docs.google.com/spreadsheets/d/1xSLNc6Y9vlIriipU_w_GrWAKqodkFzcM9T3XNvOLHbE (not readable in this session; see the spec)
- `~/repos/Keep/quaysideNotes.md`, `~/repos/quayside_personal/TASKS.md` tasks 4 to 7, `~/repos/quayside_personal/MVP.md`
- `~/repos/Keep/decision-log-2026-09-26-repos-07.md`, entry 5

## Consensus

Pending Erik's review of the draft PR.
