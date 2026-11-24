@AGENTS.md

## Agent skills

### Issue tracker

GitHub Issues on `rrweller/Astro-seeing`, used from both the cloud planning session and the CT. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. The glossary is `CONTEXT.md` at the root, created when first needed. Decisions go in `docs/decisions.md` (D-numbers) only, never in `docs/adr/`. See `docs/agents/domain.md`.

### Roadmap and session handoff

`docs/roadmap.md` on `dev` is Riley's single source for what runs next, where, and with which prompt. Every session that works on a roadmap item, ticket or PR reads `docs/agents/session-handoff.md` first and follows it: claim the item at the start, keep its status current, and delete it from the roadmap when its PR merges (D67, D70).
