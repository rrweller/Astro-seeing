# Domain Docs

How the engineering skills should use this repo's domain documentation.

## Before exploring, read these

- **`AGENTS.md`**: authoritative. It covers the mission, the rules, the phases and the decisions made on 2026-09-26.
- **`docs/RESEARCH.md`**: the physics, data and validation reference. Read it in full before any work on physics, data selection, validation or thresholds. If it disagrees with a paper PDF, the PDF wins: fix the note, log it, and tell Riley.
- **`docs/decisions.md`**: the **only** decision log (D1, D2, …). Read the entries that touch the area you're working in.
- **`CONTEXT.md`** at the repo root, if it exists: the project glossary.

If `CONTEXT.md` doesn't exist, **carry on without comment**. `/domain-modeling` creates it lazily.

## Decisions: `docs/decisions.md`, never `docs/adr/`

This repo has no `docs/adr/`. When a skill says to write an ADR, append an entry to `docs/decisions.md` instead:

- **Format:** match the existing entries: `### D<n>. <title>`, then Options, Evidence, Choice and Who. Put it under a dated session heading.
- **Numbering:** first run `git fetch origin dev`, then use the next number after the highest D-number on `origin/dev` and on any open branches you know of. The CT and the cloud session both add entries.
- **Who:** say who decided: Riley, or "agent (provisional)" for an agent's choice within an approved phase. Anything marked [ASK] waits for Riley.

## File structure

```
/
├── AGENTS.md            ← authoritative rules (Riley edits it)
├── CLAUDE.md            ← @AGENTS.md plus the agent-skills config
├── CONTEXT.md           ← glossary (created lazily)
├── docs/
│   ├── RESEARCH.md
│   ├── decisions.md     ← the only decision log
│   └── agents/          ← skill config
└── src/astroseeing/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a hypothesis, a test name), use the term as `CONTEXT.md` or `docs/RESEARCH.md` defines it, for example J, J(h), h*, `cells` layout or validation box. Don't drift to synonyms.

## Flag decision conflicts

If your output contradicts a logged decision, say so explicitly rather than overriding it silently:

> _Contradicts D24 (at most 4 requests in flight), superseded by D37 and D39, because…_

Changing a method or constant that validated results depend on is an [ASK] (AGENTS.md).
