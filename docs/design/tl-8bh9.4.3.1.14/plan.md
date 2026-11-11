# Trigger: rounds start by themselves (`tl plan rounds`)

Task: tl-8bh9.4.3.1.14 (proposed id; not in the tracker). Design, 2026-11-10, against HEAD ee5dde41b; built the same day
(section 25, as built; not run live). Design-time commands run, all read-only: source and doc reads; the policy line counter over HEAD;
`bd version`, `bd context`, `bd events --help`, `bd events tail --help`, `bd hooks --help`, `bd dolt --help`,
`bd config get events-journal`, `bd config list` (sync keys only); `bd ready --json -n 0 [--label auto]` and
`bd show --json` timed with the shell's `time` on this repository's tracker; one timing loop of a read-only SQLite
open plus count query on a throwaway file; reads of the installed `process_lock` 0.2.1, `stream_proc` 0.5.0
(`registered.py`, `owned.py`) and `beads_client` 0.2.0 (`runner.py`).
Revision 2 (same day) applies the owner's answers (section 22): 60 s default; **never a service, never at boot: always
started by hand in a terminal, foreground**; first Ctrl-C a graceful stop, a second an abrupt exit (section 7); no
tracker events now; question 5's renewal is a separate follow-up task (section 16). The supervisor and service material
of revision 1 is removed.

Read: CLAUDE.md, glossary, [.8.7](../tl-8bh9.8.7/plan.md), slices [.2](../tl-8bh9.4.3.1.2/plan.md) to
[.13](../tl-8bh9.4.3.1.13/plan.md) (.13 sections 4 to 7a and 15 in full), the [live smoke](../tl-8bh9.4.3.1.4/live-smoke.md)
(Run G and sections 7 to 9); source `plan_next, plan_ops, plan_admit, plan_launch, plan_reads, plan, attempt_entry,
slot_lock, slots, machine_config, cli_plan, cli_composition`, `.importlinter`, `tests/rules/test_policy.py`.

## 1. Words

| Word | Meaning here |
|---|---|
| **round** | One `plan_next.advance` (.13): settle existing attempts, admit eligible tasks into free slots, publish. Unchanged. |
| **rounds** | The verb `tl plan rounds`: rounds one after another in one foreground process until it is stopped. Ordinary English, no new entity, no factory.db row. Not `run` (the glossary reserves it) and not `loop` (.13 avoids it as a factory noun: the baseline's loop and lane meant a scheduler process). |
| **interval** | The time between the end of one round and the start of the next regular round (`--every`, section 12). |
| **check** | The local read of factory.db's slot reservations every 2 s between rounds (section 6). Ordinary English, not the checks step. |
| **slot freed** | A reservation row that existed at the end of the last round is gone (section 6). |

## 2. What is asked, and what is already settled

The owner, 2026-11-10: one-shot `tl plan next` stays the debugging tool; the ideal is event-driven, but a resident
process checking every 10 s to 1 min is acceptable and cheap ("if a free slot exists, scan ready tasks, sort, admit
top X"); a new task must not wait half an hour; no extra monitoring or redundancy until a real case; no stuck detection
and no factory-side stopping; a reboot or network loss mid-start continues by itself, reported in logs. Answers to
revision 1: the rounds process is always started by hand in a terminal and stays there in the foreground, never
installed as a service or started at boot; first Ctrl-C stops gracefully, a second exits at once.

Settled and not reopened: a round is stateless and idempotent and any trigger may call it at any time, concurrently
included (.13 section 5); every round action is an existing fenced operation; "multiple schedulers using one
reservation protocol, not a new daemon" (lifecycle); skills are helpers, never a scheduler; runtime version fixed until
restart (CLAUDE.md); no subprocess, spawn, signal or wait in factory source; logs are never read for control.

## 3. Facts measured or read

| Fact | Value | Source |
|---|---|---|
| `bd ready --json -n 0 --label auto` | 0.37 to 0.47 s wall, 0.35 to 0.41 s user CPU (3 runs); 11 rows, 4 distinct parents, all 4 outside the ready set | timed on this repository's tracker (1238 tasks, 174 ready, embedded Dolt) |
| `bd ready --json -n 0` | 0.35 to 0.36 s wall | same |
| `bd show <id> --json` | 0.47 s wall | same |
| A round that has candidates | 1 ready read + 1 `show` per unique missing parent (memoized) + 1 `show` in admission (`_task`), so 6 calls, about 2.5 s and 2 s CPU here, before any Git read | `plan_next._admit`, `selection.order` (ancestry only for eligible rows), `plan_admit._prepare` |
| A round with no eligible candidate | 1 ready read (0.4 s CPU); rows already attempted are skipped before any ancestry read | `selection._eligible` runs first |
| Today, all slots held | the round still reads the tracker (6 calls here) and only then admission answers `no_free_slot` | `plan_next._admit`, `plan_admit._observe` after `_prepare` |
| Reservation read on factory.db | 0.05 ms per read-only open plus `count(*)` (1000 runs in 0.05 s) | throwaway SQLite file |
| bd hooks | Git hooks only (pre-commit, post-merge, pre-push, post-checkout, prepare-commit-msg); nothing on task create or update | `bd hooks --help` |
| bd events journal | `events-journal` is `false` on this tracker; enabling is `bd config set events-journal true`, a tracker config write | `bd config get`, `bd events --help` |
| journal scope | per branch and per replica; `bd dolt pull` and merged changes are **not** journaled ("a consumer ... must re-baseline after a sync"); each replica has its own `seq`; retention floors 7 days / 100k rows; a read below the floor fails `events_journal_truncated` | `bd events --help`, `bd events tail --help` |
| journal consumption | `bd events tail --since N --follow --json`: one resident bd process printing JSON lines; the consumer keeps its own `seq` | same |
| Where a slot frees | the entry releases its own slot (reservation row deleted, still under the slot lock), then releases the lock, then publishes once, then exits; also `tl plan verify` and `tl plan release` | `attempt_entry` docstring and `_claimed`, `plan_release` |
| Entries and the launching process | `popen_registered(..., start_new_session=True)`: the entry is a **child** of the process that launched it, in its own session and process group; the launcher drops the `Popen` | `plan_launch.launch`, `stream_proc.registered` |
| An exited child of a resident process | stays a zombie until reaped; CPython's `Popen.__del__` puts it on `subprocess._active`, and every later `Popen` (each `bd` and Git call) reaps it; a zombie is observed `gone` (`owned.py`: state `Z`/`X`), holds no descriptor and no slot lock | CPython 3.15 `subprocess`, `stream_proc.owned` |
| Entry environment | `env=None`: the entry inherits the launching process's whole environment (PATH, SSH agent socket, Codex home) | `plan_launch.launch` |
| The attempt deadline | fixed at admission; the agent's timeout is `deadline - now` at dispatch (`plan._run`); the launcher's registration fence refuses an expired admitted attempt | `plan.py`, `plan_store.register_entry` |

## 4. The three options

| | (a) `--every N` plain loop | (b) event-driven: bd events + slot-freed signal | (c) hybrid: local check, tracker only when a slot is free, wake when a slot frees |
|---|---|---|---|
| New approved task waits | up to N | about the journal follower's delay, but only for tasks created **on this replica**; a task arriving by sync is not journaled, so a poll is still needed | up to N (60 s default) |
| Freed slot waits | up to N | the slot-freed signal's delay (it is not a tracker event in any option) | the check, about 2 s, plus the round |
| Tracker calls, all slots held | 3600/N per hour, each round 1 to 6 calls (at N = 10 s: 360 to 2160 calls, 4 to 24 % of a core here) | none from polling; one resident bd process | **none** |
| Tracker calls, a slot free, nothing eligible | 3600/N rounds per hour, 1 call each | journal records only, plus the fallback poll | 60 per hour at the default (1 call, 0.4 s CPU each: about 0.7 % of a core) |
| Relaunches and publish retries | one per round: 3600/N per hour per affected task | as (c) | one per regular round: 60 per hour per affected task |
| New moving parts | the loop | the loop, plus a bd child process the factory owns (spawn, read, restart when it dies, through `stream_proc`), a `seq` cursor, re-baselining after every sync, a tracker config write on every tracker | the loop, one SQLite read every 2 s, one store read method |
| What still needs a poll | everything | synced tasks, priority and label changes from other replicas, settle and publish | n/a |

(b) is strictly more than (c): its tracker events cover only local writes, so (c)'s regular round stays underneath it,
and the slot-freed signal is the same factory.db fact as in (c). Its only gain is a lower wait than the interval for a
task written on this machine.

**Decided: (c) without tracker events.** It meets "no 30-minute wait" with a 1-minute bound, reacts to a freed slot in
seconds (the event-driven part the owner wants, on the fact that actually limits throughput), reads the tracker only
when admission could take something, and adds no process, no cursor and no tracker config. Tracker events stay
possible later as one more wake source of the same loop (section 21), never as state.

## 5. The shape

```
tl plan rounds ... --every 60
  take the rounds lock for (factory.db, backlog)             refused:rounds_running if held (section 8)
  repeat:
    one round: advance(fresh per-round ports, request, quiet=previous round's moves)
    baseline = the reservation rows in factory.db now
    delay    = interval, or the backoff delay after an unavailable round (section 11)
    every 2 s until delay passed: read reservations; if a baseline row is gone -> next round at once
  until: first Ctrl-C (graceful: no new move, end line, exit 0) / second Ctrl-C (abrupt, exit 130)
         / a whole-round refusal (exit 1)
```

Inside the round, one new rule (section 15): **admission reads the tracker only when factory.db has an adopted slot
without a reservation row.** Slot freedom is a factory.db fact first, so a round with every slot held makes no tracker
call. Settling (relaunch, verify, repeat, reports) and publication run every round as today; they need no tracker read.

## 6. The signal for a freed slot, and who owns it

The fact is **a reservation row removed from factory.db**. Its one owner is the release (`plan_release`): the entry's
own settled release at the end of its step, a `tl plan verify`, or a person's `tl plan release [--abandon]`. The rounds
process only reads it; nothing new writes anything.

| Candidate signal | Why not |
|---|---|
| the entry process ending | it ends after its publish, which can take seconds to minutes after the slot is already free; a person's `tl plan release` frees a slot with no entry ending; observing the exit of an entry this process did not start (a previous rounds process, `tl plan start`) needs pidfd/kqueue, a platform API with no shelf owner; waiting on our own children is the forbidden wait escape hatch |
| a wake file written by the entry or the release | a second writer of a fact factory.db already holds, a file side channel for factory state (CLAUDE.md), and the entry would have to know a scheduler exists (.13 rejected a scheduler inside the entry) |
| SQLite `PRAGMA data_version` or the file's mtime | says only "something changed", so the same read follows; the direct read already costs 0.05 ms |
| **the reservation rows, read every 2 s** | one read-only open and one SELECT on the owner's table; no writer, no new process |

**Wake rule:** after each round the rounds process reads the set of reservation rows (`(repo_id, slot, attempt_id)`).
Every 2 s until the next regular round it reads them again; when any row of that baseline is gone, the next round starts
at once. A row added (another admission, a repeat's takeover keeps the row) never wakes. An idle backlog with a free slot
and nothing eligible never wakes (its baseline has nothing to lose), so the check cannot spin. A failed read (factory.db
missing, locked or of another schema) does not wake; the next regular round meets the problem and reports or refuses it.

**Residual, accepted:** the entry deletes its reservation under the slot lock and releases the lock a moment later. A
round woken in that instant observes the slot locked, so admission answers `no_free_slot`, and the slot is filled by
the next regular round (at most one interval). The check sees the change 0 to 2 s after it, so this needs the check's
read to fall within the few milliseconds between the entry's commit and its lock release.

## 7. Which process owns the rounds, and how it stops

**A foreground command the person starts by hand in a terminal (owner, 2026-11-10).** `tl plan rounds` never forks,
detaches, writes a pid file, installs itself or starts at boot; it is not a service. The factory has no daemon. Its
stdout and stderr are that terminal.

**Shutdown by keyboard.** A terminal's Ctrl-C sends SIGINT to its foreground process group: the rounds process and any
`bd` or Git child it is running at that instant (`subprocess.run` children share its group). Entries and their agents
are in their own session (`start_new_session=True`), so no Ctrl-C reaches them: a step already launched keeps running
whatever the rounds process does.

| Press | Mid-wait (between rounds) | Mid-round |
|---|---|---|
| **first Ctrl-C: graceful** | the current 2 s check slice ends (`time.sleep` is resumed after a handler that does not raise, PEP 475, so at most 2 s), no further round starts; `rounds stopped interrupted` is written; exit 0 | the move being performed finishes (or fails cleanly, below); the round performs **no further move** (no relaunch, repeat, verify, start or publish after it), closes with `round moves=<n> stopped=interrupted`, then `rounds stopped interrupted`; exit 0 |
| **second (or later) Ctrl-C: abrupt** | `KeyboardInterrupt` at once | `KeyboardInterrupt` at once, wherever the round is |

The terminal shows `Stopping after the current move; Ctrl-C again to exit at once.` on the first press.

**Mid-round precisely.** The round asks `stopping()` before each move (each settle action, each admission candidate,
each publication) and stops at the first True, so the safe point is "between two existing operations", each of which is
fenced and crash-safe on its own. The move in flight is not interrupted by the factory, but the same Ctrl-C also reached
its `bd` or Git child, if one was running: that child dies, the call fails, and the operation takes its own error path
as for any tool failure: a `bd` claim answers `BdError` and admission compensates (or reports `claim_leaked`), a Git call
is `unavailable:git`, a publish `unavailable:*` (retried by the next round of the next process). A move whose
operation ran no child at that instant (SQLite, the process table, the launcher's registration) completes normally. The
round's stopped word is `interrupted` whatever admission would have said.

**Abrupt.** The second press raises `KeyboardInterrupt` wherever the process is; nothing waits. The CLI catches it
around the operation, makes one best-effort append `rounds stopped abrupt` (an `OSError` or a further press during it is
ignored), prints `Stopped at once.` to stderr and exits **130** (128 + SIGINT, the shell's convention for an interrupted
command). A third press during that append leaves Python's own handling: the process ends by SIGINT, which a shell also
reports as 130. Abrupt is safe for the reason .13 section 6 gives: every round action is a fenced operation, and the next
`tl plan rounds` continues from factory.db. The one accepted residual is the existing one of every admission (`tl plan
start` and `tl plan next` included): a stop between the tracker's claim commit and factory.db's commit can leave a claim
held with no attempt row and no report; a person checks `bd list --status in_progress --assignee taskloop` against
`tl plan list` (runbook section 8). The graceful press exists so that a person who presses once never lands there,
except through a `bd` child killed by that same press, which admission compensates.

**How, and the CLAUDE.md reading.** Plain stdlib `KeyboardInterrupt` cannot give the graceful press: it is raised at an
arbitrary bytecode, mid-operation, so "finish the current move" needs a handler. The narrowest one: a new module
`interrupts.py` (~30 lines) is the only importer of `signal` in factory source; it installs, for the life of `run_rounds`
only, a SIGINT handler that sets a flag, writes the one terminal line and restores `signal.default_int_handler` (so the
next press is Python's ordinary `KeyboardInterrupt`); on exit it restores the previous handler. It uses
`signal.signal(SIGINT, ...)` and `signal.default_int_handler` only: no other signal, no `os.kill`, `killpg`, `alarm`,
`setitimer`, `pthread_kill` or `set_wakeup_fd`, and it signals no process. **Reading of CLAUDE.md** ("Factory source and
tests have no subprocess imports/usage or direct spawn/signal/wait escape hatch"; "use owning shelf ... process ...
APIs"): the rule forbids controlling other processes around the shelf's process API: spawning, signalling or waiting on a
process. Choosing how this process reacts to its own keyboard interrupt controls no process and has no shelf owner, so I
read it as outside the rule; but the words say "signal", so it is bounded and made checkable: an `.importlinter`
contract "only `taskloop.interrupts` imports `signal`" (`signal` joins `root_packages`), and a policy test that
`interrupts.py` references no `signal` attribute but `signal`, `SIGINT`, `default_int_handler` and `getsignal`. Tests
never install it or send a signal (section 18). This reading is the owner's to confirm (question 5).

`tl plan next` keeps Python's default Ctrl-C (one-shot; its `stopping` port is always False).

**Restart and reboot.** After a reboot nothing starts by itself; the person runs `tl plan rounds` again. The first round
runs immediately, with nothing suppressed in its log (section 9), so after any restart the log shows every attempt's
state once. An intact factory.db continues: admitted attempts whose entry is gone are relaunched, captured ones
verified, unpublished ones published, exactly as .13 section 6 lists (and, with the follow-up of section 16, an admitted
attempt from before the reboot gets a fresh deadline). A deliberate whole-DB discard while it runs makes the next round
refuse `database`, and the process exits 1 (the discard steps gain "stop `tl plan rounds` first", section 20).

**Process facts the runbook states (findings, not code):**

- **Environment.** Entries inherit the rounds process's environment (section 3), so they see the terminal shell's PATH,
  SSH agent and Codex home: start it from the shell where `bd`, `git push` and `codex` work.
- **Version.** The rounds process keeps the code it started with; each entry it launches imports the package installed
  at launch time (`python -I -m taskloop.attempt_entry`). After installing a new version, restart `tl plan rounds`
  (CLAUDE.md: runtime version fixed until restart). No version check is added. During a smoke, gates (`just check`,
  `just test`) reinstall the package and must not run in the checkout the rounds process runs from.
- **Zombies.** An entry that exits stays a zombie of the rounds process until the next `bd` or Git call reaps it
  (CPython's `subprocess` bookkeeping; section 3). It is observed `gone`, holds no lock or descriptor, and at most one
  per slot can wait: no change. If it is ever observed to matter, reaping belongs in a `stream_proc` API, never in
  factory source.
- **Closing the terminal** sends SIGHUP, which ends the rounds process with no line (as a kill does); entries go on. Not
  supported as a stop, only safe.
- Unsupported aside: running it under a service manager is not a supported setup; one would at least need systemd's
  `KillMode=process`, since the default kills the entries in the unit's cgroup.

## 8. One rounds process per backlog

**Decided: a lock, taken without waiting, held for the process's life.** Two rounds processes are safe (fences, .13
section 6) but double every tracker read, race for each freed slot with a claim and compensation pair, and interleave
two traces in one log; the likely cause is a person starting it in a second terminal and forgetting the first. The lock is a
`process_lock` flock on `<factory.db>.rounds-<backlog>.lock` beside factory.db, taken with `timeout=0`, `reentrant=False`,
label `taskloop-rounds`, meta `{"backlog": ...}`. A second `tl plan rounds` for the same factory.db and backlog refuses
`refused:rounds_running` before any round, naming the holder record's pid (informational, nothing decides on it) and
exits 1. Another backlog has its own lock. The kernel frees it when the process dies; nothing deletes the file (as slot
locks). A backlog that is not one plain word (`plan_next.IDENT`) refuses `refused:backlog`.

**Not locked:** `tl plan next`, `tl plan start` and a future dashboard round run beside the rounds process (the fences
make that safe); a person's one-shot round is the way to "run a round now".

`slot_lock` stays the slot custody owner. The new module `rounds_lock.py` is the second importer of `process_lock`; the
`.importlinter` contract becomes "only slot custody and the rounds lock import the process lock library".

## 9. Logging: `rounds.log` only, no idle lines

All output goes to the existing `<artifacts>/rounds.log` through `PlanFiles.log_round` (.13 section 7a: fixed words,
never read for control, never rotated). Stdout gets one start line (`Rounds for backlog B every 60 s; log:
<artifacts>/rounds.log; stop with Ctrl-C`), and the final line or refusal; nothing per round.

- **A move identical to one in the previous round is not written again** (same task, action, word and attempt id).
  The round passes the previous round's move keys as `quiet` (section 15); the moves are still in the result. So a
  running attempt is written once when it starts running, a failed one once, a stuck one once per change, a publish
  refused `diverged` once until its word changes. A `start` is never quiet (each has a new attempt id). A relaunch
  repeated every round for a persistent cause is written once; each relaunched entry's own line is in that attempt's
  `entry.log` (.13 section 4).
- **The closing line** `round moves=<n>[ stopped=<word>]` is written only when the round wrote a move line, or its
  `stopped` word differs from the previous round's. An idle round writes nothing.
- **Lines of the rounds process**, same format and `WORD` rule: `rounds started every=<s> pid=<pid>`, `rounds wait
  seconds=<s> after=<word>` when the backoff delay changes (and `rounds wait seconds=<every>` once when it returns to
  normal), `rounds stopped interrupted` (graceful), `rounds stopped abrupt` (best effort, section 7), `rounds stopped
  <kind>:<reason>` (a refusal).
- **Volume:** at most a few lines per step a task takes; an idle factory writes nothing; a restart rewrites the current
  state once.
- **Unwritable log:** the rounds go on unchanged; one stderr line `Log: not written (<path>)` each time `logged` turns
  False after being True, in the terminal.

`tl plan next` keeps .13's behaviour: every move and the closing line (`quiet` is None).

## 10. Claim lease and heartbeat

Unchanged (.9, .13 section 6). The entry renews the claim's bd lease every 100 s while its step runs; the rounds
process never renews, retakes or reads a claim. The interval is independent of the lease. A claim reverted by `bd
reclaim` after a step makes the task open; rounds skip it `attempted`, written once (section 9). An admitted attempt
refused `claim_lost` is relaunched by each regular round until its deadline, one bd heartbeat call per round: at the
60 s default and a 30-minute deadline, at most 30 relaunches, one log line (the rest quiet) and 30 `entry.log` lines.

## 11. Error backoff

**Bounded, and no detector.** After a round that is a whole-round `Failed` with kind `unavailable` or `uncertain` (the
store), or a `Round` whose `stopped` word is `unavailable:*` or `uncertain:*` (tracker, Git, store at admission), the
next regular round waits twice the last delay, from the interval up to **300 s**; the first round without one returns
to the interval. The cap keeps a new task's wait after recovery at 5 minutes at worst. Per-task words (a publish
`unavailable:remote`, a verify's `branch=` word, `skip unavailable:ancestry`) never back the rounds off: they concern one
task, and publication is already one push per regular round. The slot-freed wake still starts a round during a backoff
(at most once per step that ends). Nothing is stored; a restart starts at the interval.

## 12. Configuration

| Value | Flag | Machine config key | Default | Rule |
|---|---|---|---|---|
| interval, seconds | `--every SECONDS` | `round_seconds` | 60 | integer >= 5, else refused `interval` (`machine_config`, flag > file > default, no environment) |
| local check | none | none | 2 s | constant `CHECK`; nothing to tune |
| backoff cap | none | none | 300 s | constant `CAP`, or the interval if it is longer |

The interval is a machine-level property (how often this machine polls its tracker), so it joins the machine config
beside `slot_count` and shows in `tl config show`. The round's choices (backlog, tracker root, checkout, label, model,
effort, minutes) stay required flags, as for `tl plan next` (.13 decided no config keys for them). The rounds process
validates them before the first round: label, model and effort non-blank, minutes >= 1, backlog a plain word; a failure
refuses and exits 1 before the lock or any read.

## 13. Exit codes

| Code | When |
|---|---|
| 0 | graceful stop: the first Ctrl-C (a stop asked for is a success) |
| 130 | abrupt stop: a second Ctrl-C (128 + SIGINT; the CLI returns it, or Python's own SIGINT exit gives the same to the shell) |
| 1 | refused before the first round (machine config, inputs, `rounds_running`, `backlog`), or a whole-round refusal at any round (`database`, `schema`, `label`, `tracker_root`); an uncaught exception is Python's own 1 with a traceback (a defect) |
| 2 | usage (argparse) |

Never 3: what a one-shot round answers with 3 (rerunning is safe) is what the rounds process does by itself, after the
backoff. A round stopped by a `refused:*` word of one task or of admission (`refused:task`, `refused:checkout`) does not
end the process: it is written once and the next round tries again.

## 14. One operation, every surface

`plan_rounds.run_rounds(ports, request) -> Ended` is the one application operation for repeated rounds; each round is
the existing `plan_next.advance`. Surfaces:

- **`tl plan rounds --backlog B --tracker-root DIR --checkout DIR --label L --model M --effort E --minutes N
  [--every SECONDS] [--db] [--artifacts] [--json]`**. Help: "Run scheduling rounds until stopped (Ctrl-C): a round at
  once, then every --every seconds and as soon as a slot frees; the tracker is read only when a slot is free; writes
  `<artifacts>/rounds.log`; plan step only: publishes task/<id>; no merge or land. Runs in this terminal until stopped:
  Ctrl-C once stops after the current move, twice exits at once; launched steps keep running." `--json` prints the start, the end and refusals as JSON (`{"status": "rounds",
  "backlog", "every", "log"}`, `{"status": "ended", "backlog", "reason"}`, refusals the `{"error": ...}` shape).
- **`tl plan next`**: unchanged surface; it also gets the free-slot gate and the publish rule of section 15.
- **Dashboard (later, out of scope):** "run a round now" calls `advance`, as `tl plan next`; it shows whether rounds run
  for a backlog by reading the rounds lock's holder record (`rounds_lock.holder`, informational). It never hosts the
  rounds process: that would put a scheduler inside a viewer.
- **Skills** may start `tl plan rounds` or run `tl plan next`; they own nothing.

## 15. Changes inside a round (`plan_next`)

1. **Free-slot gate.** Before the ready read, `_admit` reads `reads.store.slot_use()` (section 17). When every adopted
   slot in factory.db has a reservation row, admission ends with `stopped = "no_free_slot"` and **no tracker call and no
   skip moves**. The count is over all repos in factory.db: another repo's free slot can only cause a needless tracker
   read (admission still answers `no_free_slot`), never a missed one, since a free slot is always unreserved. A slot
   unreserved but not free (dirty, detached elsewhere, locked) passes the gate; admission's own observation decides, as
   today, at one tracker read per regular round. A failed `slot_use` read falls through to admission, which reports the
   store itself. Applies to `tl plan next` too (one owner of the rule); Run G's checks still hold (G2 stops
   `no_free_slot`; G5 runs with the slot free).
2. **`quiet`.** `NextRequest.quiet: frozenset[tuple[str, str, str, str]] | None = None`. `_Trail.add` does not write a
   move whose `(task, action, word, attempt)` is in `quiet`; `close` writes the closing line when `quiet` is None, when a
   move line was written, or when `("", "stopped", stopped, "")` is not in `quiet`. `plan_next.reported(round)` returns the
   keys of a round (moves plus its stopped word) for the next one.
3. **Publication waits for a running entry.** `_publish` skips a `publish` row whose entry is observed running: that
   entry publishes it itself right after its release (section 6), and the slot-freed wake would otherwise make the round
   push the same commit at the same moment as the entry. If the entry's push fails, the next round after it exits pushes.
4. **The graceful stop's safe points.** `Advancing.stopping: Callable[[], bool]` (the one-shot opener binds
   `lambda: False`). `_settle`, `_admit` (before the ready read and before each candidate) and `_publish` ask it before
   each move; at the first True the round performs no further move and closes with `stopped = "interrupted"` (which
   replaces any admission stop word). `interrupted` joins the exit rule as a non-failure word (exit 0 for a one-shot
   that never sees it; the rounds process ends gracefully on it).

No new state word, store write, Git write or tracker write.

## 16. Question 5 from .13: an admitted attempt that expired during downtime

**Decided, owner-confirmed 2026-11-10: continue it automatically after a reboot; keep it reported otherwise.** A
separate **follow-up task**, not part of this slice: it changes the launcher's fence and adds a store write, not the
trigger. This slice builds nothing of it; until it lands, an admitted attempt expired by a reboot stays
`stuck:expired_admitted`, as today. Its small design:

- With rounds every 60 s, an admitted attempt is relaunched within one interval of the person starting `tl plan rounds`
  again, so expiry needs an outage (including the time until that restart by hand) longer than the deadline. Only a reboot (or power loss) realistically does that
  mid-start: network loss does not stop an entry before dispatch (its pre-dispatch reads are the local tracker, Git and
  files); it fails a running agent, which is a failed result, not this case.
- **Rule:** a relaunch of an `admitted` attempt whose registered entry is from **another boot** (stored `entry_boot` not
  the current boot id) first renews the attempt's deadline to now plus the request's `--minutes`, in one fenced write
  (phase `admitted`, same key and reservation, entry from another boot), then registers as today. It applies whether or
  not the old deadline passed, which also fixes the short agent time a late relaunch would otherwise get (`plan._run`
  gives the agent `deadline - now`). Same attempt id: the trace is the same attempt's `relaunch` line and `entry.log`.
- **Why only another boot:** the deadline is the only bound on relaunches for a persistent same-boot cause
  (`claim_lost`, `slot_busy`, .13 section 4). A boot change is a stored fact compared with the current boot id, so the
  renewal happens at most once per reboot and needs no counter, no log read and no schema change (the `deadline`
  column exists; `tests/rules/test_policy.WRITERS` gains one UPDATE owner).
- **Not covered, stays reported:** an attempt whose entry was never registered (power lost inside the launch's ~5 s
  registration window) keeps its deadline; a same-boot expiry stays `stuck:expired_admitted` (abandon, then `tl plan
  start`). An attempt `dispatching`/`registered` at a reboot is `stuck:entry_lost`: session resume, out of scope.
- **Rejected:** abandon and re-admit by a round (contradicts "an abandoned task is never retried by a round" and
  changes a person's abandon); renew on every relaunch (removes the bound).
- **Follow-up scope:** `plan_launch` (renew before registration when the stored entry's boot is not `boot_id()`, the
  request's minutes passed in for a relaunch), `plan_store` (one fenced UPDATE of `deadline`), `plan_next._resume` and
  `tl plan start` passing minutes; tests: another boot renews once, the same boot never renews, the fence refuses a
  changed key or a non-`admitted` phase; GUIDE `stuck:expired_admitted` names the rule. About +40 SLOC.

**As built (2026-11-10, uncommitted, on 283ae2271).** Differences from the text above, each the smaller correct form of
what is built:

- **The renewal is the registration's own write, not a separate UPDATE before it.** `PlanStore.register_entry` takes
  `renewed` (the launcher passes its clock plus `minutes * 60`) and, when the stored entry it replaces carries another
  boot id than the identity being registered, sets `deadline=renewed` in the same fenced UPDATE that writes `entry_*`
  (same immediate transaction: key, held reservation, phase `admitted`, the exact replaced identity), past deadline or
  not. The renewed deadline is `max(stored, renewed)`, so a renewal never shortens a live deadline; a renewal that is
  not finite or not after `now` is refused (`registration_refused`) and writes nothing, so it is not consumed (the
  launcher turns minutes no float holds into an infinite renewal, which the store refuses). A separate write before registration would renew again on every relaunch whose start failed before it registered
  (`start`, `log`, `store`), which removes the bound; in one write the new entry is this boot's, so a second relaunch in
  the same boot never renews. The current boot is the registered child's identity (`popen_registered`), so the launcher
  needs no boot read. `WRITERS` gains no row: `UPDATE plan_attempt` is already `plan_store`'s (the row now says so).
- **The status had to change too.** `next_step` answered `stuck:expired_admitted` for any expired admitted attempt, so a
  round would never have reached `_resume`. `Reads` gains a `boot` port (`composition.current_boot`: this process's own
  identity through `stream_proc.inspect_process`, because `boot_id` is not public in the shelf library), and an expired
  admitted attempt whose stored `entry_boot` differs from a known boot is `start` (`next_step(..., rebooted=True)`); an
  unknown boot never counts as a reboot. `dispatching`/`registered` stay `stuck:entry_lost`.
- **Minutes pass through every launch**: `Launch.launch(backlog, task_id, minutes)`; `tl plan start`, `plan_next._resume`
  and `PlanRepeat` (its own and `_existing` launches) pass the request's `--minutes`. `--minutes` is now bounded from 1
  to `plan_ops.MAX_MINUTES` (a week) by one check, `plan_ops.minutes_refused` (`refused:choices`), in `tl plan start`,
  `tl plan next` (after the label check, before any read) and `tl plan rounds`' input checks (which before checked >= 1
  only); admission had no upper bound.
- GUIDE `start` and `stuck:expired_admitted` name the rule (the latter: the deadline passed with no relaunchable entry
  from before a reboot: none registered, one from this boot, or the boot unknown); the live smoke gains an optional owner-run reboot check
  after Run H (a reboot is only faked in tests by a stored boot id).
- Tests: `test_entry_store` (another boot renews once, the same boot and a first registration never renew, the fence
  refuses a changed key, a wrong replaced identity and a non-`admitted` phase; a renewal at or before now, infinite or
  NaN is refused and a later valid one still renews; a renewal never shortens a live deadline), `test_launch` (a
  relaunch over an other-boot entry at t=200 stores deadline 200 + 30 min; minutes no float holds refuse and keep the
  stored entry; `current_boot` is this process's native boot, None when unknown), `test_ops` (the next-step row, `tl
  plan show` with another, the same and an unknown boot, minutes reaching the launch, out-of-range minutes refused
  before any read), `test_repeat` (both `PlanRepeat` launches pass the request's minutes), `test_next` (a round
  relaunches an expired other-boot attempt with the request's minutes; `dispatching` stays `stuck:entry_lost`; minutes
  out of range refused before any read), `test_rounds` (the upper bound).
- **Residual:** after a reboot, until one relaunch registers, the attempt shows `start` past its deadline, so a start
  that keeps failing before its registration (`unavailable:start`, `log`, `store`) is retried every round without the
  deadline's bound; the first registration (also an exec failure after it) renews and the bound returns. Not observed
  live: a real reboot (runbook, after Run H).

## 17. Modules and caps

SLOC by the policy counter today -> estimate; caps 400 file, 80 function, 800 test file.

| Module | Change | SLOC |
|---|---|---|
| `plan_rounds.py` (new) | `RoundsRequest(backlog, every)`, `Pacing` ports (`round: Callable[[Quiet \| None], Round \| Failed]`, `slot_use: Callable[[], SlotUse \| None]`, `clock` wall for log stamps, `monotonic` for pacing, `wait`, `log`, `warn`, `stopping`), `Ended`, `run_rounds` (graceful end on `stopping()`; lets `KeyboardInterrupt` through as the abrupt stop), `_once` (round, quiet keys, backoff word), `_pause` (2 s checks until due or a baseline row gone), `_delay` (doubling, cap), `_line` | ~115 |
| `rounds_lock.py` (new) | `lock_path(db, backlog)`, `hold(db, backlog) -> ProcessLock` raising `RoundsRunning(pid)` or `RoundsLockUnavailable`, `holder(db, backlog)` | ~35 |
| `interrupts.py` (new) | `Interrupts` (flag, `press()`: set the flag, say the line, restore the default handler), `installed(interrupts) -> context manager` (the only `signal.signal` calls: install for SIGINT, restore the previous handler on exit) | ~30 |
| `plan_next.py` | `NextRequest.quiet`, `_Trail` quiet rule, the gate in `_admit`, `_publish` skips a running entry, `Advancing.stopping` safe points, `reported` | 178 -> ~210 |
| `plan_reads.py` | `SlotUse(adopted: int, held: frozenset[tuple[str, str, str]])`, `PlanReads.slot_use()` (two SELECTs, `StoreUnavailable` on failure) | 166 -> ~180 |
| `machine_config.py` | `round_seconds` key, `Flags.round_seconds`, `_seconds` check, refusal `interval` | 89 -> ~98 |
| `plan_ops.py` | `Ended` in the `Result` union, `exit_code` case (interrupted 0, refused 1; 130 is the CLI's, below) | 360 -> ~367 |
| `plan_data.py` | the start and `Ended` shapes | 87 -> ~95 |
| `cli_plan.py` | `rounds` parser, `_rounds` (input checks, start line, render; catches `KeyboardInterrupt` around the operation: best-effort `rounds stopped abrupt`, `Stopped at once.`, return 130), GUIDE rows `rounds_running`, `interval`; `discard` step 1 names `tl plan rounds` | 339 -> ~375 |
| `cli_composition.py` | `open_plan_rounds(db, artifacts, request)`: input checks, the lock, the installed `Interrupts`, `Pacing` with a per-round `open_plan_next` + `advance` (its `stopping` the same flag), a per-call read-only `slot_use`, `time.time`, `time.monotonic`, `time.sleep`, `PlanFiles.log_round`, stderr `warn` | 146 -> ~185 |
| `.importlinter` | `plan_rounds`, `rounds_lock`, `interrupts` join `cli-never-imports-the-attempt-entry` sources; `plan_rounds` and `interrupts` join `entry-never-imports-the-command-surface` forbidden; `one-slot-lock-owner` renamed, ignore `taskloop.rounds_lock -> process_lock`; new `one-signal-owner`: `signal` in `root_packages`, forbidden to `taskloop`, ignore `taskloop.interrupts -> signal` | |
| `tests/rules/test_policy.py` | `interrupts.py` uses no `signal` attribute but `signal`, `SIGINT`, `default_int_handler`, `getsignal` (AST check) | +~12 |

Every function stays a short sequence (at most four returns, C90 12). No subprocess, wait, `Any`, `cast` or ignore; the
only signal use is the SIGINT handler of section 7, in one module; no new Git write, tracker write or schema change; no new dependency. The section 16 follow-up is separate
(`plan_launch`, `plan_store`, about +40 SLOC, its own tests).

## 18. Tests

Pytest functions and parametrized tables; no unittest, no subprocess, **no real sleep**: a fake clock serves `clock`
and `monotonic`, and the fake `wait(seconds)` advances it, records the call and, scripted, presses a fake stop (sets the
`stopping` flag) or raises `KeyboardInterrupt` after a set number of calls. **No test installs a signal handler or sends
a signal**: the graceful press is the `Interrupts.press()` method called directly (or a scripted `stopping` port), the
abrupt one a raised `KeyboardInterrupt`; `interrupts.installed` is covered by the policy rule and by Run H only.

- **`tests/plan/test_rounds.py`** (new, ~300 lines), `run_rounds` over a stub `round` port returning seeded results
  and a seeded `slot_use` sequence:
  - cadence: rounds at t = 0, 60, 120 (plus round time) with nothing freed; `wait` called in 2 s slices;
  - wake: a baseline row gone at t = 4 starts a round at t = 4; a row added, or an unchanged set, never wakes; an idle
    baseline (no rows) never wakes; `slot_use` returning None neither wakes nor fails;
  - backoff table: `unavailable:tracker` stops give delays 60, 120, 240, 300, 300, then a clean round returns to 60;
    a whole-round `Failed("unavailable", "store")` backs off and continues; `refused:task` does not back off; each delay
    change writes one `rounds wait` line, an unchanged one none;
  - quiet: the second round receives the first round's `reported` keys; the first receives an empty set, not None;
  - ends: whole-round `Failed("refused", "database")` -> `Ended` refused, `rounds stopped refused:database`, exit 1;
  - graceful, mid-wait: `stopping` turns True during a pause -> no further round, at most one more 2 s slice, `rounds
    stopped interrupted`, `Ended("interrupted")`, exit 0; graceful, mid-round: the stub round sees `stopping` True and
    returns `stopped=interrupted` -> no wait, no next round, the same end line;
  - abrupt: `KeyboardInterrupt` from `wait` or from the round propagates out of `run_rounds` unchanged (no end line from
    the operation);
  - log: `rounds started every=60 pid=<n>` first; a `log` raising `OSError` changes nothing but calls `warn` once.
- **`tests/plan/test_next.py`** (341 -> ~400): the gate (all slots held -> `stopped=no_free_slot`, the
  `FakeTaskReadClient` seeded with `ready_fault` is never called, no skip moves; one unreserved slot -> the ready read
  runs); quiet (an identical move not written, a changed word written, the closing line rule, `quiet=None` writes all as
  before); a `publish` row with its entry running is not pushed (recording publisher), with its entry gone it is;
  `reported` keys; safe points: a `stopping` port turning True after the first settle move leaves the second attempt
  untouched (recording ports), no ready read, no start, no publish, `stopped=interrupted`, closing line written; True
  between two candidates: the first started, the second never claimed.
- **`tests/plan/test_interrupts.py`** (new, ~40): `press()` sets the flag, says the line once and calls the injected
  restore once; a second `press()` (were it reached) does not say it again; the flag starts False.
- **`tests/plan/test_slot_lock.py`** (137 -> ~170) or a new `test_rounds_lock.py`: a second `hold` for the same db and
  backlog refuses with the holder pid (real lock file under `tmp_path`, `reentrant=False` refuses in-process); another
  backlog is independent; released when the holder releases.
- **`tests/plan/test_slots.py`** or the store tests: `slot_use` over the in-memory `factory` fixture (adopted count,
  held rows, an unreadable store raises `StoreUnavailable`) (~+20).
- **`tests/cli/test_config.py`** (125 -> ~145): `round_seconds` default 60, file, flag over file, 4 refused `interval`,
  a bool refused `type`; `tl config show` lists it.
- **`tests/cli/test_plan_cli.py`** (411 -> ~455): `plan rounds` help text, required flags, `--every` below 5 refused,
  blank label refused before any read, the start line and the end line (the operation stubbed at `cli_composition`),
  JSON shapes, exit codes 0 and 1, the `rounds_running` guide; the operation stub raising `KeyboardInterrupt` -> exit
  130, `Stopped at once.` on stderr, one `rounds stopped abrupt` line through a list log, and a log raising `OSError`
  then still exits 130.
- **`tests/plan/test_ops.py`**: `exit_code(Ended)` rows (~+8).
- **No new real-layer test:** the rounds process adds no Git, process or tracker mechanism; the lock is the existing
  library over a real file in the lock test. The live run is Run H.

## 19. Smoke runbook additions (owner-run; scratch tracker, `remote.git` and scratch paths only)

New **Run H (section 6g)** in the live smoke, after Run G, `slot_count = 1`, with Run G's move-aside first. Tab B runs
the rounds process in the foreground; tab A does the rest.

```bash
ROUNDS=(plan rounds --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --label auto --model "$MODEL" \
  --effort "$EFFORT" --minutes 30)
# tab B: a long interval, so a start seconds after a slot frees can only be the wake
T "${ROUNDS[@]}" --every 120          # H1: start line; rounds.log: rounds started every=120, then the first round
# tab A
H_ONE=$(cd "$TRACKER" && bd create "Smoke rounds one" -p 1 -l auto --silent)
H_TWO=$(cd "$TRACKER" && bd create "Smoke rounds two" -p 2 -l auto --silent)
printf 'H_ONE=%s\nH_TWO=%s\n' "$H_ONE" "$H_TWO" >> "$SMOKE/env.sh"
tail -f "$ART/rounds.log"            # H2: within 120 s `start started` for $H_ONE; then nothing while it runs
T "${ROUNDS[@]}" --every 120; echo "exit $?"   # H3 (tab C): refused:rounds_running naming tab B's pid, exit 1
T plan next --backlog "$BACKLOG" --tracker-root "$TRACKER" --checkout "$REPO" --label auto --model "$MODEL" \
  --effort "$EFFORT" --minutes 30 --json     # H4: works beside it: report running, stopped no_free_slot
T plan show "$H_ONE" --backlog "$BACKLOG"    # until Released; note its Released time
# H5: $H_TWO's `start started` line within ~5 s of $H_ONE's Released time (the interval is 120 s)
wc -l < "$ART/rounds.log"; sleep 300; wc -l < "$ART/rounds.log"   # H6, once both are done: no new line while idle
# H7, graceful: Ctrl-C ONCE in tab B while $H_TWO runs (the process is between rounds): the terminal says
#   "Stopping after the current move; Ctrl-C again to exit at once.", within 2 s `rounds stopped interrupted`; echo $? -> 0;
#   `ps` still shows $H_TWO's entry
T "${ROUNDS[@]}" --every 120          # H8, tab B again: the first round writes `report running` for $H_TWO once
# H9, abrupt: Ctrl-C TWICE quickly in tab B: `Stopped at once.`; echo $? -> 130; rounds.log ends `rounds stopped abrupt`
#   (best effort); `ps` still shows $H_TWO's entry if it still runs
T "${ROUNDS[@]}" --every 120          # H10: starts normally, no second entry; then Ctrl-C once to end the run
```

Optional **H11, backoff:** with nothing running, move `$TRACKER/.beads` aside for 5 minutes:
`rounds wait seconds=240 after=unavailable:tracker` lines appear; after moving it back a `rounds wait seconds=120` line
and the next round succeed.

| Check | Pass | Fail means |
|---|---|---|
| H2 new task | `$H_ONE` started within one interval | the trigger missed a ready task |
| H3 singleton | exit 1, `rounds_running` with a pid | two rounds processes for one backlog |
| H5 wake | `$H_TWO` started seconds after the release, not up to 120 s later | the slot-freed wake does not work |
| H6 quiet | no new line over 5 idle minutes | idle rounds write lines |
| H7 graceful | the notice, `rounds stopped interrupted` within 2 s, exit 0, the entry still running | the stop killed the step, or waited for a full interval |
| H8 restart | one `report running` line; no second entry, no new attempt row | a restart launched again |
| H9 abrupt | exit 130, `Stopped at once.`, the entry still running | a second press waited, or the step died |
| H10 after abrupt | a normal first round, no second entry or attempt row | the abrupt stop left something a round could not continue |

Section 7 gains: tab B's start and end lines, `rounds.log`, `T plan show` of `$H_ONE`/`$H_TWO`, H3's and H4's output.
Section 9 gains: never run `tl plan rounds` against the real tracker or with real paths; never run it under a service
manager; never run the gates in `$TL` while the rounds process runs from it; stop the rounds
process before a reset (section 8). Not covered live: a real reboot, the wake race of section 6, the zombie reaping, a
first Ctrl-C landing mid-round (it needs luck with timing; the tests cover the safe points), macOS.

## 20. Docs to update with the code

- [.4.3.1.13](../tl-8bh9.4.3.1.13/plan.md) section 5: "the trigger is decided in .4.3.1.14 (`tl plan rounds`)"; section
  15 question 5: "decided in .4.3.1.14 section 16"; section 7a: the `quiet` rule for repeated rounds; section 4: a
  regular round every 60 s bounds relaunches at `minutes` per deadline.
- [.8.7](../tl-8bh9.8.7/plan.md) lines 50-51: `tl plan rounds` joins the registered plan surface under the same exception.
- [.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md) section 0: "rounds by themselves in .4.3.1.14; pause = stop `tl plan rounds` (or
  remove the label); the dashboard remains next".
- `cli_plan.discard` step 1 and `GUIDE["no_free_slot"]` ("`tl plan rounds` fills it seconds after a slot frees; by hand,
  the next `tl plan next`").
- The live smoke (section 19) and its section 8: the `bd list --status in_progress --assignee taskloop` check against
  `tl plan list` after an abrupt stop or a crash.
- The glossary needs no change (round, rounds, interval and check are ordinary English). AGENTS.md and CLAUDE.md gain
  one mirrored sentence naming `interrupts.py`'s SIGINT handler as the only signal use (question 5, approved).

## 21. Out of scope

Other steps (implement, check, review, land); the dashboard UI; session resume (`stuck:entry_lost`); retrying a failed
step (a network loss during an agent run stays a reported failure, .13 rule); stuck detection, stopping or supervising
entries; a self-daemonizing mode, pid files, services, start at boot (owner: never); enabling bd's events journal or following
it (a later wake source of the same process if the 60 s bound is ever felt: any journal record starts a round early;
its `seq` lives in memory only and a restart re-baselines with a full round); tracker sync (`bd dolt pull`) on the
factory machine; several factories on one backlog; the section 16 follow-up's code.

## 22. Owner questions

Answered (owner, 2026-11-10):

1. **Default interval:** 60 s, as designed.
2. **Start at boot:** never. The rounds process is always started by hand in a terminal and stays there in the
   foreground; no service, no boot start. First Ctrl-C a graceful stop, a second an abrupt exit (section 7).
3. **Tracker events:** not now, as designed.
4. **Question 5 of .13:** the renewal once per reboot is a separate follow-up task (section 16).

5. **One SIGINT handler: approved (owner, 2026-11-10)** as the single exception, mirrored into CLAUDE.md and AGENTS.md,
   enforced by `.importlinter` `one-signal-owner` and the policy AST test. The question as asked:
   **May one module install a SIGINT handler?** The graceful first Ctrl-C needs it: Python's default turns Ctrl-C into
   an exception at whatever line is running, which cannot "finish the current move". CLAUDE.md says factory source has
   no "direct spawn/signal/wait escape hatch"; I read that as about controlling other processes (spawning, signalling or
   waiting on them), which this does not do: it only decides how the rounds process reacts to its own keyboard. It is one
   module, SIGINT only, installed only while `tl plan rounds` runs, rule-checked, never in tests (section 7).
   **Recommendation: allow it as that one narrow exception**, and mirror one sentence into CLAUDE.md and AGENTS.md
   ("the rounds process's SIGINT handler in `interrupts.py` is the only signal use"). Without it, a single Ctrl-C can
   only be the abrupt stop.

## 23. Decided here, open to veto

Option (c) without tracker events; the verb `tl plan rounds` (not `run`, not `loop`); a foreground command started by
hand, never detaching; graceful first Ctrl-C at the next move boundary (at most one 2 s slice when waiting), abrupt
second Ctrl-C through `KeyboardInterrupt`, exit 0 and 130; the slot-freed signal is the reservation row's removal read
every 2 s, owned by the release; the free-slot gate before any tracker read, also in `tl plan next`; publication skips
a row whose entry still runs; one rounds process per (factory.db, backlog) by a `process_lock` beside factory.db,
one-shot rounds unlocked; `rounds.log` only, identical consecutive moves written once, idle rounds silent; backoff
doubling to 300 s on whole-round or admission-stopping `unavailable`/`uncertain` only; exit 1 on refusals, never 3;
`round_seconds` in the machine config, `--every` over it, >= 5; the round choices stay flags; the environment, version
and zombie notes as runbook text.

## 24. Not verified

Read and timed, not run: nothing of `tl plan rounds` exists. The bd timings are three runs each on one machine and one
tracker; a busier tracker or a concurrent `bd` writer (embedded Dolt, the entries' heartbeats, the person's own `bd`)
may be slower, and whether concurrent embedded `bd` calls wait or fail was not checked. CPython's zombie reaping through
`subprocess._active` was read in source, not observed with a resident process. That Ctrl-C reaches in-flight `bd` and
Git children (shared process group) and that `time.sleep` resumes after a non-raising handler (PEP 475) are read, not
tried here; the systemd `KillMode` aside is its documented default. The wake race of section 6 is reasoned from the
entry's order of release, lock release and publish. `bd events tail --follow` was read from help only (journal not
enabled, not tailed). Every line estimate.

## 25. As built (2026-11-10, on ee5dde41b, uncommitted)

Built as designed in sections 5 to 15 and 17 to 20, with the review repairs below; nothing of section 16 (its own
follow-up task). No live run (Run H is owner-run, not yet run). Gates: `just check` (ruff, pyrefly 0 errors, 6
import-linter contracts kept) and `just test` (1200 passed). SLOC by the policy counter: `plan_rounds` 108, `rounds_lock`
18, `interrupts` 35, `plan_next` 220, `plan_reads` 179, `machine_config` 101, `plan_ops` 370, `plan_data` 91, `cli_plan`
379, `cli_composition` 205; tests `test_rounds` 200, `test_rounds_lock` 21, `test_interrupts` 11, `test_next` 427,
`test_plan_cli` 510, `test_config` 133, `test_slots` 201, `test_ops` 542, `test_policy` 159.

Differences from the text above:

- **The wake baseline is the union of the reserved slots read just before and just after each round**, passed to the
  pause: a slot released while the round runs (its own verify's release, an entry ending) wakes the next round at the
  first check, and a slot the round itself reserved wakes it when that step ends. The first repair read the baseline
  only before the round, which was incomplete: live Run H found that a round starting with the slot free left an empty
  baseline, the pause skipped every check, and the step's end woke nothing (H5: 91 s instead of about 2 s; it worked
  only from the second round after a start). Fixed and covered by a fake-clock test (slot free before round 1, held
  after it, released at t = 4: round 2 at t = 4.5, not 120). Either read alone stands when the other fails; with both
  failed each check retries it (the first successful read becomes the baseline; it never wakes by itself). An empty
  baseline has nothing to lose and is not read again during that pause.
- **`SlotUse(free, held)`**: `free` counts adopted slots with no reservation row of their own `(repo_id, name)`, so the
  gate is `free == 0`; `held` is the reserved **`(repo_id, slot)`** pairs, not rows with their attempt: a repeat's
  takeover rewrites the attempt and keeps the slot reserved, which must not wake. It is every backlog's reservations:
  another backlog's release wakes one round that finds nothing to do (accepted, documented).
- **A transient factory.db failure backs off**: in the rounds path an open that fails while the file exists (locked past
  the busy timeout, unreadable now) is `unavailable:store` (`cli_composition.one_round`); only an absent file stays
  `refused:database` and ends the rounds (a deliberate discard). Before the first round a failed open still refuses.
- **The quiet set is `Round.written`**: the keys of moves and of the stopped word actually in the round log (written
  now, or quiet and unchanged since an earlier round); empty when any write of the round failed, so the next round
  writes the state again, and a broken log keeps `logged` False round after round: `Log: not written` is said once
  until a write succeeds again. `plan_next.reported` is gone. A round that writes a move line always writes its
  closing line.
- **`stopped=interrupted` whenever a stop was asked**: `advance` closes with `interrupted` if `stopping()` is True at
  the end, also when the press landed during the last move.
- **The wait line** is written when the backoff delay **or its cause** changes, so the first unknown round writes
  `rounds wait seconds=<every> after=<word>` (a whole-round `unavailable:store` has no round line of its own); the
  return to the interval writes `rounds wait seconds=<every>` once. Delays as designed, up to `max(CAP, every)`.
- **The abrupt line is the operation's**: `run_rounds` catches `KeyboardInterrupt` only after `rounds started` was
  written, makes the best-effort `rounds stopped abrupt` (a write error or a further press ignored) and re-raises; the
  CLI maps it to `Ended(backlog, "abrupt")`, and `plan_ops.exit_code` maps `interrupted` 0, `abrupt` 130, any other end
  word 1. A press during setup is exit 130 with no line. The ended JSON keeps `detail`
  (`{"status": "ended", "backlog", "reason", "detail"}`); refusals before the first round keep the `{"error": ...}` shape.
- **Input checks** live in `plan_rounds.inputs`: refusals `backlog` (not `plan_next.IDENT`, or containing `/`), `label`,
  `choices`. Order before any round: inputs, the read-only database guard (no lock file beside a missing factory.db), the
  lock (`rounds_running`; `rounds_lock` when its file cannot be made), then the SIGINT handler. `--checkout` is not
  checked here: admission refuses a wrong one (`refused:checkout`, ending admission for that round), but while every slot
  is held no candidate is tried, so that feedback waits until a slot frees (help and runbook say so).
- **SIGINT disposition**: the first press puts back the previous disposition (Python's `default_int_handler` in a
  terminal), before saying the notice with an unbuffered `os.write(2, ...)`; on exit the previous disposition is
  restored. A process started with SIGINT ignored (`SIG_IGN`, e.g. a background job of a non-interactive shell) keeps it
  ignored: nothing is installed and Ctrl-C is not re-enabled (the smallest correct behaviour; that process is stopped
  as any ignoring process is).
- **A graceful stop waits for the move in flight**: a verify finishes its release and its publish push first, up to
  Git's own timeout (the same Ctrl-C also reaches the push's Git child if it shares the terminal's process group, which
  then fails it and a later round retries). Help and runbook say so.
- **`rounds_lock.holder` is not built** (no reader yet); the refusal takes the pid from the library's `LockHeldError`.
- **`.importlinter`**: `signal` cannot be a root package (a single module); as an external module the forbidden
  contract sees it. A probe `import signal` in `plan_rounds` broke the contract (then removed). `one-slot-lock-owner` is
  now `process-lock-owners`.
- **Policy rule**: in every source and test file, `signal` and `_signal` are imported only by `interrupts.py`, and only
  as a plain `import signal` (no alias, no `from`); no file makes a dynamic import (`import_module`, `__import__`); no
  file uses a name that sends or times a signal (`kill`, `killpg`, `alarm`, `setitimer`, `pthread_kill`,
  `pthread_sigmask`, `set_wakeup_fd`, `pidfd_send_signal`, `raise_signal`, `siginterrupt`, `sigwait`, `sigtimedwait`)
  under any receiver; `interrupts.py` uses only `signal`, `SIGINT`, `SIG_IGN`, `default_int_handler`, `getsignal` and
  imports no `os`.
- **Tests**: `test_next.Bench` adds one unreserved adopted slot of another repo by default (`free=True`); the gate test
  passes `free=False`. A whole-round unknown keeps the previous round's `quiet`. Behavioural tests replace the two that
  restated the code (the keys of `reported`; the count of baseline reads): a failed log write makes the next round write
  the state again, and a slot released during a round wakes the next one.

Live Run H (first run, emulated Ctrl-C by `kill -INT` to the process group): a SIGINT mid-round killed the in-flight
`bd ready` child within 50 ms and the round closed `stopped=interrupted`, exit 0; exited entries stayed zombies (`Zs`)
until the next `bd` call reaped them. Not observed: a real terminal press, a SIGINT during a claim's `bd` or a push's
Git child. The runbook's Run H now runs H7 to H9 on a third, longer step right after H5 and H6 last; H11's first wait
line is `seconds=120` at `--every 120`.

Residual: the wake race of section 6; a claim with no attempt row after an abrupt stop between the tracker's commit and
factory.db's (runbook section 8); zombies of exited entries until the next `bd` or Git call; that `time.sleep` resumes
after the handler and that Ctrl-C reaches in-flight `bd`/Git children are read, not observed; `interrupts.installed`
itself is exercised only by Run H.
