# COMPAT: which install may read which stored record (tl-e5t0.58)

Design and test plan only; no code moves with it. Prerequisite of ARCHVERT-CKPT (tl-e5t0.29) and ARCHVERT-D-DB (tl-e5t0.41): neither may change a stored format before this policy and its three tests exist (docs/design/stage-isolation.md, section 7, points 1 and 3).

## What the code does today (origin/main, 2026-11-06)

1. **A record has one wire version.** About 50 records carry `V`; `wire.load` refuses any other `v` with `StaleRecord` and never migrates (`contracts/wire.py`). `Rec` also refuses unknown keys (`forbid_unknown_fields=True`), so an older install cannot read a record that gained a field, even with the same `v`. The one exception is `RunState` (`forbid_unknown_fields=False`, `contracts/checkpoint.py`), tolerant because fields were retired.
2. **A foreign version reads as absent where the caller uses `get()`**: `JsonStore.get` is lossy and `need()` raises `Refused` (`contracts/docstore.py`). `Checkpoints.read` (`app/run/state.py`) is `doc.get()`.
3. **Three readers meet a format change:**
   - *reexec*: `Reload.safe_point` (`app/run/reload.py`) execs a running engine into a newer install at a step boundary; the new install reads the checkpoint the old one wrote (the hand-over note `ReexecNote` is a second record).
   - *rollback*: `Installs` / `bad-versions.json` (`app/loop/versions.py`) send the loop back to the old install when a new one breaks soon after the move; the old install then reads what the new one wrote.
   - *dead close*: `Engine.__init__` (`app/run/engine.py`) reads the checkpoint, and `ended.unfinished` asks whether a close died with an unapplied effect key; a run found so keeps its run id and finishes the close.
4. **Consequence of 1 and 2:** after any change that moves `Checkpoint.V` or adds a top-level `Checkpoint` field, a reexec forward or a rollback backward reads every in-flight checkpoint as absent. A dead close then has no `ended` or `applied`, so the close never finishes and its effects (record, bd close, branch cleanup) are lost or redone from nothing. Nothing tests this.

## Policy

Terms: install N is the one running; N-1 is the one the loop can roll back to; N+1 is the next one it may exec into.

- **P1. Additive first, in two releases.** A field is added to a stored record in two steps, the same shape as the `.task-loop.json` key rule in CLAUDE.md: release A ships readers that accept the field (declared, with a default) and writes nothing new; release B writes it. In between N-1 never meets a key it forbids.
- **P2. No rename, retype or removal while an older install can be rolled back to.** Those are a V bump (P3), or an expand-then-contract: add the new field (P1), write both for one release, stop reading the old one the release after.
- **P3. A V bump reads N-1 and N.** Release A: the reader accepts `v in (V-1, V)` and maps V-1 to the new shape in memory; the writer still writes V-1. Release B: the writer writes V. Release C: the reader drops V-1. A record with a single accepted version (today's rule) is allowed only when it holds nothing a close or a resume needs.
- **P4. A checkpoint of a foreign version is never absent when it could hold a close.** `Checkpoints.read` uses `need()`: a foreign or torn checkpoint parks the bead with an owner-visible ask naming the file and the two versions, and leaves the file untouched; it is not read as "start fresh". (This changes behavior; owner decision 2.)
- **P5. Parts.** When `taskloop_db` (tl-e5t0.41) stores a checkpoint per part, each part declares its `read` range (min, max version) in the registry; the launch check compares ranges, not schema hashes (stage-isolation.md section 7, point 4). P1-P3 apply to each part on its own.
- **P6. One window.** The window is one release back and one forward, matching `bad-versions.json` and CLAUDE.md's "one release after". A longer rollback is the owner's reinstall, not the code's promise.

## Tests (the acceptance criteria), each simulating a format change by editing a real stored dict

Place: `tests/run/test_compat.py` (unit layer: files only through `workdir`, no process; the install switch is a fake via the `newer_fn` / `exec_fn` seams the engine already has).

| test | setup | must hold |
|---|---|---|
| reexec survives | a checkpoint dict from `wire.dump(Checkpoint(...))` with a new optional field added (N+1) and, separately, one field removed (N-1) | the engine started with a `ReexecNote` resumes at the saved step with the same counters; nothing reads as absent |
| rollback survives | the N+1 dict above; `Installs.record_bad` marks N+1 and the loop reads as N | the checkpoint loads, or the bead parks by P4; it is never read as fresh |
| dead close survives | a dict with `ended` set and one effect key missing from `applied`, plus an unknown extra field and, separately, `v` bumped | `ended.unfinished` is true and the run id is retaken; for the bumped `v` the engine refuses by P4 and the file is untouched |

Plus two guards the policy needs to stay true:

- a **golden** test (as `tests/contracts/test_wire.py` does for `records.json`) that fails when a persisted record's fields change while its `V` and the policy marker do not move; and
- a test that `Checkpoint` and `EndRec` accept one unknown key once release A of P1 has shipped (the tolerance is a declared, tested property, not an accident like `RunState`'s).

## Size and order

M: the three tests and the P4 change are about 150 lines of test and 20 of source. Order: this note, then the tests (red for P4 first), then P4, then P1's tolerant `Checkpoint`. ARCHVERT-CKPT and D-DB wait for all of it.

## Owner decisions

1. **Tolerate unknown keys in persisted records, or two-release adds only?** Recommend two-release adds (P1) with no blanket tolerance: `Rec` refuses unknown keys on purpose, it catches typos, and `RunState` shows the cost of leaving it open.
2. **A foreign-version checkpoint parks the bead (P4) instead of reading as absent?** Recommend yes: absent loses an unfinished close silently; a park is visible and reversible.
3. **Window of one release each way (P6)?** Recommend yes; it is what rollback in `versions.py` already assumes.

## Not verified

The counts (about 50 records with `V`) are a grep of `contracts/`; no test was run for this note. Whether the hand-over `ReexecNote` needs its own range is open until the reexec test is written.
