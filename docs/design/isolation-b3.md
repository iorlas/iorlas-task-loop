# ISOLATION B3 and the leftovers of C: the plan after B2b (tl-hwv5.3, tl-hwv5.4)

Status: plan, 2026-11-07, written after B2b-1..4 (#466, #475, #478, #489, #496). Denis accepted `docs/design/isolation.md` as written
("Protocol then protocol"). No code PR of this note starts before the lead announces the freeze: B3 edits files that still move
(`app/pipeline`, `app/plan`, `app/write`, `app/review`). **B3 moves no module between packages**: it deletes rows, fields and
modules and rewires calls inside the existing ones, so it may follow the freeze.

## What is true after B2b

delegate owns the network wait, the lane polls, the short lane-out wait, the one worker retry and the write reroute. The engine's
`policy.TABLE` keeps three kinds of rows, all because the engine alone holds the **whole prompt** and the **resume policy**:

| Row | Why it is still the engine's |
|---|---|
| `NewThread` / `Reroute` for a RESUMED call (worker_failed, lane poll, lane predicted) | a fresh thread needs the full prompt; delegate got only the delta |
| `resume_refused` (caller / needs_owner on a resumed call) | same |
| `denied_secret` (`apply_patch` note) | the note is appended to the full prompt |

Everything else is `Yield | Fail` data. `pauses.py` / `pause_reasons.py` (the Park wake words, read by `app/asks/parks.py` and
`app/pipeline/closing.py`) stay until B3-1 makes the engine see only `Done | NeedsOwner | Failed(retry_after)`.

## The design: a thread is a key, not a ref

Today the engine holds the vendor session ref (`WriterSession.delegate`, `RunState.planner_ref`, `Call.resume`), the context size
(`WriterSession.ctx`, `Usage.context_k`), the fresh-above limits (`FRESH_ABOVE_K`, `write_fresh_above_k`, `write_fresh_stage_k`),
the delta-vs-full prompt choice and the "you take over from an earlier writer" text. That is harness knowledge: a session ref
means a vendor, context size means a window, and "fresh above 150k for claude" means a model.

After B3 a worker call carries:

```
start(brief: Brief, thread: ThreadKey | None, role, tools, budget, policy)
Brief = full prompt + delta prompt (None when the brief changed: the whole prompt is the only valid one)
ThreadKey = an opaque string the engine picks per bead and node ("writer", "planner", "look"); delegate maps it to a session
```

delegate keeps, per (run, thread key): the session ref, the context it holds, the lane. It decides, with its own config and
tables: resume with `delta` or start fresh with `full` (+ its own takeover note) when the context is over the family limit, the stage
is a boundary, the lane is out, the vendor refused the ref, or the writer family changed. The engine keeps only what is
product-level: *which prompts exist* and *whether the brief changed* (the `seen` hashes stay in the engine; they say what the
engine's own prompts contain).

Options judged:

| Option | Verdict |
|---|---|
| Engine keeps the ref but delegate returns "ctx_k, resumed" for it to decide | ❌ same knowledge, one hop further |
| Delegate decides from `ThreadKey` + both prompts | ✅ chosen; the engine's resume rows disappear |
| Delegate also owns the `seen`-hash delta rule | ❌ it would parse the engine's prompts; the engine knows when its brief changed |
| `Agent.transcript()` for `tl trace` | ❌ as in isolation.md option 8; events persisted by task-loop cover it |

## Slices (order = dependency order; each releasable, each a pure deletion on the engine side)

| # | Slice | What it deletes in task-loop | Size |
|---|---|---|---|
| B3-1 (tl-hwv5.3.1) | **Thread key + full/delta in the request.** delegate keeps session/lane per key and owns resume-vs-fresh, `resume_refused`, lane-out of a resumed call, the takeover note. | policy rows `resume_refused`, resumed branches of `_bead_none/_lane_*`, `NewThread`, `Reroute`, `Call.resume/was_resumed/resume_key`, `WorkerCall.again`, `asked.thread_updates` resume parts, RetryPlan `worker_failed/resume_refused`, `lane_acts.act` NewThread/Reroute branches, `FRESH_WRITER_TEXT`, `RESUME_AFTER_STOP`; then `pauses.py` words collapse to `outcome_of` kinds | done: 1a #541, 1b #<PR> |
| B3-2 (tl-hwv5.3.2) | **Context and the fresh policy.** `FRESH_ABOVE_K`, `write_fresh_above_k/stage_k` move into delegate's config; `drop_big`, `Handoff.fresh_above_k`; `WriterSession.delegate/ctx`; `Usage.context_k`; trace/`WriteRound` fields `resumed`, `context`, `input_tokens` by thread | `app/write/handoff.py` (drop_big, fresh_above_k), `config.py` keys (profile keys leave `.task-loop.json`: unknown-field refusal, remove them from the repo's own profile in the same PR), `checkpoint.WriterSession`, `trace` fields | M |
| B3-3 (tl-hwv5.3.3) | **Harness flags become product booleans.** `only_family`, `writer_exec_allow`, `engine_only`/`engine_only_advisory`, `writer_family`/`planner_ref`/`fallback_lane` in `RunState`, `domain/lanes/pin.py` ("openai" is the Codex writer), `domain/checks/writer_split.py` | `RunRequest.to_argv`-era fields in `tlkernel/delegate.py`, `worker_request.py`, `worker_identity.py`, `writer_pin.py`; the profile keeps `writer_needs_edit` and `reviewer_other_family` (booleans delegate honours) | M |
| B3-4 (tl-hwv5.3.4) | **Transcripts.** `TranscriptKind/TranscriptInfo`, `DelegateResult.transcript*`, `AiCall.transcript`, `CallEnd.transcript`, `app/run/calls.py` ("opencode:" ids); `tl trace` and the dashboard read the event log task-loop already persists from `Agent.events()` | kernel records (V bumps), `adapters/delegate_wire.py`, `app/track/verbs.py` | done: #552 |
| B3-5 (tl-hwv5.3.5) | **Names.** `report/card.py` family from lane name, `taskloop_dash/names.py`, `childenv.py` prefixes (`CLAUDE_*`, `ANTHROPIC_*`, `OTEL_*`, `CODEX_COMPANION*`) to delegate's worker env; `DELEGATE_LIVE_FILE` env (A4 leftover) | the above; `adapters/childenv.py` shrinks to task-loop's own scrub | done: #554 |

Not harness knowledge (stay, judged): `adapters/ident.py claude_dir` and `app/release/*` use of `~/.claude` (task-loop IS a Claude
Code plugin: its own install), `asks/trustroots.py` (a security list of directories), `release/publish.py` (`claude plugin ...`, release
tooling).

Acceptance of the whole B3 (the epic's grep): `codex|claude|opencode|openai|xai|FRESH_ABOVE_K` find nothing in task-loop code outside
`adapters/` plugin-install code listed above; the profile carries no harness-named key; `tl trace` and the dashboard read events,
not a harness path.

## Leftovers of C (tl-hwv5.4), after C1/C2a

| # | Slice | Files | Size |
|---|---|---|---|
| C-a (tl-hwv5.4.1) | `report/planner.py` reads `api.history()` rows by their delegate field names: the run's outcome and cost become a field of the `Agent` outcome the engine already logs (`CallEnd`); the report sums those | `app/report/planner.py`, `adapters/delegate.py history()`, `tlkernel/usage.py` | S |
| C-b (tl-hwv5.4.2) | Words: `route.py` is gone (a library): docstrings, `tl.py lanes` help, `kernel/delegate.py` and `ports.py` docstrings, `app/launch/selftest.py` "fake route.py", `adapters/__init__.py`, `RouteProbe` naming, `delegate_status.py` | comments and names only | S |
| C-c (tl-hwv5.4.3) | Dashboard live view reads task-loop's own event log: `taskloop_dash/readers/logs.py` (`live_dir`, `*.jsonl`, long-poll), `readers/world.py live_events/stage_events`, `views/live_lines.py`, `stage_logs.py` | dashboard; depends on B3-4 (event log is the one store) | M |

## Order and PR count

C-b can go any time (S, no dependency). C-a is independent. B3-1 (2 PRs) then B3-2, B3-3, B3-4, B3-5; C-c after B3-4.
Total: 10 PRs (B3: 6, C: 3, plus the final grep/doc check as part of the last one). Closure target +0 each (deletions); B3-1 and B3-4 touch
kernel records and bump their V (stale records are refused; no migration).

## Decisions

| Decision | Status |
|---|---|
| A thread is an opaque key; delegate owns ref, context, resume-vs-fresh, takeover note | proposed, to Denis through the lead |
| Profile keeps product booleans only (`writer_needs_edit`, `reviewer_other_family`) | proposed |
| `claude_dir` / plugin-install code is task-loop's own, not harness knowledge | proposed |
