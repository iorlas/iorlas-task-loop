# REWRITE-FACTLOG: the engine log is the one history; the trace is its projection (tl-7i9k.35)

Design note only; no code moves with it. Acceptance of the bead (REWRITE-05 in `docs/architecture/review-rewrite-opus.md`): `records.file_trace` builds no fields by hand; the projection equals the old trace on recorded runs; `Tokens` is defined once. Ledger rows folded in: M-099 (one `jsonl_log`, `events.jsonl` one writer), M-115 (trace, manifest state, EndRec are projections), M-116, M-117, M-385. Measured on origin/main, 2026-11-06.

## What is written twice today

The engine log (`runs/<run>/engine.jsonl`, 40 typed records in `contracts/log.py`) already holds the calls, steps, checks, waits, land receipts and `Close`. At the close the engine also writes a `RunTrace` (`contracts/trace.py`, 166 lines, V2, 36 fields) to `traces.jsonl` (177 lines on the devbox now), built by hand:

- `app/run/records.py:133` `file_trace` (198 lines in the file) passes ~25 fields to `app/run/trace.py` `run_trace` (117 lines), which copies them into the record. Of these, 13 come from the engine's in-memory state (`e.cost`, `e.stats`, `e.sessions`, `e.verified`, `e.write_rounds`, `e.strays`, `e.reflection`, `e.account_notes`, `e.salvaged`, `e.route`, ...), the rest from the run's identity and the close.
- `app/pipeline/closing_record.py` (108) writes the log's `Close` and the trace in one place; `app/reconcile/lost.py` and `commits.py` write a trace for a run that died (`salvaged`, `backfilled`).

So a fact such as "this call cost 0.4 USD, 12k tokens" exists once in the log (`CallEnd.tokens`, `.cost`) and again in `RunTrace.sessions[].tokens`. If the run dies before the close, only the log has it.

Other duplication named by the bead:

- **Token shapes in task-loop**: `contracts/trace.py` `Tokens` (in/cached/out), `contracts/log.py` `CallTokens` (the same plus `cache_write`), `contracts/delegate.py` `UsageTokens` and `LiveTokens`. Delegate's own library has `wire.Tokens`, `wire.UsageTokens`, `status.LowTokens`, `live.LiveTokens`. Task-loop imports only `delegate.api`, so the delegate ones stay; the three inside task-loop collapse to one (`CallTokens`, with `cache_write: int | None`).
- **JSONL appenders**: `_vendor/jsonl_log` is the one implementation of the single `O_APPEND` write, used by `delegate/contracts/stores.py`, `contracts/rotating.py`, `app/track/trail.py`. Other sites open files for append by hand: `app/loop/files.py` `append_line`, `app/loop/exits.py`, `app/loop/core.py`, `app/loop/run.py`, `app/run/entry.py`, `app/checks/executor.py`, `app/land/tree.py`, `app/loop/factory.py`, `app/launch/dash.py`, `app/wire/slots.py`, `adapters/layout_migrate.py` (11 files; some are text logs, not JSONL: each is judged at its cut).
- **`events.jsonl` writers**: the ledger says two; today `app/track/trail.py` `event()` is the one writer (under `events_lock`, one held handle) and `contracts/events.py` types its rows. This part of M-099 is already done; the PR for it is a test that no other module opens the file (a rules test), not code.

## The projection

`project_trace(rows: Sequence[EngineLog], close: RunFinish, origin: Origin) -> RunTrace`, a pure function in `domain/` (the trace is read by `app`, `report`, and the dashboard's `readers/records.py`, so the fold may live in `contracts/` if the dashboard keeps its read of the type; see owner decision 2).

Fields by source:

| RunTrace field | from the log | missing from the log today |
|---|---|---|
| run, bead, started, branch, worktree, version | `RunStart` | none |
| ended, outcome, why, sha, kind, why_code | `Close` + `RunFinish` | none |
| sessions[].tokens, cost, secs, account/route | `CallStart`/`CallEnd` | none |
| stats, cost.usd | fold of `CallEnd`, `CheckEnd`, `StepEnd` | none (check the equality in the golden test) |
| write_rounds | partly `StepStart`/`StepEnd` of the write node | a `WriteRound` row |
| verified | none | a `Verified` row |
| reflection, strays, account_notes | none | `Reflection`, `Stray`, `Note` rows (`Note` exists) |
| faults, fingerprint, kfp | `Warn`, `VendorError`, `Close` | none |
| salvaged, backfilled | the lost-run path | stays a trace-only flag set by the writer of the salvage |

So the log gains four row types (`WriteRound`, `Verified`, `Reflection`, `Stray`), all written at the moment the engine learns the fact (today it stores it in memory and writes it at the close). That is also what the crash-resume note (`docs/design/crash-resume.md`) wants: a fact in memory is lost with the process, a fact in the log is not.

## Cut order (each a PR green on `just test`)

1. **Golden fold, read-only.** `project_trace` over the engine logs for the last 50 recorded runs, a test that compares it field by field with the stored traces and prints the fields that differ (the architecture note's first slice). Ships no behaviour; its output decides cuts 2 and 3. Needs a fixture set of ~10 real logs (anonymised) in `tests/fixtures`, since a test may not read the owner's `~/.config`.
2. **One Tokens.** `Tokens` becomes `CallTokens`; `AiCall.tokens` and `report` read it; `UsageTokens`/`LiveTokens` in `contracts/delegate.py` map to it at the edge. Trace bytes: `cache_write` appears as an added optional field (V stays 2; msgspec ignores a missing one).
3. **The four rows** (`WriteRound`, `Verified`, `Reflection`, `Stray`), written when learned; the trace still built by hand, now also checked against the fold in the golden test.
4. **The closer writes the fold's output**: `file_trace` calls `project_trace`, builds nothing by hand; `run_trace`/`_known` copy code deleted. For a run whose log lacks the new rows (written before cut 3), the fold falls back to the in-memory state for one release.
5. **Lost and salvaged runs** (`reconcile/lost.py`, `commits.py`) call the same fold, so a dead run has a trace made of its log.
6. **jsonl_log everywhere it is a JSONL file**: the appenders of the list above that write typed rows move to `jsonl_log`; text logs stay. Rules test: no `open(..., "a")` of a `*.jsonl` outside `_vendor/jsonl_log`. Ratchet-shaped: the number of offenders may not rise.
7. **Delete**: `EndRec` and the handoff mirror (REWRITE-05 names them) only after the manifest-state fold exists; this is the part this note does not size, because manifest state is also the lease-and-resume record (STORE work, `tl-7i9k.12`). Leave it out of this bead.

Size: in about 450 lines (4 row types, the fold, the golden test, the fixtures); out about 300 (`run_trace`, `_known`, the by-hand argument list, two token classes). Net roughly +150 lines and one fewer way for a trace to disagree with its log. Files touched: about 22 across cuts 1-6 (16 import `contracts.trace` today, plus the 11 appenders, minus overlap).

## Risks

- `tl report`, the reflect digest and `readers/records.py` read traces: they keep reading `traces.jsonl` throughout; only the producer changes. A golden diff in cut 1 is the safety net.
- The fold must be deterministic across the schema change: records are versioned, an old log folds through the old record types.
- Traces are retained (every LANDED record, pruned by age); engine logs are rotated by age (7 days, per the plan). A trace cannot be re-folded from a log that has rolled, so the stored `traces.jsonl` stays authoritative for old runs. The projection is only the producer.

## Owner decisions, with a recommendation

1. **Keep writing `traces.jsonl` (a cached projection) or fold on read?** Recommend keep writing: `tl report` and the page read 177+ traces without opening 946 run directories, and logs age out. This is the architecture note's choice too.
2. **Where does the fold live: `domain/`, or `contracts/` so the dashboard can call it?** Recommend `domain/`: the dashboard reads traces, it does not make them. (Contrast with READMODEL, where the shared rule must live in `contracts/`.)
3. **Add four log row types now, or fold only what the log has and leave `verified`/`reflection` hand-built?** Recommend add them: otherwise "builds no fields by hand" is not true, and a crash before the close loses them.
4. **Leave EndRec and the handoff mirror out of this bead?** Recommend yes; they belong to the manifest/lease work and a second bead would own them.
5. **Fixtures: 10 anonymised real logs checked in?** Recommend yes, with paths and repo urls rewritten; the alternative (reading `~/.config`) is against the test rules.
