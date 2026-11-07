# Review, lens 3: the land/gate/close pipeline, lanes/slots/runs, and its failure modes

Reviewer id prefix: `PIPE-FABLE`. 2026-11-02. Static reading; nothing run. All `file:line` cites are from the C4 worktree
`/home/iorlas/Workspaces/wt/C4` at task-loop 0.23.299 (`d4dd972b`, CRASHPARK), which is newer than the main checkout
`/home/iorlas/Workspaces/iorlas-task-loop` (0.23.293, `e6c7f2a7`; `origin/main` is at 0.23.301). Paths are relative to the repo root; `tl/` =
`src/taskloop/`. Line counts by `wc -l` this session. "(unverified)" marks what I did not open.

## The incident this lens starts from: `KeyError: STALE`

What happened, from the code and git, not from the commit message alone:

1. GATEIDENT (`a0f566fc`, 2026-11-01) made `Gate.run` return a fourth outcome, `Problem(ProblemKind.STALE, ...)`, when tree, HEAD, base or
   config moved during the checks (`tl/app/land/gate.py:159-172`).
2. `Gate.run` has two callers. The in-lock caller (`Lander.tries` → `pass_for`) already treated STALE specially. The outside-the-lock caller
   (`Lander.outside` → `Lander.land`) handed every `Problem` to `FixOutside.run`, which did
   `{GATE: ..., VERIFY: ..., CONFLICT: ...}[problem.kind]` → `KeyError` (the pre-fix line, `git show cff2a794`).
3. The exception left `lander.finish` and was caught by the catch-all in `RunOnce.go` (`tl/app/run/run_once.py:59-60`), which at that version
   turned it into `FAULT_ENGINE` with the text `failed: engine error KeyError: <ProblemKind.STALE: 'stale'>` and **no traceback**
   (the only traceback writer in the engine is `crash.py:16`, added by CRASHPARK 24 minutes after KEYERR: `cff2a794` 13:10Z, `d672d9c8` 13:34Z).
4. The fix (KEYERR, 0.23.298) special-cases STALE in `Lander.land` (`lander.py:138-141`), names the table `CAUSE` (`fix_outside.py:54`) and adds a
   test that every `ProblemKind` is in every table keyed by it (`tests/land/test_problem_kinds.py`).

The fix is correct for this enum and wrong as a class fix:

- The class is **a closed enum consumed through open tables and `str`-typed seams**. `Fixer.fix(self, kind: str, ...)` (`tl/app/land/fixer.py:66`)
  erases `ProblemKind` at the exact boundary where it matters; the prompt tables are keyed by plain strings (`tl/domain/prompts/land.py:5-10`);
  `test_problem_kinds` passes only because `StrEnum` hashes like its value. pyrefly cannot see a missing key in a dict lookup. The same shape
  exists elsewhere (PIPE-FABLE-03): `Verdict.kind: str` across the loop/engine process boundary with `kind.startswith("fault_")`
  dispatch (`tl/app/loop/verdict.py:31`, `:52`), `pauses.TABLE: dict[str, PauseRule]` with a silent `needs_owner` default for an unknown word
  (`tl/domain/lanes/pauses.py:23`, `:84`), `stage_checks.fault_kind` (`tl/app/run/stage_checks.py:20`), `gate.FAULTS` (`gate.py:26`),
  `SILENT_LIMIT` partial over `Step` with a default (`tl/contracts/runlife.py:22-26`). Each is one GATEIDENT-style change away from the same crash.
- The **failure-mode ladder** that turned a one-line bug into a 70-minute loss is untouched: a crash anywhere in the engine is "transient" by
  construction (PIPE-FABLE-02), the run has no wall deadline (PIPE-FABLE-16), the crash leaves no traceback and no event (PIPE-FABLE-01, -17),
  and a release at the land safe point re-execs every in-flight land onto the just-released code (PIPE-FABLE-23).
- CRASHPARK, the follow-up, **made the escalation worse** while keeping the work: `ENGINE_CRASH` has `retries=0` and no `escalate_to`
  (`tl/domain/outcome.py:76`), is in `PAUSES` (`tl/contracts/kinds.py:40`), gets a transient park with 60 s → 1 h backoff and no attempt cap
  (`tl/domain/lanes/pauses.py:30`, `:87-100`; `tl/domain/beads/park.py:36-40` caps only question runs), and `storm=False` (default of `Rule`,
  `outcome.py:48`). Before CRASHPARK the same crash was `FAULT_ENGINE`: 3 same-fingerprint retries then `ASK_STUCK`, and it fed the storm detector.
  A deterministic crash in land or close now retries every hour, forever, without ever asking the owner or stopping the factory.

## Top 10 by importance

1. **PIPE-FABLE-02** A crash in land/close (ENGINE_CRASH) never escalates and never trips the storm: hourly retries forever. P1, S.
2. **PIPE-FABLE-01** Engine crashes outside land/close are logged without a traceback or an event; the 3am diagnosis is one line. P1, S.
3. **PIPE-FABLE-16** A run has no wall-clock deadline; only silence is detected, a loop that keeps emitting steps runs for days. P1, S.
4. **PIPE-FABLE-06** The heartbeat thread and the main thread both get-then-put the manifest with no lock and no join: a landed run can be buried as `lost`. P1, S.
5. **PIPE-FABLE-23** `safe_point("land")` execs every in-flight land onto a release that just shipped; the KEYERR and CRASHPARK fixes themselves rode this hop. P1, M.
6. **PIPE-FABLE-03** The KeyError class: enum-keyed open tables and `str`-typed seams; one rule test over all enum-keyed tables, and `match` + `assert_never` at dispatch. P1, M.
7. **PIPE-FABLE-04** The in-lock STALE path is unbounded: `moved` is not counted in `pass_for`, and a base that keeps moving (another machine) runs the gate under the land lock forever. P2, S.
8. **PIPE-FABLE-08** No lane supervisor: a loop that raises stays dead until a human runs `tl factory start`; the dashboard greys it after 3 min and nothing pages. P2, M.
9. **PIPE-FABLE-22** The land's caps (`pushes`, `moved`, `flaky`) live in process memory; every restart or exec at the land step starts them at zero. P2, M.
10. **PIPE-FABLE-19** Four sites classify "the engine crashed" into three different Kinds depending on where the exception surfaced. P2, S.

## Idea ledger

| id | idea | evidence (file:line) | kind | sev | effort | verdict | reason |
|---|---|---|---|---|---|---|---|
| PIPE-FABLE-01 | `RunOnce.go`'s catch-all records `f"engine error {type}: {err}"` and nothing else; only land/close crashes get a traceback (CRASHPARK) | `tl/app/run/run_once.py:59-60`; traceback writers in the engine: `tl/app/run/crash.py:16` only (grep) | observability gap | P1 | S | ✅ do | A `KeyError` in a stage step is still diagnosed from one line, as KEYERR was. The engine's stderr file sees nothing: the exception is caught. |
| PIPE-FABLE-02 | ENGINE_CRASH never escalates, never storms, retries hourly without cap | `tl/domain/outcome.py:76` (retries 0, no escalate_to, storm default False at `:48`); `tl/contracts/kinds.py:40` (in PAUSES); `tl/domain/lanes/pauses.py:30`, `:87-100`; `tl/domain/beads/park.py:36-40` (no attempt cap) ; compare `_fault()` at `outcome.py:55-57` | failure-mode regression (CRASHPARK) | P1 | S | ✅ do | A deterministic crash on every land now costs one full land per hour forever and the owner is never asked. Pre-CRASHPARK it was 3 then ASK_STUCK. |
| PIPE-FABLE-03 | The KeyError class is enum-keyed open tables plus `str` seams; the fix test covers one enum | `tl/app/land/fixer.py:66` (`kind: str`); `tl/domain/prompts/land.py:5-10`; `tl/app/loop/verdict.py:31`, `:52`; `tl/domain/lanes/pauses.py:23`, `:84`; `tl/app/run/stage_checks.py:20`; `tl/app/land/gate.py:26`; `tl/contracts/runlife.py:22-26`; `tests/land/test_problem_kinds.py:21-27` | class-of-bug, missing gate rule | P1 | M | ✅ do | pyrefly cannot see a missing dict key; `match` + `assert_never` it can (25 uses exist already, grep). A rule test can walk every `MappingProxyType`/`Final` dict whose keys are enum members and assert totality or an explicit exclusion set. |
| PIPE-FABLE-04 | In-lock STALE has no counter: `pass_for` returns STALE without `st.moved += 1`; with tries used up every iteration is a full INSIDE gate under the land lock | `tl/app/land/lander.py:145-150` (STALE skips fixing, loops), `:195-198` (INSIDE once `moved >= tries`), `:245-250` (STALE, no increment), `:233-239` (push STALE does increment); `gate.py:169-172` | liveness hole | P2 | S | ✅ do | Under the lock main can only move from another machine or a human (Z06); then this lane gates forever and holds the lock for everyone else on the box. Also the CACHED → `passed()` None path repeats outside without counting. Cap like `PUSH_TRIES` (`push.py:91-92`). |
| PIPE-FABLE-05 | `Gate.green()` builds a clean worktree copy each call and is called up to three times per try | `tl/app/checks/runner.py:120-127` (`isolated` per call); `tl/app/checks/clean.py:26-33`; callers `lander.py:168`, `:193`, `:248` (via `passed`) | cost, silent work | P3 | S | ❓ untested | Measure: count `clean_tree` creations per land in a Trust Night log. Low confidence that it matters; high confidence it is invisible. |
| PIPE-FABLE-06 | Manifest lost-update inside one process: the Lease thread's `beat` (get→put) races the main thread's `advance`/`end`; `stop()` sets an event and never joins | `tl/app/slots/lease.py:42-47` (no join); `tl/app/run/run_once.py:42`, `:77-84`, `:251`, `:239`; `tl/app/run/records.py:84-93`; `tl/contracts/locator.py:159-171` | state race (adds depth to Z04) | P1 | S | ✅ do | A beat that read `live` before `end` wrote terminal puts `RUNNING` back; the reconciler marks a landed run `lost` 5 min later (`runlife.py:16`, `:52`). CAS per file (Z04) does not fix this: the beat's expected revision is simply stale and should lose, which needs the beat to retry-or-abandon, not merely to serialize. Join the thread in `stop()`. |
| PIPE-FABLE-07 | Host identity is `os.uname().nodename`; `is_lost` only reconciles runs of the same nodename | `tl/contracts/locator.py:17-19`; `tl/contracts/runlife.py:52` | brittle identity | P2 | S | ❓ untested | macOS nodename can change with the network (Bonjour/DHCP). If it does on the Mac, runs of the "old" host are never reconciled and show live forever. Test: log nodename on the Mac hourly for a day. Low confidence. |
| PIPE-FABLE-08 | No supervisor for loop lanes: a lane that raises re-raises out of `main` and stays dead; `factory start` tops up only when invoked | `tl/app/loop/loop.py:107-109`; `tl/app/loop/factory.py:103-110`; `src/taskloop_dash/views/board.py:21` (greyed after 180 s) | operability | P2 | M | ✅ do | `start(lanes=N)` is already idempotent under the loop lock: make a loop chore re-run it every 10 min from any live lane, and emit a `lane_down` event. Pairs with Z22 (caffeinate per child). |
| PIPE-FABLE-09 | A crashed lane's exit record says `reason=crash, detail=""` | `tl/app/loop/core.py:128-135` (`left` never called on the raise path) | observability | P3 | S | ✅ do | Put `type(e).__name__: e` into `detail` in `main`'s `except Exception` before re-raising. |
| PIPE-FABLE-10 | "Every effect is safe to repeat" is a docstring, not a test per effect | `tl/domain/interpret.py:4-6`, `:43-44` (key after apply); `tests/run/real/test_close_kill.py:1-2` (one kill point); `tl/domain/effects.py:150-160` (12 close effects) | idempotency claim | P2 | M | ✅ do | A kill between `apply` and `mark` repeats the effect. RaiseAsk, FileNotes (follow-up beads), Reflect (bd comment) are the ones I would not bet on (their dedupe not opened: unverified). Table test: for each effect in `plan_close`, apply twice, assert one observable. |
| PIPE-FABLE-11 | "Already landed" is detected by the commit subject ending in `(<bead>)` on the task branch tip | `tl/app/land/landed.py:51-58`; the push pins the sha (`outbound.py:19-24`) | fragile receipt | P2 | S | ❓ untested | A repo commit-msg hook that rewrites subjects, or a hand `tl land` with another message, defeats the receipt; the rerun would re-land. Test: a `commit-msg` hook that appends a trailer. Low confidence. |
| PIPE-FABLE-12 | A fenced-out run never saves its own work: `close` returns before `SaveBranch` | `tl/app/run/run_once.py:252-255`; the next run's `Tree.reset` saves it as wip (`tl/app/land/tree.py:77-78`, `:101-107`) | crash recovery by the next tenant | P3 | S | ❓ untested | Works only if the next run of that slot is the same bead; a different bead in the slot sees "uncommitted work of another branch" and is `FAULT_SLOT` (`tree.py:104-105`). Test: fence a run, run another bead in its slot. |
| PIPE-FABLE-13 | Kinds cross the loop/engine process boundary as strings; the loop dispatches by prefix and by duplicated constants | `tl/app/loop/verdict.py:13-15`, `:31`, `:52`; `tl/contracts/kinds.py:9-35`; `tl/app/loop/run.py:75` | str seam (same class as 03) | P2 | S | ✅ do | `RunReport.kind` and `Verdict.kind` become `Kind` (msgspec enum); `v.fault` becomes `fault_of(kind)`. A new `FAULT_*`-shaped reason that does not start with `fault_` (ENGINE_CRASH is one) silently falls through to the pause path. |
| PIPE-FABLE-14 | The retry/escalation history is read from `traces.jsonl` under `suppress(OSError)`; unreadable history means "never escalate" | `tl/app/run/closer_decide.py:56-59`; `tl/domain/outcome.py:176-184` | silent degradation | P2 | S | ✅ do | A rotated or unwritable traces file turns 3-then-ask into retry forever. Warn in the log and the event trail when history is unreadable. |
| PIPE-FABLE-15 | `Placing.INSIDE` runs the gate under the land lock to avoid starvation; the GatePass tree+base check already makes a lockless gate safe | `tl/app/land/state.py:23`; `lander.py:143-144`, `:200-231`, `:245-247`; `push.py:64-67` | contrarian design | P2 | M | ❓ untested | Delete INSIDE: gate outside always, cap stales (04), and starvation becomes a FAULT_LAND the owner sees instead of a lock held for 15 min across every lane and `dev/release.py`. Contrarian: the comment says INSIDE exists for a busy main, but under the lock main moves only from other machines. |
| PIPE-FABLE-16 | No run deadline: the stuck rule detects silence only | `tl/contracts/runlife.py:20-27` (`SILENT_LIMIT`, `SAME_RED`); `run_once.py:77-84` (beat ticks it) | missing cap | P1 | S | ✅ do | Every loop in this lens (04, 02's hourly retries, fix rounds) emits records, so it is never "stuck". One `max_run_minutes` in `EngineConfig`, checked at `beat`, ending in PAUSE_KILLED-like stop with the work kept. |
| PIPE-FABLE-17 | No event in `events.jsonl` for an engine crash; only the engine log sees it | grep `trail.event` in `run_once.py`, `crash.py`, `closer*.py`: none; `tl/app/run/reload.py:110` shows the pattern | observability | P2 | S | ✅ do | The dashboard's timeline is events; a crash should be a row with run id, step, exception type, so a 3am look at the phone shows it. |
| PIPE-FABLE-18 | `records.settle` and `heartbeat` swallow `OSError`; a run whose manifest cannot be written stays live forever and says nothing | `tl/app/run/records.py:84-93`; `tl/app/loop/loop.py:174-179` (the loop checks disk, the engine does not) | silent degradation | P2 | S | ✅ do | Write the failure to stderr and into the outcome line (`RunReport.why`), so the loop's log carries it. |
| PIPE-FABLE-19 | Four crash classifications: stage crash → FAULT_ENGINE (go), land/close → ENGINE_CRASH (parked_crash), `one_stage` ValueError → FAULT_ENGINE, BaseException in LAND/CLOSE → parked_crash, else FAULT_ENGINE | `tl/app/run/run_once.py:57-60`, `:102-106`, `:220-228`; `tl/app/run/stages.py:143-152` | duplicated responsibility | P2 | S | ✅ do | One `classify_crash(step, err) -> RunOutcome` in domain, called from the two catch sites; its table is the place to put 02's escalation. |
| PIPE-FABLE-20 | A dirty slot at gate time is reported as `FAULT_STALE_BASE` ("stale base") | `tl/app/checks/clean.py:30-31`; `gate.py:26`, `:147` | misleading fault text | P3 | S | ✅ do | The owner reads "stale base" and looks at main; the cause is an uncommitted file. Add `CheckFaultKind.DIRTY_TREE` (and it will show whether 03's totality rule exists: a new member must land in `FAULTS` and `stage_checks.fault_kind`). |
| PIPE-FABLE-21 | Parks are written at two close sites per run; idempotent only by run id | `tl/app/run/stages.py:162-167`; `tl/app/run/closer.py:136-149`; `tl/domain/lanes/pauses.py:94-95` | agrees with Z04 item 9 | P3 | S | ✅ do | Fine today because `after_pause` returns the record unchanged for the same run; one more writer breaks it. Fold both into the close plan as an effect with a key. |
| PIPE-FABLE-22 | `Land` counters are process memory: a SIGKILL, a stop, or an exec at the land step resets `pushes`, `moved`, `flaky`; `fixes` persistence not confirmed | `tl/app/land/state.py:34-41`; `lander.py:127`; `fix_outside.py:63`, `:68` (`e.fixes`); checkpoint fields not opened (unverified) | cap not durable | P2 | M | ❓ untested | Test: SIGKILL a land after two rejected pushes; rerun; count pushes before FAULT_LAND. If `fixes` is in the checkpoint this is P3; if not, `max_fix_rounds` is per process and a bead can burn writer rounds across restarts. |
| PIPE-FABLE-23 | `safe_point("land")` execs the run onto a newer install exactly at the land step; a release during Trust Night moves every in-flight land | `tl/app/run/run_once.py:184`; `tl/app/run/reload.py:68-124`; `git log`: 0.23.293 → 0.23.301 in two days | agrees with Z05/R2, adds the step | P1 | M | ✅ do | The land is the most state-heavy step (lock, pass, counters, fence). The KEYERR fix was released at 13:10Z and CRASHPARK at 13:34Z: any bead at land in between exec'd twice. Delete this one safe point now even if R2 waits. |
| PIPE-FABLE-24 | The crash-after-exec fallback almost never fires: the engine's catch-all writes an outcome file (`gave=True`), so a Python exception in the new install is not "died after the move" | `tl/app/loop/run.py:79-88` (`not gave` required); `run_once.py:59-63` (every exception becomes an outcome, exit 2) | contrarian: dead machinery | P2 | S | ❓ untested | Only an import-time crash (no outcome) triggers `record_bad`. Test: inject a raise in a stage on a "new" install and watch `bad-versions.json` stay empty. If confirmed, delete the fallback with R2 rather than fix it. |
| PIPE-FABLE-25 | Three cap vocabularies for one loop: `PUSH_TRIES`/`PUSH_UP_FAILS` constants, `cfg.land_optimistic_tries`, `cfg.max_fix_rounds` | `tl/app/land/state.py:5-6`; `lander.py:155-156`; `fix_outside.py:63` | smell | P3 | S | ✅ do | One `LandCaps` record in config with a stales cap (04) added; the land loop reads one object. |
| PIPE-FABLE-26 | After a landed push, a failed `bd sync` is `FAULT_LAND` with the `engine-fault` label and the 3-then-ask ladder; the code is already on main | `tl/app/land/outbound.py:134-150`; `tl/domain/outcome.py:86`; `tl/domain/lanes/pauses.py:64` (`fault_land` needs_owner) | wrong class for a network blip | P2 | S | ✅ do | Classify Dolt failures by text like the push does (`Push.transient`, `push.py:100`): transient → PAUSE_NETWORK; only conflict/stuck (exit 2..4) stay FAULT_LAND. |
| PIPE-FABLE-27 | The fence fails open when bd cannot be read; across a >5 min bd outage `release_dead` on another lane frees the claim and two engines can hold one slot until the first writes | `tl/contracts/fence.py:87-98`; `tl/app/reconcile/leases.py:11-20`; `tl/app/slots/lease.py:14`, `:35-38` | agrees with A.F03/Z06 | P2 | M | ✅ do | The first engine's next write raises `Fenced` and the run closes nothing (12). Depth added: the loser's uncommitted work survives only through the next tenant's `Tree.reset`. |
| PIPE-FABLE-28 | `Closer.close` ignores SIGTERM for the whole close; if `Reflect` or `FileNotes` run an AI call the stop waits on a worker | `tl/app/run/closer.py:88-97`; `tl/app/run/reflect.py:55` (catch-all; the call itself not opened, unverified) | stop latency | P3 | S | ❓ untested | Test: `tl stop --now` during the close of a landed bead; measure seconds to exit. If the reflection is a worker call, move it out of the SIGTERM-ignored region. |
| PIPE-FABLE-29 | Reconcile after an exec: the manifest's pid is the old Python pid until `take_up`; a cold `uv run` longer than 300 s makes the run `lost` while it is starting | `tl/contracts/locator.py:133`, `:139-149`; `tl/contracts/runlife.py:16`, `:52`; `tl/app/run/reload.py:113-119` | race window | P3 | S | ❓ untested | Test: throttle uv's cache and exec; low confidence it happens on the Mac, but the window exists. |
| PIPE-FABLE-30 | The STALE fix test asserts membership of `StrEnum` members in `str`-keyed tables; it would pass with any table whose string values match | `tests/land/test_problem_kinds.py:21-27`; `tl/domain/prompts/land.py:5-10` | test protects less than it says | P3 | S | ✅ do | Key the prompt tables by `ProblemKind` and type `Fixer.fix(kind: ProblemKind)`; the test then also fails on a renamed value. |
| PIPE-FABLE-31 | The pre-push judge runs `tl check` in process inside git's hook when the tip is HEAD of a clean tree | `tl/app/land/push_judge.py:77-86` | agrees with c4 item 14, Z01 | P2 | S | ✅ do | From this lens: a push by hand from a slot can start a 20-minute check round inside `git push` with no run record, no manifest, no stuck rule. The judge should refuse-with-reason, never run checks. |
| PIPE-FABLE-32 | `BeadRun.run` reopens a stopped bead only when `v.outcome is FAILED`; a stop during the close of a landed bead that then lost the race is handled, but a stop with `PAUSED` leaves the bead to the lease sweep | `tl/app/loop/run.py:89-94`, `:96-98`; `tl/app/reconcile/leases.py` | edge | P3 | S | ❓ untested | Test: stop-now during a PAUSE_NETWORK close; observe how long the bead stays assigned. Low confidence. |
| PIPE-FABLE-33 | Landed-run outcome override: any outcome after `landed_sha` is set becomes LANDED except ENGINE_CRASH; a crash after the push therefore parks a bead whose code is on main | `tl/app/run/run_once.py:247-250` (`not in (LANDED, ENGINE_CRASH)`) | CRASHPARK edge | P2 | S | ✅ do | The comment says the retry cursor is kept, but the rerun's `Lander.finish` → `already()` closes it anyway (`lander.py:102-104`), one hour later (02). Close it landed now; park only the close effects that did not run. |
| PIPE-FABLE-34 | `Fenced` inside `interpret` is suppressed and the key kept in memory only; the remaining effects still run under a lost lease | `tl/domain/interpret.py:66-69`; `run_once.py:252-255` guards only the close entry, not the land's `Sync.run` (`tl/app/land/sync.py:44-49`) | exactly-once under contention | P3 | S | ❓ untested | After the push, `RecordLand` and `BdSync` run even when fenced (the push already went through, so arguably right), but a fenced run then writes `landed/<bead>.json` while the new holder also lands (Z04's two writers). Test: fence between push and sync. |

Counts: 34 ideas; P1 × 7, P2 × 19, P3 × 8; ❓ untested/low-confidence/contrarian: 05, 07, 10 (partly), 11, 12, 15, 22, 24, 28, 29, 32, 34 (12).

## First step for each ✅

- **01**: in `RunOnce.go`'s `except Exception`, call `parked_crash`'s logging path (or `e.log.warn(why + traceback)`) before building the outcome.
- **02**: in `POLICY`, give `Kind.ENGINE_CRASH` `retries=KNOBS["fault_retries"]`, `escalate_to=Kind.ASK_STUCK`, `storm=True`, and in `pauses.TABLE` an attempt cap that turns the park `needs_owner` after N.
- **03**: write `tests/rules/test_enum_tables.py` that imports every `taskloop` module, finds module-level mappings whose keys are members of one Enum, and asserts the key set equals the Enum (minus a declared `EXCLUDED` set); fix the first failures by keying `prompts/land.py` by `ProblemKind`.
- **04**: add `stales: int` to `Land`, increment it on every STALE from `pass_for` and from `outside`, and raise `FAULT_LAND("main or the tree moved under the gate N times")` past a cap in `LandCaps`.
- **06**: in `Lease.stop()`, `self.thread.join(timeout=self.every + 5)` and have `RunOnce.close` call it before `records.settle`.
- **08**: add a loop chore that calls `factory.start(files, repo, version, argv, spawner, lanes=cfg.lanes)` every 10 min when this loop holds lane 1, and emits `lane_down` for a lane whose state file is missing.
- **09**: in `Loop.main`'s `except Exception`, call `self.left("crash", f"{type(e).__name__}: {e}")` before `raise`.
- **10**: a `tests/run/test_effects_twice.py` that applies every `plan_close` effect twice through fakes and counts bd calls, asks and follow-ups.
- **13**: change `RunReport.kind: str` to `Kind` in `tl/contracts/run.py` and `Verdict.fault` to `fault_of(kind) is Infra and kind.name.startswith("FAULT_")`.
- **14**: in `Decide.run`, replace `suppress(OSError)` with a warn that names the traces file.
- **16**: add `max_run_min` to `EngineConfig`, check it in `RunOnce.beat`, set `e.halt` with a reason the stop path records.
- **17**: `trail.event(e.who, "engine_crash", e.bead, step=step, exc=type(err).__name__, run_id=e.run_id)` in `parked_crash` and in `go`'s catch-all.
- **18**: in `Records.settle`, on `OSError` write the error to stderr and set `e.why += "; manifest unwritable: ..."`.
- **19**: move the two catch-sites' classification into `domain/outcome.classify_crash(step: Step | None, err: BaseException) -> Kind`.
- **20**: add `CheckFaultKind.DIRTY_TREE`, raise it in `clean.isolated`, and let 03's rule test force the two tables to grow.
- **21**: make the park write a `CloseEffect` (`FilePark`) with a key, delete the call in `stages.record_stage`.
- **23**: delete the `e.reload.safe_point("land")` line in `RunOnce.stages`; keep the plan-time one until R2.
- **25**: a `LandCaps` msgspec record in `contracts/config.py` holding `push_tries`, `push_up_fails`, `optimistic_tries`, `fix_rounds`, `stales`.
- **26**: add `dolt_transient(text)` to `domain/land/matchers.py` and raise `PAUSE_NETWORK` from `Outbound.bd_sync` when it matches.
- **27**: `fence.stale` returns a third value `unknown` on `BdFailure`; `Pusher.push` and `Checkpoints.writer` treat `unknown` as refuse, the beat as ignore.
- **30**: with 03.
- **31**: delete the `self.check()` branch in `PushJudge.green_or_checked`; refuse with "run `tl check`" instead.
- **33**: drop `Kind.ENGINE_CRASH` from the exclusion in `run_once.py:247` and keep the crash text in the close reason.

## What I think you are NOT thinking about

1. **Every crash is "transient" by construction.** There is no notion of a deterministic failure anywhere in the ladder: `ENGINE_CRASH` and
   every `PAUSE_*` get an exponential park with no attempt cap (`pauses.py:87-100`, `park.py:36-40`); `FAULT_*` escalates only when three traces
   carry the same fingerprint, and the fingerprint strips numbers, paths and hex (`outcome.py:135-140`), which is also what makes a `KeyError:
   <ProblemKind.STALE>` on three different beads look like three different faults for the storm (storm keys on fingerprint across beads,
   `closer_decide.py:66-74`). A crash whose text is identical run after run is the strongest signal the factory has, and nothing reads it as "stop,
   this is code".
2. **The land step is the only step that holds a machine-wide lock while doing minutes of work, and it is the step you exec into new code at.**
   `tries` runs under `locks/land-<url>.lock` and may run the whole gate there (`lander.py:143-144`, `:245-247`); `safe_point("land")` is the hop
   (`run_once.py:184`); `dev/release.py` takes the same lock (c4-task-loop, Release row). A release during Trust Night therefore waits on every
   lane's in-lock gate and then moves every lane at its land. You have been shipping 4 to 8 releases a day (0.23.293 → 0.23.301 in two days).
3. **Caps that live in process memory are not caps.** `Land.pushes/moved/flaky` (`state.py:34-41`) reset on every restart, kill, or exec; the
   stuck rule's `SAME_RED` counts rounds in one run (`runlife.py:27`). The only durable counters are the park's `attempts` and the traces'
   fingerprints, and both are read with suppressed errors (14).
4. **Nobody watches the watchers.** The reconciler runs only when a tl process happens to start or a person runs a verb (`runlife.py:65-66`);
   lanes are not supervised (08); the engine's own disk and manifest failures are swallowed (18); the dashboard is pull-only (no notify path
   seen in this lens: the `closer.py:95` comment mentions "a notify command", not opened, unverified). At 3am the signal is "the phone page looks
   grey", and only if someone looks.
5. **The type system is turned off at every seam that matters.** `host: Any` (c4 item 10), `kind: str` in `Fixer.fix`, `RunReport.kind: str`,
   `pauses.TABLE: dict[str, ...]`, `Verdict.kind: str`, `SILENT_LIMIT.get(..., default)`. pyrefly is in `just check` and would have caught
   GATEIDENT's new return value at the outside-path caller if the dispatch were a `match` on `ProblemKind` with `assert_never`. The KEYERR test
   protects four tables of one enum; the rule that protects the class is one generic test (03).
6. **"Lost" and "done" are one race apart.** The manifest is written by a daemon thread with no join (06); a landed, closed run can be shown
   as lost, which is exactly the state the owner would wake up for. The reverse also holds: a beat that lands after `mark_lost` resurrects a dead
   run (Z04). Both are in one process or one file, and both are fixed by "a run's state goes forward only" (a monotonic `state` write with the
   terminal states as a sink, and the beat refusing to write once it has seen a terminal state).
7. **Observability is write-only logs.** Every failure path writes prose into the engine log (`e.log.warn`, `e.warn`) and the loop log; the
   structured channels (`events.jsonl`, the manifest `reason`, `RunReport.why`) get a truncated string (`reason[:300]`, `why[:500]`). Nothing
   records the exception type as a field; nothing lets `tl report` group "KeyError in land" across beads. The grep for a crash is `grep "engine
   error"` over `engine/*.jsonl`.
8. **The two-machine deployment breaks the land's single assumption.** Everything in `Lander` assumes that while this process holds the land
   lock, `main` cannot move except by its own push (`state.py:23`, `lander.py:201-202`). With the Mac factory and devbox sessions on one repo
   (Z06), the in-lock gate can go stale indefinitely (04) and the "already landed" receipt (11) is checked against a `fetch` that may lose a ref
   lock to the other machine's fetch (`checkout.py:60`).

## Where I disagree with the existing documents

- **`rca-zoomout-three.md` section 1: "Release hops (Z05, Z21) are a design question for the owner, not a defect."** Disagree for the land safe
  point. `safe_point("land")` (`run_once.py:184`) is a defect in its own right: it re-runs the most state-heavy step on code that has never seen
  that checkpoint, under the land lock, and it is the hop the KEYERR and CRASHPARK fixes themselves took. Delete that one safe point now; the
  owner decision (R2) is about the plan-time hop.
- **`zoom-out-review.md` Z04's proposal (CAS under a per-document flock)** is necessary but not sufficient for manifests. The in-process beat/end
  race (06) is a lost update where the correct resolution is "the beat loses and stops", not "the beat retries with the new revision" (a retry
  would re-read the terminal state and correctly do nothing, but only if the beat's own `live` check runs under the same lock as its put). The
  cheaper and sufficient fix is to join the beat thread and make the terminal write monotonic.
- **CRASHPARK (0.23.299) as described in its commit: "a land or close crash parks as engine_crash with the work kept."** The work is kept; the
  escalation, the storm trip and the owner ask are gone (02). The commit message and `c4-task-loop.md` present it as a hardening; from the
  failure-mode lens it traded a 3-strike ladder for an infinite hourly retry.
- **`c4-task-loop.md` component table, `app/land`: "gate in a fresh detached worktree".** True and too kind: the fresh worktree is rebuilt on every
  `green()` call, up to three times per try (05), and the `Placing` enum hides that one of its values (`INSIDE`) runs that gate under the
  machine-wide lock (15).
- **`c4-task-loop.md` item 4 and `c4-system.md` Level 3, manifest row: "six writers, no lock".** Undercounted: the seventh writer is the engine's
  own beat thread, inside the engine process (06). The table's "Crash leaves" column should also say "a landed run shown as lost".
- **`tests/land/test_problem_kinds.py` docstring: "a new kind cannot be forgotten".** It cannot be forgotten in those four tables. It can be
  forgotten in `Fixer.fix`'s `str` signature, in any new table, and in every other enum in the engine (03, 30). The claim should be a rule test,
  not a slice test.
- **`tl/contracts/runlife.py:1-3`: "A run's state is RECORDED by its writer ... never inferred from a log gap".** The state is recorded by two
  threads with get-then-put and no ordering, so what is recorded is sometimes the older write. The sentence is the design intent, not the code's
  guarantee.
- **The brief's own framing, "the class of the STALE KeyError (an unhandled enum value crashing the fix round)".** The crash was the cheapest
  part of the incident. The class worth naming is the ladder around it: no traceback (01), no event (17), no deadline (16), a transient park with no
  cap (02), a release hop at the same step (23). Fixing enum totality alone leaves a 70-minute run one `ValueError` away from the same loss, since
  `stages.py:143-146` and `run_once.py:102-103` route `ValueError` to `FAULT_ENGINE` with no traceback either.
- **`zoom-out-review.md` R5 (engine steps as functions returning transitions) ranked last (wave 3).** Agree with the destination; disagree with
  the order from this lens. The failure-mode items above (01, 02, 06, 16, 17, 23) are all S or M, independent of R1/R5, and each removes a way
  for Trust Night to lose a night. They belong in wave 1 with Z01-Z03.
