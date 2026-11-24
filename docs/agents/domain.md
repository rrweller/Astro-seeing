# Domain Docs

How the engineering skills should read this repo's domain documentation before exploring the code.

This is a **single-context** repo: one `CONTEXT.md` at the root, and one decision log.

## Read these first

- **`AGENTS.md`**: the mission, the rules, and the phases and gates. The rules there win over any skill's defaults.
- **`docs/RESEARCH.md`**: the physics, data sources, validation targets and thresholds. Read it in full before working on physics, data selection, validation or thresholds.
- **`CONTEXT.md`** at the repo root, if it exists: the glossary.
- **`docs/decisions.md`**: the decision log, which takes the place of `docs/adr/` here. Read the entries (D1, D2, …) that touch the area you're about to work in.

If `CONTEXT.md` doesn't exist, **proceed silently**. Don't flag that it's missing, and don't suggest creating it up front. The `/domain-modeling` skill creates it when a term actually gets resolved.

## Recording decisions

**There is no `docs/adr/` in this repo, so don't create one.** Wherever a skill says "write an ADR" or "record an ADR", add an entry to `docs/decisions.md` instead:

- Use that file's format: the next `### D<n>.` number under a dated `##` session heading, with options, evidence, choice and who decided.
- Mark the agent's own choices "agent (provisional)".
- Anything that `AGENTS.md` marks [ASK] waits for Riley. Log it as pending, and don't decide it yourself.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis or a test name), use the term as `CONTEXT.md` or `docs/RESEARCH.md` defines it, for example J, J(h), h*, good night or ground layer. Don't drift to synonyms.

If the concept you need isn't defined anywhere yet, that's a signal. Either you're inventing language the project doesn't use (reconsider), or there's a real gap (note it for `/domain-modeling`).

## Flag decision conflicts

If your output contradicts an entry in `docs/decisions.md` or a decision in `AGENTS.md`, say so explicitly rather than silently overriding it:

> _Contradicts D4 (tropopause bound at 500 hPa), but worth reopening because…_

Changing a method or constant that validated results depend on is an [ASK] under `AGENTS.md`.
