# REWRITE-VOCAB: one vocabulary per end state, and the cut order (tl-7i9k.31)

Design note only; no code moves with it. The bead's acceptance: `grep '"(FAULT|PAUSE|ASK|WAIT)_'` in app is empty with a rule test, and the `Kind[...]` lookup is gone. The canonical ideas are M-151, M-160, M-165, M-218, M-244 and M-381 of `docs/architecture/review-ledger.md`.

## What is true today (origin/main, 2026-11-06)

- `Kind` (`contracts/kinds.py`) is a plain `enum.Enum` of 27 members with lowercase values (`"fault_infra"`). It is the stored end of a run. `Kind.CUT` has no raiser (the file says so); `ENGINE_CRASH` and `FAULT_CRASHED` are two crash kinds.
- The app and domain spell a kind by NAME as an uppercase string in **99 literal sites in 34 files**: 75 in app and cli, 24 in domain (`domain/lanes/policy.py` 17, `domain/lanes/says.py` 7, `app/land/pr_land.py` 7, `app/land/tree.py` 6). They travel as `kind: str` (28 parameters in app/run and app/land alone) and are converted late by the single lookup `Kind[kind]` (`app/run/blocked.py:35`). Eight `blocked_for(why, kind: str)` copies sit in host Protocols.
- Families are read three ways: `kind.name.startswith("FAULT_")` (`app/run/outcomes.py`, `closer_settle.py`, `lane_acts.py`), `record.kind.startswith("ask_")` over stored values (`contracts/attemptrows.py`, `domain/outcome.py`, `app/loop/verdict.py`), and the tuples `ASKS`, `PAUSES`, `FAULTS` built from names in `kinds.py`.
- The other vocabularies are in three states: `Step`, `Cause`, `CheckStatus`, `WaitWhat` already are `StrEnum` in `contracts/enums.py`; `Cause` is also a `Literal` in `contracts/answers.py` (two definitions of one idea); `SlotState` is a `Literal` in `contracts/slots.py`; `LoopExit` is an event record, not a vocabulary.

## Target

1. `Kind` becomes a `StrEnum` whose value is today's stored value (no data change), with the family as data: `Kind.family` (`FINISH | ASK | PAUSE | FAULT | OTHER`) set in one table beside the members. `ASKS`, `PAUSES`, `FAULTS` and every `startswith` are derived from or replaced by `kind.family`; the `ASK_NAME` table (27 entries, 23 of them `""`) becomes an attribute on the four ask members.
2. `blocked_for(why, kind: Kind)` everywhere (the eight Protocol copies and `run/blocked.py`); the call sites pass `Kind.FAULT_SLOT`. `Kind[kind]` is deleted. A kind read from a stored row goes through the one `kind_named` that exists.
3. One crash classification: `ENGINE_CRASH` and `FAULT_CRASHED` get one `classify_crash` and a recorded decision on whether they are one kind with a cause (M-218); until then neither is renamed.
4. `Cause` is defined once (the `StrEnum`; `answers.py` imports it). `SlotState` moves to `StrEnum` next to `Step` and `CheckStatus`. `LoopExit` stays a record; its `reason` gets a `StrEnum` only if the census finds string sites for it (not counted here).
5. `Kind.CUT` is deleted with its `Rule` row in `domain/outcome.py` once the trial cell that mentioned it is confirmed gone.

## Rule test (the acceptance)

`tests/rules/test_kind_vocabulary.py`, AST-based like `test_enumtotal.py`: no string constant in `src/taskloop/{app,cli,domain}` equals a `Kind` name or value, no `startswith` on a kind, no `Kind[` subscript. It starts as a ratchet at the census above (99, 3 `startswith` families, 1 subscript) and may only fall, so the work can land in pieces; the last piece sets it to zero.

## Cut order (each step lands green on its own)

1. **Rule test as a ratchet** at today's count, plus `Kind` to `StrEnum` with identical values. Nothing else moves; every existing `Kind.X.value` and `kind_named` caller still works. The wire/golden tests prove the stored values did not change.
2. **`blocked_for(kind: Kind)` and the callers in `app/land`** (about 35 sites, the eight Protocols): they are one slice, and the bulk of the 75.
3. **`app/run`, `app/write`, `app/plan`, `app/review`** (about 30 sites, `lane_acts.py` and `worker_request.py` first: they hold the `startswith("FAULT_")` reads).
4. **`domain/lanes`** (24 sites, `policy.py` and `says.py`): these return kind names that the app converts; they return `Kind` instead, which removes the last `Kind[...]`.
5. **Families as data**: `kind.family`, delete `ASKS/PAUSES/FAULTS/ASK_NAME` builders and the `startswith` reads in `contracts/attemptrows.py`, `domain/outcome.py`, `app/loop/verdict.py`.
6. **The small ones**: `Cause` once, `SlotState` to `StrEnum`, `Kind.CUT` deleted, `classify_crash`. The ratchet is set to zero.

## Risks and what to check

- **Persisted values.** Stored rows hold lowercase values; the strings being removed are uppercase names that never reach disk. A `StrEnum` with the same values changes no row. A test that round-trips every member through `kind_named` guards it.
- **Typing that hides a wrong kind.** Today a typo in `"FAULT_SLOTT"` fails at runtime in `Kind[...]`; after step 2 it fails in pyrefly. That is the point, but it means step 2 needs `just types-all` on the whole tree, not only the changed files.
- **Domain returning names.** `domain/lanes` is imported by `app`; changing its return type is a contract change within the layers, which `.importlinter` allows (domain does not import app), but every test double of those functions changes in step 4.
- **Overlap.** LANEPURGE renames `lane` words in `domain/lanes`, `lane_acts.py` and `Cause.LANE_OUT`; run step 4 before LANEPURGE's domain cut or after it, not at the same time, and keep the two PRs on disjoint files.

## Decisions for the owner (a recommendation each)

- **One crash kind or two (M-218).** Recommend one kind `CRASHED` with a `cause` (engine or process), since both are retried the same way; this changes stored values, so it ships after step 6 with a reader for the old two values.
- **`Kind.family` or separate enums per family.** Recommend the attribute: the dashboard and report read a stored kind and need the family without a second lookup.
