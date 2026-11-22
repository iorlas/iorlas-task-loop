# Shelf proposal: a new task branch tracks its base (L52 part c)

Status: proposed. The owner decides; nothing here is built.

## Problem
`git-porcelain` `take_branch` creates a missing branch with `checkout -b <branch> <base-sha>`. A sha base sets no upstream, so in a
factory slot `task/<id>` has none. blueprint's `secret_scan range` and any-gate's `changed` / `state` read `@{upstream}`; with none,
the scan is the full-history scan ("run too much") and the gate's change-selection runs every step. Any repo with one historic false
positive fails check 1 in every slot, and every slot pays the full scan.

## Options
| option | change | cost |
|---|---|---|
| A. shelf `take_branch` accepts `track: str \| None` (a remote-tracking ref); the factory passes `origin/main` for a new branch | git-porcelain API + real/fake + a taskloop call | the proper fix: one owner (the checkout operation), and every gate read of upstream then works |
| B. blueprint scan reads `origin/<target>` when there is no upstream | blueprint | hides the missing upstream; a second reader of "the base" |
| C. nothing; each repo keeps a `.gitleaks.toml` | none | done for this repo; full scan stays (about 6 s here, grows with history) |

Recommendation: A. Until it lands, C (`.gitleaks.toml`) is in place, so the gate no longer fails for this reason.
