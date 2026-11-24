# Agent skills setup: proposed AGENTS.md change

Date: 2026-11-24. Status: **proposal for Riley**. `AGENTS.md` says agents mustn't edit it, so this block isn't applied yet.

## What was set up

The engineering skills (`to-tickets`, `triage`, `to-spec`, `domain-modeling` and others) now read these three files:

- `docs/agents/issue-tracker.md`: issues live in GitHub Issues for `rrweller/Astro-seeing`, via the `gh` CLI. "PRs as a request surface" is off.
- `docs/agents/triage-labels.md`: the five default labels, `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human` and `wontfix`.
- `docs/agents/domain.md`: a single-context repo. Agents read `AGENTS.md`, `docs/RESEARCH.md` and `CONTEXT.md` (once it exists) first, and record decisions in `docs/decisions.md` rather than in a new `docs/adr/` (D37).

## Proposed addition to AGENTS.md

Append this at the end of `AGENTS.md`:

```markdown
## Agent skills

### Issue tracker

Issues live in GitHub Issues for rrweller/Astro-seeing (`gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` plus `docs/decisions.md` (no `docs/adr/`). See `docs/agents/domain.md`.
```

Until it's added, the skills still find the `docs/agents/` files by their standard paths. The block just makes them easier for agents to find.

## Uncertain / to check

- **Issues need GitHub auth on the CT.** The `gh` CLI needs a GitHub login there. In cloud sessions, issues go through the GitHub connector instead. I haven't checked whether `gh` is authenticated on CT 350.
- **The triage labels don't exist on GitHub yet.** `/triage` creates them the first time it applies one.
- **A file D36 refers to is missing.** D36 points to `docs/handoff_pivot.md`, which isn't in the repo on this branch.
