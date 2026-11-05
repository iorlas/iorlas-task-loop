# Plan: a task-loop factory instance on the shelf repo (design only, no loop started)

Evidence tags: *read* = in code/docs, *session* = observed this session, *unverified* = no run or read exists.

## Goal

Run the task-loop on `~/Workspaces/shelf` so ready shelf beads are claimed, built in 2 slots, gated once, landed as a PR that the lead session merges after review and a green gate, and closed with the merge sha.

## Prerequisites

| Item | State | Evidence |
|---|---|---|
| task-loop 0.23.403 installed; `engine.land_mode: "push"\|"pr"` | shipped | session; read `contracts/config.py:171` |
| profile with `land_mode: "pr"` loads in the installed loader | shipped | session: `tl setup --plan --repo` printed `ok profile ... loads` (a positive run only) |
| PR land: opens a PR, waits, never merges; merge detected, bead closed with merge sha | unverified | only the config line was read, not the land code |
| shelf profile draft | drafted | branch `shelf-profile`, sha b0f4632 in `/Users/iorlas/Workspaces/shelf-profile`, not pushed |
| first shelf bead `shelf-42uy` (docs chore, acceptance set, no `auto` label) | filed | session: `tl task create --repo` |
| shelf gate = `uv run just check` (whole repo; prek pre-push runs the same via gate-state) | shipped | read shelf `justfile`, `.pre-commit-config.yaml` |
| hook chain on a slot push: dispatcher, `tl judge-push`, prek hook, once each | shipped | session; `prek install` refuses under tl's `core.hooksPath` |
| `bd ready` with `external:` edges | unverified | session: bd 1.3.1 ignores them; tl filter untested |
| `owner_author` = "Denis Tomilin" | unverified | no shelf comment by him found; taken from this repo's `.task-loop.json` |
| registering the repo with the loop | unverified | exact command not read |

## Steps, in order

1. Lead: file the first bead (`shelf-42uy`, done). It has no `auto` label, so no loop picks it.
2. Lead: draft the shelf profile (done, `shelf-profile`): 2 slots, setup `uv sync --locked`, one check `gate` = `uv run just check` with `run: gate`, `land_mode: pr`, `pick_label: auto`, `owner_author: Denis Tomilin`, default `land`.
3. Denis: push it as a shelf PR: `git -C /Users/iorlas/Workspaces/shelf-profile push --no-verify origin shelf-profile:shelf-profile`, open the PR against `main`. `--no-verify` is Denis-approved for this profile push; shelf's "never `--no-verify`" has this one stated exception.
4. Lead: review the PR, `just check` green, merge it (no auto-merge; the lead is the merger).
5. Denis: `tl setup --plan`, then `tl setup --apply` (host.json from the unity-lease answer; shelf has no Unity).
6. Lead: register the repo; `tl doctor`; confirm the slot hook order.
7. Lead: dry run: add label `auto` to `shelf-42uy`; `tl next` shows it pickable; test the `external:` filter.
8. Loop: `tl run-task` on that bead: plan, worker via delegate, gate, rebase, push the branch, open the PR. No tag, no release.
9. Lead: review the PR, merge it on a green gate; the loop sees the merge and closes the bead with the merge sha (unverified).
10. Lead: if clean, start a continuous loop by hand (`--wait-drained`).

## Risks

| Risk | Failure | Mitigation |
|---|---|---|
| Gate declared twice (engine check + prek pre-push) | a base push runs `just check` twice | one declared `gate`; prek skips an already-passed tree via gate-state |
| `land_mode` ignored or not honored by land code | worker pushes straight to shelf main | step 8 dry run on one bead, watch the first land; keep `auto` on that bead only |
| Merge never happens | land waits, slot stays held | lead merges promptly; PR-wait timeout and slot release unverified |
| `prek install` refuses under tl's hooksPath | shelf bd hooks / `bd dolt push` do not run in slots | engine pushes through tl's chain; Dolt push stays a main-checkout step (unverified) |
| `bd ready` ignores `external:` edges | a cross-repo-blocked bead is picked early | no `external:` edges on shelf beads until the filter exists |
| Shelf tests take every core | slots starve other work | 2 slots; the shelf test lock serializes gates |
| Dashboard beads edit shelf packages (bd memory) | two writers, one package | keep factory beads package-disjoint from open dashboard work |
| Shelf tag or release | a tag nobody asked for | the loop never tags; bead text says so; tell the lead first |
| Wrong `owner_author` | owner comments not recognized as instructions | confirm the string against a real shelf comment by Denis |
