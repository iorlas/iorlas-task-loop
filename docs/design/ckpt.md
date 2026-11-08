# CKPT: CloseIntent and the stage sections of the checkpoint (tl-e5t0.29, design slice 1)

Design and slicing only; no code moves with it. Follows `stage-isolation.md` section 1.1c and 7, `compat.md` (no backward compatibility: the format changes once, directly, a foreign-version record is refused) and `pipeline-node.md` (slice P3 moves `closer*.py`; this bead does not touch those files while that PR is open). Measured on origin/main, 2026-11-07, by reading `contracts/checkpoint.py`, `app/run/closer.py`, `app/pipeline/ended.py`, `app/run/records.py`, `app/run/crash.py`, `app/workers/account_acts.py`; nothing was run.

## What a restart reads today

A run that died inside its close leaves a `Checkpoint` with `ended: EndRec` (kind, fingerprint, detail, sha, spec, fp, comment, escalated, leftovers) and `applied` (keys of the effects done). `Closer.resume(ck)` rebuilds the outcome and the Disposition from `ck.ended` (`ended.loaded`) and calls `finish(done)`. `finish` then reads, from a **fresh engine**, things the dead run knew:

| read in `Closer.finish` / `pause` | where the dead run set it | on a fresh engine it is |
|---|---|---|
| `e.pause_reason`, `e.pause_producer`, `e.pause_permanence` | `workers/account_acts.py` (167-169, 135-137), `run/crash.py` (15, 26-27) | `""`, `"engine"`, `None`: `parks.paused(...)` files a pause with no reason, and a delegate-typed one becomes the engine outcome kind |
| `e.retry_after` | set by `pause` itself from the park, and by the worker stop | `0.0` (unknown) |
| `e.crash_fingerprint`, `e.crash_site` | `run/crash.py` (21-22) | `""`: a crash pause loses its fingerprint and the `ask_pause` text its site |
| `e.cost`, `e.t0`, `e.stats`, `e.sessions` | `workers/worker_call.py` (cost), engine start (t0), steps | `0`, now, `{}`, `[]`: the `stats` line of the Reflect comment and the run record says `cost=$0.00; minutes=0` |
| `e.plan_summary`, `e.asked`, `e.why` | plan, ask flow, result | defaults (`RaiseAsk` for a NOOP builds its spec from `plan_summary`) |

`EndRec` is the outcome; the facts above are the rest of what the close needs. `stage-isolation.md` names this: "the `Pause` value must go into `CloseIntent`, or it fixes nothing."

## The record

`CloseIntent` is `EndRec` plus what the table lists, as one frozen record in `contracts/checkpoint.py`, written by the existing `keep_end` (one fenced write, before the close's first effect):

- `outcome: EndRec` (unchanged; it is renamed `CloseIntent` only when the pipeline's close moves, to avoid touching its readers twice);
- `pause: PauseFacts` (`reason`, `producer`, `permanence`, `retry_after`, `crash_fingerprint`, `crash_site`);
- `stats: str` (the line `finish` builds, built once by the dead run and not recomputed by the restart);
- `plan_summary: str` (for the NOOP ask) and `asked: bool`.

`Closer.resume` reads these and sets nothing on the engine from the checkpoint but the intent's own values; `finish` takes `stats` as a parameter. The close never decodes `RunState` or any stage section.

## Stage sections

The checkpoint stays one record. Sections keep resumable stage progress only: `RunState` is already that for the stages that are done (`LookState`, `ReviewLive`, `PlanState`, `WriteState`, `LandState` hold the unsaved parts and `RunState` fields stay engine attributes via `StateField`). Each section later declares `restart()` (what a task started again on the base keeps) in place of `RunState.start_again`'s one keep list (`extra`, `rebase_resets`, `brief_hash`, `snap`, `planner_ref`, `pending_land_validation`, `leftovers`, `followup_ids`); `Checkpoints.save`'s forced `land-verify-red` step moves with the land's section. Both are format-neutral until the sections own their fields, so they come after the stage beads' slice 3 and 4 (AmendState, hand-offs).

## Slices

1. **CloseIntent** (this bead, code): the record, `keep_end` writes it, `Closer.resume`/`finish` read it. `Checkpoint.V` 3 to 4, nothing migrated. Tests: a current-format checkpoint with a `CloseIntent` resumes a close with the dead run's pause reason, retry time, crash fingerprint and stats (killed-before-Reflect child test: `tests/run/real/test_close_kill.py` plus a logic test over a fake host); a v3 checkpoint is refused loudly and the run starts over; the record round-trips through `wire`. Blocked on P3 only for the lines of `closer.py` it edits: it touches `finish`, `resume`, `pause` signatures.
2. **restart() per section**: `start_again` becomes the sum of the sections' keep rules; one table test per section. After B-PLAN slice 3 and B-LAND slice 4.
3. **Per-part persistence**: sections stored as their own parts of factory.db (D-* beads), `Checkpoints.save` writing them in the one transaction. After D-KV.

## Open points for the owner

1. Rename `EndRec` to `CloseIntent` now (one wide edit of `ended`, `finish`, `records`, `closer_host`, `state`) or with P3 (recommended: with P3).
2. `owner-look payload` in the design sentence: no reader was found in the close path; the leftovers already travel in `EndRec`. Recommend dropping it from the record unless the owner names a reader.
3. `stats` as text or as the numbers (cost, minutes, counts) the line is built from: recommend text (the close only prints it).

## Not verified

The table is read from the code, not exercised: whether a restart really files `cost=$0.00` was not run. `e.sessions` and `e.stats` as defaults are read from `run/fields.py` names only. Whether P3 changes `Closer.finish`'s signature is the pipeline stream's to say.

## 4. Per-part persistence (C3, tl-e5t0.29; one PR)

Storage only. The in-memory `Checkpoint` and the flat `RunState` (engine attributes through `StateField`) do not change, so no call site of `ck.state.X` moves; `Checkpoints` (app/run/state.py) keeps its methods. What changes is how the record is stored: no more one body that holds every stage's fields.

**Rows.** The pipeline Part keeps `checkpoint` (bead, t, rev, body) as the **cursor row** and gains `checkpoint_section` (bead, section, body), primary key (bead, section). The cursor body is the `Checkpoint` without the owned fields (branch, head, step, stage, rounds, n, feedback, gate_tail, applied, `ended: CloseIntent`, notes, progress, closed, and the shared fields below). Each section row is one kernel record. The cursor's `rev` is the only fence: a write is one SQLite transaction that checks the cursor revision, writes the cursor and upserts only the sections whose body changed. A read is one transaction that assembles the `Checkpoint`. A section row missing, torn or of another version refuses the whole record (`Refused`); nothing is migrated (compat.md).

**Who owns which RunState field** (every field has one owner; no catch-all section):

| owner | section record | fields |
|---|---|---|
| plan | `PlanSection` | plan_data, brief_hash, snap, planner_ref, planned, replans, extra, rebase_resets, plan_log |
| write | `WriteSection` | writer, writer_family (opaque progress identity), handoff, stage_tree, denials |
| land | `LandSection` | pending_land_validation, leftovers, followup_ids, fixes |
| look | `LookSection` | look_notes, look_unjudged, look_done, rendered_names, last_reqs, render_stale (LOOK_FIELDS plus render_stale) |
| review | `ReviewState` (existing) | review |
| cursor body (shared by pipeline, write, look, land) | n/a | done, accepted, accepted_new |

The `write` section holds the write stage's persisted `RunState` fields; `WriteState` (rounds, summaries, strays) is not checkpointed today and stays out. The three shared fields are the stage progress every stage reads and the pipeline advances, so they live with the cursor, not in a stage's section.

**Primitive.** A kernel store (`tlkernel/checkpointrows.py`) over the pipeline tables: `read(bead)`, `write(ck, expect_rev)`, `delete(bead)`, `keys()`, with the same revision semantics as `RowDoc.write_in` and the same `Fenced`/`StaleRevision` outcomes. `AmendDoc.modify` / `modify_with` keep their meaning: `fn` sees the assembled record, the result is written in one transaction. One contract suite runs against the real SQLite store and against the in-memory fake (`MemDoc`-based, assembled the same way), so the fake cannot drift.

**Versions.** `Checkpoint.V` 4 to 5; pipeline Part 2 to 3 with a no-op step (a record changed its V needs a Part bump, #460); goldens regenerated. A v4 checkpoint is refused loudly and the run starts over; no dual read, no dual write.

**Not done here.** Moving a section's record into its stage's own package (stage packages carve), and `Checkpoint` losing `state` in memory.
