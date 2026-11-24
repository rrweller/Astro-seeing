# Session handoff: keeping the roadmap current

Every session that works on a roadmap item, in the cloud or on the CT, reads this file first and follows it from start to finish.

`docs/roadmap.md` on `dev` is Riley's **single source** for three things: what runs next, where it runs, and the prompt that starts it. It is only useful if every session keeps it current, so this protocol is part of every task, not optional cleanup.

## Where status lives

Each roadmap item's status lives in exactly **two lines** of `docs/roadmap.md` on `dev`, and nowhere else:

1. **Its status-board entry:** a line like ``- `C5` · **ready** · cloud · … ``.
2. **Its diagram class line:** a line like `class C5 ready` in the Mermaid diagram.

Every status line has a spacer line next to it (a blank line on the board, a `%% ---` comment line in the diagram), so changes to two different items never touch adjacent lines and merge without conflicts.

## States

| State | Meaning | Who sets it, and when |
|---|---|---|
| `done` | Finished and merged into `dev` (or, for a CT job, its report is merged) | The session itself after its PR merges, or the next session's sweep |
| `review` | PR open, waiting for Riley | The session, when it opens its PR |
| `in-progress` | A session is working on it (includes long CT jobs, such as a running download) | The session, as its first write |
| `ready` | Every dependency is `done`: it can start now | Any session's sweep |
| `needs-you` | Waiting for something only Riley can do (a login, a merge, an approval, being at home) | Whoever finds the wait |
| `blocked` | At least one dependency isn't `done` | The initial state of a new item; the sweep keeps it accurate |

The colors in the diagram come from the `classDef` lines; don't change those.

## Status commits: the one direct write to `dev`

Riley allows sessions to commit status changes straight to `dev`, without a PR (D67), under these rules:

- **Only `docs/roadmap.md`, and only status lines:** the state word on the board line (plus the ticket or PR link on that line), and the state on the matching `class` line. Nothing else.
- **One commit per status change**, with message `roadmap: <ID> <old> → <new>` (several items in one sweep may share one commit: `roadmap: sweep (C4 ready, K5 ready)`).
- **Push to `origin dev`.** If the push is rejected, run `git fetch origin dev`, rebase the one commit onto it, and push again, up to 4 times. **Never force-push**; never touch `main`.
- Everything else (code, decisions, reports, new items, wording, prompts) goes through a PR into `dev` as usual.

Cloud sessions without `git push` rights to `dev` can make the same edit with the GitHub tools (`create_or_update_file` on `docs/roadmap.md`, branch `dev`, with the file's current SHA). If neither works, put the status change in the PR description and tell Riley.

## The protocol

### 1. At the start

1. Run `git fetch origin`, and read `docs/roadmap.md` from `origin/dev`.
2. **Sweep.** For every item, check whether its status is still true, and fix the ones that aren't, in one status commit:
   - `review` whose PR is merged → `done`;
   - `in-progress` whose PR is merged → `done`;
   - `blocked` whose dependencies are all `done` → `ready`;
   - `ready` whose dependency is no longer `done` → `blocked`.
   - Leave `needs-you` alone unless the thing it waited for has visibly happened (say so in the commit message).
3. **Claim your item:** status commit `<ID> ready → in-progress`. If it isn't `ready`, stop and tell Riley why, unless Riley's prompt says to go ahead anyway.
4. If the item has a GitHub ticket, also claim the ticket as `docs/agents/issue-tracker.md` describes. If it has none and your prompt says to create one, create it, then put its link on your board line in the same status commit or the next.

### 2. While working

- Don't change any other item's status, except in a sweep.
- If you find **new work** that belongs on the roadmap, add it in your PR as a new item:
  - an ID: next free `C<n>` for the cloud, `K<n>` for the CT, or `F1-<n>` for F1 build tickets;
  - a board line;
  - a diagram node and its edges;
  - a `class` line followed by a `%% ---` spacer;
  - its section with dependencies, model and effort, suggested skills (from the roadmap's skills guide), and a self-contained prompt that starts with the same first line as the existing prompts, followed by a `Skills:` line.
  
  New lines don't conflict with other sessions' status commits. A new item starts as `blocked` or `ready`.
- If you find the roadmap's **order or dependencies** are wrong, fix them in your PR and say so in the PR description.

### 3. At the end

1. Open your PR into `dev`. Its description says which roadmap item it completes.
2. Status commit `<ID> in-progress → review`, with the PR link on the board line.
3. Subscribe to the PR's activity (cloud sessions), so the merge wakes you.
4. **When the PR merges:** status commit `<ID> review → done`, then sweep. Items that only waited on yours become `ready`.
5. If the session ends before the merge, that's fine: the next session's sweep marks it `done`.

### 4. CT-only items (K items)

These follow the same steps, using `gh` and `git` on the CT. A long job (a download that takes days) stays `in-progress` until it finishes. Its report PR then moves it to `review` and `done` like any other item.

### 5. Things that need Riley

- When you're waiting on Riley (approval, a merge, a login), set your item to `needs-you`. Put what you're waiting for on the board line after the title, for example "needs you: merge PR #45".
- Status commits never decide anything. Anything that is an [ASK] in AGENTS.md still goes to Riley.
