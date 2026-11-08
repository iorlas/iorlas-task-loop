# Where delegate lives (tl-w7lt.37, DQ-02)

Decision for Denis. Nothing moves until he picks; this note only compares.

## State today (checked 2026-11-08, main 7b9dd20d6)

- delegate **already is** an isolated workspace package of this repo: `packages/delegate` (`tldelegate`, no runtime dependencies, stdlib
  only), moved from `src/delegate` by S1c (#679). The engine reaches it through `delegate.api` only (`docs/contracts/delegate-api.md`);
  its tests keep their own hermetic HOME/CLI isolation (`packages/delegate/tests/conftest.py`, `hermetic.py`).
- There is no separate `iorlas-delegate` checkout any more on the devbox; the name survives only in the marketplace plugin data folder
  and in older architecture docs (`docs/architecture/c4-delegate.md`, the review notes).
- So Denis's 2026-11-04 words ("merge Delegate into the task-loop repo, keep it isolated as a package") are Option A below, and it is done.
  What is open is whether to go on from there to the shelf ("maybe move it to Shelf, potentially").

## Options

| | A. Stay: isolated package in this repo (today) | B. Move to the shelf |
|---|---|---|
| Release drift between two repos | none: one `dev/release.py`, one version | returns: delegate gets its own tag, the engine pins it |
| Shelf constitution | not involved | Article VI/VIII: a shelf piece is generic substrate pulled by consumers (DEEP, STABLE, WINS; derived consumer list; zero active consumers means orphaned). delegate is a product: accounts, skills, a plugin; its only consumer is task-loop. Article III: no flags, no shims; the delegate JSON contract and account config are exactly the optionality the shelf forbids |
| Isolation | enforced here by import-linter (`package-*` contracts) and `delegate.api` | would be a repo boundary, stronger but paid with release steps on every change that touches the seam |
| Cost | zero | a Kind for products in the shelf catalog (none exists), a catalog entry, a tag flow, a second CI-less repo to gate, the plugin data folder rename |
| Who else uses it | nobody (Denis: "no one uses it, aside from us") | nobody: no consumer demonstrably breaks without it (Article V keeps it `candidate`, inert) |

## What breaks

- **B:** every change to the delegate seam becomes two commits in two repos plus a tag; the factory (which releases itself through
  `dev/release.py` in one clone) would need a cross-repo release; the shelf gains a product it has no Kind for, and by its own Article VIII
  the only consumer is us, so a protection row for it is not earned.
- **A:** nothing breaks. The cost is that delegate's tests and code stay in the engine repo's gate (its tests are skipped unless a change
  touches `packages/delegate`, `just test-delegate`), which the factory already accepts.

## Recommendation

**A, final.** The shelf is for generic, multi-consumer substrate; delegate is a single-consumer product whose contract is already
enforced in-repo. Moving it would reintroduce the release drift Denis wanted gone. If a second consumer ever appears, extract its
generic pieces (not the accounts) to the shelf then, as any `any-*` piece.

Consequence if Denis picks A: close tl-w7lt.37 with his pick quoted, and unblock tl-w7lt.38.11 (LANEPURGE, canonical account/track/loop names), which
waits on this decision. If he picks B, S1c is undone as a plan and a Kind for products must be decided first in the shelf.
