# Issue tracker: GitHub

Issues, specs and wayfinder tickets live as GitHub issues on `rrweller/Astro-seeing`.

Two environments use them:

- **Cloud planning sessions** use the GitHub MCP tools (`mcp__github__issue_write`, `issue_read`, `list_issues`, `add_issue_comment`, `sub_issue_write`). There's no `gh` there.
- **The CT** (`/home/astro-seeing`) uses the `gh` CLI, logged in as rrweller. `gh` infers the repo from `git remote -v`.

## Conventions

- **Create an issue:** `gh issue create --title "..." --body "..."` (use a heredoc for multi-line bodies), or `issue_write` with `method: create`.
- **Read an issue:** `gh issue view <number> --comments`, or `issue_read` with `get` and `get_comments`.
- **List issues:** `gh issue list --state open --json number,title,body,labels,comments`, with `--label` and `--state` filters. In the cloud, use `list_issues`.
- **Comment:** `gh issue comment <number> --body "..."`, or `add_issue_comment`.
- **Labels:** `gh issue edit <number> --add-label "..."` / `--remove-label "..."`, or `issue_write` with `method: update`.
- **Close:** `gh issue close <number> --comment "..."`, or a comment and then `issue_write` with `state: closed` and a `state_reason`.

**Where a ticket runs.** Every ticket has exactly one of these labels:
- `runs-on:cloud`: needs only the repo.
- `runs-on:ct`: needs `/data`, `/staging`, the manifest, CDS access, `external/` or `papers/`.

The ticket body also says where it runs, what data it uses, its acceptance test and what to report.

**Never put secrets, tokens or paper text in an issue.** Issues are as public as the repo.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR:** `gh pr view <number> --comments`, and `gh pr diff <number>` for the diff.
- **List external PRs for triage:** `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`, then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR` or `NONE` (drop `OWNER`, `MEMBER` and `COLLABORATOR`).
- **Comment, label, close:** `gh pr comment`, `gh pr edit --add-label` / `--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either. Resolve it with `gh pr view 42`, falling back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read the issue with its comments.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue, with **child** issues as its tickets.

- **Map:** one issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body.
- **Child ticket:** a sub-issue of the map.
  - In the cloud, use `issue_write` with `parent_issue_number`, or `sub_issue_write`. On the CT, use `gh api` on the sub-issues endpoint.
  - Put `Part of #<map>` at the top of the body.
  - Labels: `wayfinder:<type>` (`research`, `prototype`, `grilling` or `task`), plus a `runs-on:*` label.
- **Blocking:** a `Blocked by: #<n>, #<n>` line at the top of the child's body. **This line is the source of truth**, because the cloud session can't set native dependencies.
  - The CT may mirror it as a native dependency: `gh api --method POST repos/rrweller/Astro-seeing/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`. The blocker's database id comes from `gh api repos/rrweller/Astro-seeing/issues/<n> --jq .id`.
  - A ticket is unblocked when every issue on its `Blocked by` line is closed.
- **Frontier query:** list the map's open sub-issues and drop any that have an open blocker or an assignee. The first in map order wins. The CT considers only `runs-on:ct` tickets, and the cloud session only `runs-on:cloud` ones.
- **Claim:** assign the ticket to rrweller (`gh issue edit <n> --add-assignee @me`, or `issue_write` with `assignees`), and comment saying which environment claimed it. Claiming is the session's first write.
- **Resolve:**
  1. Comment with the answer.
  2. Close the issue.
  3. Add a context pointer (the gist and a link) to the map's Decisions-so-far.
  4. If the answer is a non-trivial decision, it also gets a D-number in `docs/decisions.md` (see `docs/agents/domain.md`).
