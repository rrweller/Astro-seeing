# Session handoff: keeping the roadmap current

Every session that works on a roadmap item, in the cloud or on the CT, reads this file first and follows it from start to finish.

`docs/roadmap.md` on `dev` is Riley's **single source** for three things: what runs next, where it runs, and the prompt that starts it. **It lists only unfinished work** (D70): once an item is finished, its entry is deleted. It's only useful if every session keeps it current, so this protocol is part of every task, not optional cleanup.

## Where status lives

Each roadmap item's status lives in exactly **two lines** of `docs/roadmap.md` on `dev`, and nowhere else:

1. **Its status-board entry:** a line like ``- `C5` · **ready** · cloud · … ``.
2. **Its diagram class line:** a line like `class C5 ready` in the Mermaid diagram.

Every status line has a spacer line next to it (a blank line on the board, a `%% ---` comment line in the diagram), so changes to two different items rarely touch adjacent lines.

**Dependencies are the diagram's arrows.** `C8 --> K8` means K8 waits for C8. Deleting a finished item deletes its arrows, so an item whose incoming arrows are all gone has nothing left to wait for. The tables' "Depends on" column says the same in words. Some items also wait on something that isn't an item, written on the item's board line or table row (for example K11's "your [ASK] on the size").

## States

| State | Meaning | Who sets it, and when |
|---|---|---|
| `review` | PR open, waiting for Riley | The session, when it opens its PR |
| `in-progress` | A session is working on it (includes long CT jobs, such as a running download) | The session, as its first write |
| `ready` | No arrow points to it, and nothing else it waits for is pending: it can start now | Any session's sweep |
| `needs-you` | Waiting for something only Riley can do (a login, a merge, an approval, being at home) | Whoever finds the wait |
| `blocked` | At least one arrow still points to it | The initial state of a new item; the sweep keeps it accurate |

There is no `done` state: a finished item is **deleted**, as described below. The colors in the diagram come from the `classDef` lines; don't change those.

## Deleting a finished item

An item is finished when its PR has merged into `dev` (for a CT job, its report PR), or, for an item with no PR (a login, a restart), when the session that did it or Riley confirms it. Then delete **everything** about it from `docs/roadmap.md`:

- **Board:** its line and the blank line after it.
- **Diagram:**
  - its node line in the `cloud` or `ct` subgraph;
  - every arrow that starts or ends at it. Split a chain such as `C3 --> C4 --> F1` so the remaining arrows stay (`C4 --> F1`);
  - its `class` line and the `%% ---` after it.
- **Work order:** its row in the cloud-waves or CT table, its place in the CT order list, and its ID in other rows' "Depends on" cells.
- **Prompts:** its whole `### <ID>.` section, including the prompt box.
- **Reserved D-numbers:** its row.
- **Mentions in other items' prompts:**
  - leave prompt text that still makes sense, such as "the merged code from C9";
  - remove a "Depends on <ID>" phrase from another item's header line.

## Direct writes to `dev`

Riley allows two kinds of change to be committed straight to `dev`, without a PR (D67, D70):

1. **Status changes:** the state word on the board line (plus the ticket or PR link on that line), and the state on the matching `class` line.
2. **Deleting a finished item:** exactly the lines listed under "Deleting a finished item", nothing more.

Rules for both:

- **Only `docs/roadmap.md`.** Nothing else in it or in any other file.
- **Commit messages:**
  - a status change: `roadmap: <ID> <old> → <new>`;
  - a deletion: `roadmap: remove <ID> (#<PR> merged)`, or `(finished: <what happened>)` when there is no PR;
  - a sweep may combine several in one commit: `roadmap: sweep (remove C5; C10 ready, K5 ready)`.
- **Push to `origin dev`.** If the push is rejected:
  1. run `git fetch origin dev`;
  2. rebase your one commit onto it;
  3. if the rebase conflicts on a neighbouring line, keep the other session's change and reapply yours;
  4. push again, up to 4 times.

  **Never force-push**; never touch `main`.
- Everything else (code, decisions, reports, new items, wording, prompts) goes through a PR into `dev` as usual.

Cloud sessions without `git push` rights to `dev` can make the same edit with the GitHub tools (`create_or_update_file` on `docs/roadmap.md`, branch `dev`, with the file's current SHA). If neither works, put the change in the PR description and tell Riley.

## The protocol

### 1. At the start

1. Run `git fetch origin`, and read `docs/roadmap.md` from `origin/dev`.
2. **Sweep.** For every item, check that its status is still true, and fix the ones that aren't, in one commit:
   - `review` or `in-progress` whose PR is merged → **delete the item**;
   - `blocked` with no arrows left pointing to it and nothing else pending → `ready`;
   - `ready` that has an arrow pointing to it again → `blocked`.
   - Leave `needs-you` alone unless the thing it waited for has visibly happened. If that finished the item, delete it; otherwise move it on. Either way, say so in the commit message.
3. **Claim your item:** status commit `<ID> ready → in-progress`. If it isn't `ready`, stop and tell Riley why, unless Riley's prompt says to go ahead anyway.
4. If the item has a GitHub ticket, also claim the ticket as `docs/agents/issue-tracker.md` describes. If it has none and your prompt says to create one, create it, then put its link on your board line in the same status commit or the next.

### 2. While working

- Don't change any other item's status, except in a sweep.
- If you find **new work** that belongs on the roadmap, add it in your PR as a new item:
  - an ID: next free `C<n>` for the cloud, `K<n>` for the CT, or `F1-<n>` for F1 build tickets. Never reuse a deleted item's ID; check git history if unsure;
  - a board line, followed by a blank line;
  - a diagram node and its arrows;
  - a `class` line followed by a `%% ---` spacer;
  - a row in the cloud-waves or CT table;
  - its section: a line saying whether it needs Riley and what it depends on, then a self-contained prompt that starts with the same first sentence as the existing prompts, followed by a `Skills:` line.
  - If the item's main workflow is a **slash-command skill** (`grill-with-docs`, `to-spec`, `to-tickets`, `implement`), the prompt starts with that command on the same line as the first sentence, for example `/mattpocock-skills:implement Read docs/agents/session-handoff.md …`. Only Riley can start these skills, by sending the command, so a prompt that doesn't start with one can't use them. Use at most one per prompt. If an item needs a second one (C10's `to-tickets`), the prompt tells the session to ask Riley to send it as a later message.

  A new item starts as `blocked` or `ready`.
- If you find the roadmap's **order or dependencies** are wrong, fix them in your PR and say so in the PR description.
- **Where a skill's defaults and this repo's docs differ, the docs win:**
  - "ADR" means a D-number in `docs/decisions.md` (`docs/agents/domain.md`);
  - issues follow `docs/agents/issue-tracker.md`: the `Blocked by:` line in the body is the source of truth, plus a `runs-on:*` label;
  - every item ends with a PR into `dev` and the steps below, even where a skill says only "commit".

### 3. At the end

1. Open your PR into `dev`. Its description says which roadmap item it completes.
   - **Don't delete your own item in the PR.** It stays on the board as `review` until the merge.
   - If your PR adds new items or edits other parts of the roadmap, that's fine.
2. Status commit `<ID> in-progress → review`, with the PR link on the board line.
3. Subscribe to the PR's activity (cloud sessions), so the check result and the merge wake you.
4. **Merge it yourself** if your prompt authorizes it and every condition under "Merging into `dev`" below holds. Otherwise Riley merges: set your item to `needs-you` ("needs you: merge PR #N").
5. **When the PR merges:**
   1. close the ticket, if your item has one, with a comment linking the PR (PRs into `dev` don't close issues, because `main` is the default branch);
   2. delete your item, in one direct commit to `dev`: `roadmap: remove <ID> (#<PR> merged)`;
   3. sweep. Items whose last incoming arrow was yours become `ready`.
6. If the session ends before the merge, that's fine: the next session's sweep deletes the item.

### Merging into `dev` (D93)

An agent may squash-merge a PR into `dev` itself only when **every** condition holds:

1. **Authorized:** the prompt Riley started the session with says it may (the F1 cloud prompts and the coordinator prompt do). Claude Code merges only on the user's own ask, so this file alone isn't enough.
2. **Nothing for Riley:** the item's roadmap section doesn't say "Needs your approval", and the PR carries no [ASK] from AGENTS.md, no choice its ticket leaves to Riley, and no change to `AGENTS.md`.
3. **Green:** the `tests` check (`.github/workflows/tests.yml`: lint plus the full test suite) has passed on the PR's current head commit.
4. **Reviewed:** `mattpocock-skills:code-review` ran on the branch against `origin/dev`, and every finding is fixed or answered in the PR description, with nothing serious left open.
5. **Clean:** GitHub shows no merge conflict.

Never merge into `main`, and never force-push. After the merge, tell Riley which PR merged. Riley can revert any merge.

### 4. CT-only items (K items)

These follow the same steps, using `gh` and `git` on the CT. A long job (a download that takes days) stays `in-progress` until it finishes. Its report PR then moves it to `review`, and the merge deletes it like any other item.

### 5. Things that need Riley

- When you're waiting on Riley (approval, a merge you may not do yourself, a login), set your item to `needs-you`. Put what you're waiting for on the board line after the title, for example "needs you: merge PR #45".
- Status commits and deletions never decide anything. Anything that is an [ASK] in AGENTS.md still goes to Riley.
