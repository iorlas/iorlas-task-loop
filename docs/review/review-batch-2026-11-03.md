# Review batch 2026-11-03: CLAUDEPOFF, PERMCAP, DB03, RELHYG

Read-only review of the single commit each branch has on origin/main (`git -C ~/Workspaces/wt/NAME diff origin/main`, plus the real
files). Nothing was run: no tests, no gate. "Unverified" marks anything that would need a run or another repo to confirm.
Specs: `bd show` of the named beads; delegate facts from the installed delegate 0.55.0 `contract.json`.

| Branch | Verdict |
|---|---|
| CLAUDEPOFF (tl-7i9k.3) | FIX FIRST |
| PERMCAP (tl-7i9k.26 + tl-7i9k.1) | FIX FIRST (close to REJECT as written: one test is red on its face, and two regressions park beads with no way to wake them) |
| DB03 (tl-zej9.3) | FIX FIRST (small) |
| RELHYG (tl-7i9k.14 + tl-7i9k.23) | FIX FIRST |

Cross-branch: CLAUDEPOFF and PERMCAP both rewrite `domain/lanes/pauses.py` `TABLE` and will conflict. PERMCAP's new rules
(`test_every_reason_has_exactly_one_policy`, the reason scanner) need `writer_unsandboxed` added to `Reason` and to `TABLE` as
`("engine", WRITER_UNSANDBOXED)`. CLAUDEPOFF's `writer_policy.families` must also set `e.pause_producer = "engine"`. Whichever
branch goes second has to be rebased by hand. Do not land both blind.

---

## CLAUDEPOFF: claude -p is not a writer lane

Acceptance: "delegate refuses role=writer on claude -p; the devbox quota-out fallback does not pick it; claude -p workers do not
load task-loop hooks".

What it does: every worker call now carries `--only-family`, which defaults to `openai, xai, deepseek, zai`. On Linux, `claude` is
filtered out even of explicit pins. On macOS, `claude` stays only if `engine.writer_family` lists it. A filter that leaves nothing
raises a typed `writer_unsandboxed` needs_owner pause before delegate runs. `hooks/hook.py` exits 0 for session-start, precompact
and pretool when `TASK_LOOP_WORKER=1` or `DELEGATE_DEPTH` is nonzero.

### Bugs / risks
1. **Weakened check: the pkill/killall PreToolUse guard is turned off for every delegated worker** (`hooks/hook.py:18`, `"pretool"`
   in the skip list). The only rule in `hook/rules.py` refuses `pkill`/`killall`, which kill other sessions' processes. Workers
   (claude -p readers, and Mac writers) are exactly the processes most likely to run that. The pretool hook is plain `python3` with
   no deps and takes well under a second, so the "do not load hooks" concern (session indexing, the shim, handoff injection) does
   not cover it. Fix: skip session-start and precompact only, and keep pretool. If the owner really wants pretool off too, it is a
   behaviour change to announce.
2. **The unpinned engine-only path may now stop where it used to route** (unverified, check before release). Since
   `worker_request.py:37`, unpinned writes carry `--only-family`. `engine_only_advisory` is still computed from the user's pin only
   (`worker_request.py:39`: `bool(only_family and recipes)` with the pre-filter list), so it is False for unpinned calls. Delegate's
   contract says `engine_only_unenforced` applies "including with --only-family". If `claude` was the family whose harness could deny
   engine-only recipes, every unpinned write with engine-only recipes now stops `engine_only_unenforced` (needs_owner) instead of
   being placed. Check which non-claude harnesses can deny. If none can, compute the advisory from the effective list, or say so.
3. **The hard-coded `DEFAULT_FAMILIES` (`writer_policy.py:15`) silently narrows routing.** A family delegate adds later never
   writes unpinned until someone edits this tuple. The names do match delegate 0.55.0 today (claude, openai, xai, deepseek, zai).
   Acceptable as a stopgap; leave a comment or a doctor line.
4. **The worker-call identity changes for unpinned writes.** `worker_identity.prepare_call` digests `sorted(r.only_family)`, which
   goes from `[]` to the four families. An unpinned write in flight across the upgrade (a reexec at a step boundary) will not match
   its old semantics digest. Expect a relaunch rather than a reattach. Unverified how recovery treats the mismatch; announce it.
5. **`families()` has side effects inside a request builder** (`writer_policy.py:26-35`: it sets `pause_reason`, steps and outcome,
   then raises). Anything that builds a request only to compare identities (recovery) will pause the run. This works for the
   tested launch path; it is a trap later.
6. **The needs_owner pause has no park on origin/main** (`parks.paused` returns None for non-transient reasons). What stops the loop
   from re-taking a `writer_unsandboxed` bead at once, given the worker role is "usable"? Unverified; the existing
   `engine_only_unenforced` path presumably relies on the same mechanism. Each retake re-runs the engine up to the refusal, but makes
   no model call.

### Spec gaps
- "delegate refuses role=writer on claude -p": not done. The refusal is on the task-loop side only. A direct
  `route.py run --role worker` outside task-loop still writes with claude -p. That may be the right cut under the "only the
  contract is shared" rule, but the acceptance line names delegate, so either a delegate bead is filed or the acceptance is amended.
- "claude -p workers do not load task-loop hooks": they still load. Claude spawns `uv run --script hook.py session-start` (uv
  resolves the env), and the script exits early. That is fine in practice; it is not "do not load".

### Behaviour changes to announce
- On Linux, `claude` is never a writer, even when pinned. A Linux profile pinned to `["claude"]` pauses every write
  (`writer_unsandboxed`).
- Unpinned writes now go out with `--only-family openai,xai,deepseek,zai`. When those are all quota-out, the write waits; it no
  longer falls back to claude.
- Worker sessions are no longer indexed for the dashboard (session-start skipped), and the pkill guard is off for them (bug 1).

### Tests
- `tests/run/test_writer_safety.py` blanks every inherited `EngineTest` test with `setattr(..., None)` (lines 93-95). That works,
  but it is a smell; use a mixin.
- `test_quota_out_keeps_the_safe_family_filter` only asserts that `claude` is absent from the argv. It cannot catch the real
  fallback (delegate picking claude), because delegate is faked. It pins the argv, which is the right observable here.
- No test covers bug 2 (an unpinned write with engine-only recipes).

**Verdict: FIX FIRST.** (1) Restore pretool for workers, or get explicit owner sign-off. (2) Settle the advisory/engine-only
question. (3) Agree with the owner whether the "delegate refuses" acceptance needs a delegate-side bead.

---

## PERMCAP: one permanence per reason, transient caps, ValueError parks, tracebacks

Acceptance (.26): "no_lane and crash follow contract.json; a test fails when a pauses.TABLE key differs from the contract;
Unknown(raw) policy; pause keys by (producer, reason)". Acceptance (.1): "a transient pause repeats at most N times then parks; a
ValueError from land parks; every catch-all log row has a traceback; retry history and settle errors are logged, not suppressed".

The table work is the right shape: `(producer, Reason)` keys, `Unknown(raw)`, legacy counter migration (`history()` takes the max),
no_lane and crash set to needs_owner as in contract.json (verified against delegate 0.55.0), and the network reasons uncapped.
Three problems make it unshippable as is.

### Bugs
1. **A test that cannot pass** (`tests/loop/test_park_pick.py:66-68`). The input was changed to `reason="busy"`, but the assertion
   still expects `("no_lane", "transient", 160)`. `busy` has base 30 s, so with `draw=0.5` the park is `("busy", "transient", 130)`.
   The three tests after it (`:77`, `:93`, `:101`) also use `busy` while keeping 159/160 as the "not yet due" and "due" times. At
   159 a `busy` park (due 130) is already due, so `test_take_path_cannot_claim_early...` asserts the wrong thing. The branch cannot
   have been green. Unverified only in the sense that I did not run it, but the arithmetic is unambiguous.
2. **Owner parks that nothing can wake** (`app/asks/parks.py:53`). The `permanence != "transient"` guard was removed, so every
   needs_owner pause now writes a Park with `permanence="needs_owner", retry_at=0`. `closer.ask_pause` (`closer.py:168`) asks only
   when a capped reason ran out. Immediate owner reasons (`no_lane`, `crash`, `logged_out`, `credit_exhausted`, `secrets`, `setup`,
   `engine_only_unenforced`, any Unknown) get **no ask**. `park.verdict` (`domain/beads/park.py:37`) then reports "answer the owner
   ask" and keeps the bead parked until an ask is answered (none exists), the text changes, or `--fresh`.
   Input: a lane logs out and the owner logs back in. Output: the bead stays parked forever. Before this branch the loop re-took it
   once the role was usable again (pause_role/pause_lane).
   Input: `no_lane` (now needs_owner per contract, and the normal devbox "everything quota-out" stop). Output: a silent dead-end park
   on every bead that hit it overnight.
   The test that pinned the old behaviour was rewritten to pin this one (`test_pause_compatibility.py`
   `test_owner_and_unknown_reasons_create_owner_parks_without_asks`, and `test_pause_retry.py`
   `test_owner_pause_has_a_durable_owner_wake_without_a_timer_or_ask`). Those tests pin the wrong thing. Fix: either raise one ask
   for an immediate owner park, or give these reasons a wake that is not an ask (lane usable again, owner re-login), or keep not
   parking them as before.
3. **Engine-synthesised `no_answer` is misattributed to delegate and becomes needs_owner.** `adapters/delegate.py:205,212`
   synthesises `no_answer` stops ("route.py could not run", "no answer object"). They reach `lane_acts.py:162`, which sets
   `pause_producer = "delegate"` whenever `pause_reason` is set. `("delegate", "no_answer")` is not in `TABLE` (only
   `("engine", NO_ANSWER)` is, `pauses.py:44`), so `rule()` falls through to needs_owner. A transient route.py spawn failure
   therefore becomes an immediate dead-end park (see bug 2). The same will happen to CLAUDEPOFF's `writer_unsandboxed`. Fix: carry
   the producer on the stop itself (synth stops are the engine's), not inferred from "a reason is set".
4. **ValueError at land now reports a deterministic refusal as an engine crash.** `gate.py:135` raises
   `ValueError("land refused: gate is no longer green for this tree and base; run --stage gate")`, and the push_judge raises
   ValueErrors too. These now go through `parked_crash` (`stages.py:249`, `run_once.py:340`), which yields ENGINE_CRASH. The
   fingerprint rule then escalates on the second identical crash, and the ask says "The engine keeps crashing; how should it go
   on?" for what is a gate-staleness refusal. The acceptance asked for "parks", so this is per spec, but the wording misleads the
   owner. Also `stages.py:252` (`"land refused: no land was recorded"`) is raised *after* the new try and still goes to FAULT_ENGINE
   through the catch-all, so only part of the land path parks.
5. **Caps on FAULT_* rows are dead** (`pauses.py:60` onward: `FAULT_INFRA`, `FAULT_CRASHED`, `FAULT_STALE_BASE` set to 3).
   `parks.paused` returns None for any kind not in `PAUSES` (PAUSE_* and ENGINE_CRASH only), so these counters are never charged.
   That is harmless, but `test_every_transient_policy_is_capped_except_network` claims coverage it does not give.
6. **`storm.recent_closes` now raises on PermissionError** and the like. The only caller (`closer_decide.py:58`) catches OSError
   and warns, so this is fine today. Any new caller inherits a raise.

### Behaviour changes to announce
- `no_lane` and `crash` from delegate: transient goes to owner (with bug 2: a permanent silent park).
- Every other transient reason (`busy`, `rate_limited`, `same_family`, `only_family_unready`, `timeout`, `hung`, ...) asks the owner
  on the 4th pause of a bead. Counters live in the Park across runs and are cleared only when the bead finishes. On a busy devbox,
  `busy` and `same_family` are normal capacity waits; three of them per bead before an ask will produce many asks per night. Decide
  whether capacity waits (busy, same_family, only_family_unready, rate_limited with a predicted unlock) belong under the cap.
- Park `attempts` keys change from `reason` to `producer:reason`. Old records are read (max-merged), but a downgrade will not
  understand the new keys.
- A ValueError at land or close goes from FAULT_ENGINE to ENGINE_CRASH (retried, then ask).

### What is right
- Traceback logging in every catch-all (`artifacts`, `closer_branch`, `closer_decide`, `records.settle`, `reflect`, `reload`,
  `run_once`) is as asked, and `test_failure_logging.py` covers it.
- `test_all_recorded_delegate_contract_reasons_have_a_policy` now compares permanence, not only key presence. That meets ".26: a
  test fails when a key differs from the contract". It reads the fixture copy of contract.json, not the installed one; fine.

**Verdict: FIX FIRST.** (1) Fix the red park_pick tests. (2) Give immediate owner parks a wake: an ask, or the old no-park
behaviour. (3) Carry the producer on synthesised stops. (4) Reword the crash ask for land refusals, or keep gate refusals as their
own kind. Then announce the cap change.

---

## DB03: contracts/factorydb.py

Acceptance: "open returns None (the caller falls back) when WAL does not take, user_version differs or quick_check fails; a rule
test says every table in the 2. mapping has one owner".

The DDL matches durable-factory.md section 2 (lines 1033-1088) and Part A (177-189) column for column. Pragmas: WAL, NORMAL,
busy_timeout 5000, foreign_keys. Version, quick_check and non-WAL all fall back to None, and each has a test. The read-only URI is
correct. There is a CAS helper. Tests are decent.

### Bugs
1. **Concurrent first open: the second process gets None** (`factorydb.py:133-140`). The emptiness check runs outside the write
   transaction. Two processes opening a fresh `factory.db` both see `user_version=0` and an empty schema. One wins `BEGIN
   IMMEDIATE`; the other waits on the busy timeout, then runs `CREATE TABLE family` → "table family already exists" → OperationalError
   → None. Result: one process on the DB and one on files. Once a family's authority is `db`, that is split-brain. Fix: re-read
   `user_version` inside the IMMEDIATE transaction (execute statements one by one instead of executescript, or use `CREATE ... IF NOT
   EXISTS`), and add a two-connection test.
2. **The macOS network-filesystem check is a no-op** (`factorydb.py:124`). `os.statvfs` results have no `f_fstypename` (fields:
   bsize, frsize, blocks, bfree, bavail, files, ffree, favail, flag, namemax, fsid), so `getattr(..., "")` always gives "" and an
   SMB/NFS home on a Mac is accepted. Use `statfs` through ctypes, or `mount`/`df -T`, or drop the claim.
3. **Mount detection fails open** (`factorydb.py:125`, pinned by `test_mount_detection_failure_is_harmless`). An unreadable
   `/proc/mounts` counts as safe. That conflicts with "None on any problem"; a conservative open would fall back. Minor, but the
   test pins the permissive choice.

### Spec gaps
- **"Every table in the 2. mapping has one owner" is not tested as written.** `test_owners_cover_exactly_the_created_tables` checks
  only that the keys equal the created tables and that the values come from an allowed set that includes `"any:cas"`. `"any:cas"`
  for `lease` and `event` (`factorydb.py:84-85`) is exactly "no single owner". The design (rule 3) assigns owners per row kind:
  `event(src='engine')` to the engine, `event(src='loop'|'exit')` to the loop, indexed rows to the indexer, `lease(kind='loop')` to
  the loop, and reconcile writes only `attempt.end_kind='lost'`. Encode that per (table, discriminator) or amend the acceptance.
  Also, `event` has no `rev` column and `lease` has no `rev` either, so `cas_update` cannot do the "CAS on the lease" rule 3 needs
  for reconcile. "any:cas" is promising a mechanism the helper does not provide.
- `"ask": "owner"` (`:88`) is wrong for today's code. The engine creates asks (`ask_flow.raise_ask`) and the owner answers them.
  `"wait": "loop"` (`:92`) follows the design, but today the engine's closer writes parks (which `wait` replaces). Note it for DB-04+.

### Other
- `PRAGMA quick_check` on every open is O(database). The design opens one read-only connection per dashboard request. Once the DB
  holds months of events, this adds up. It is per spec; consider a full check once per process, or `quick_check(N)`.
- `cas_update` accepts any table in OWNERS. On a table with no `rev` column it raises OperationalError, not the documented
  ValueError. It also does not assert `con.in_transaction`, although the docstring requires one.

No behaviour change (nothing imports it yet).

**Verdict: FIX FIRST** (small): bug 1, plus an owner rule that does not hide behind "any:cas". Fix bug 2 or drop the macOS branch.

---

## RELHYG: release train, ring, suite once

Acceptance (.14 TRAIN): "dev/release.py refuses within 2 h of the last release without --urgent "why"; ring stage recorded; Mac
standing pin moves only after devbox-ok; tl pin at Night start". Acceptance (.23 SUITEONCE): "the cache key is the pre-bump tree
content; the release does not rerun the suite inside the land lock; uv prewarm then offline spawns".

### The "extras": most of them are the spec
The brief listed release rings, the Mac pin restriction, `--devbox-ok`, the Night pin instructions, verification outside the land
lock and prewarmed offline workers as extras. **All of these are in the two acceptance lines above** (review-ledger R9-16 and
R9-26). They are not scope creep. The real extras are:
- **Deleting `.github/workflows/test.yml`: scope creep.** Neither acceptance line mentions CI. It belongs to R9-24 / M-295 "gate on
  it or delete", which the ledger routes to DQ-16, an owner decision. It also removes the only Linux run for releases made on the
  Mac: the container suite falls back to the host when no Docker answers. Split it out, or get the DQ-16 answer recorded.
- **Three push attempts instead of two:** justified. The suite now runs outside the lock, so the base can move between attempts;
  the cap is what keeps the loop bounded. Fine.
- **`UV_OFFLINE` and `UV_CACHE_DIR` added to the engine's child-env allowlist** (`adapters/childenv.py:39-40`): a mild leak. It is
  needed so nested spawns in the suite stay offline, but it changes what every production engine child inherits. Fine if the owner
  never sets `UV_OFFLINE=1` in a shell.

### Does it weaken the release's safety?
- **The tested tree is no longer exactly the pushed tree.** `bump_and_commit` (`flow.py:54`) verifies the pre-bump HEAD, then commits
  `plugin.json` and `MANIFEST.sha256`. The pushed tree is the tested tree plus those two generated files. The e2e test was changed
  to say so: `test_release.py:373` pops `PLUGIN` and `manifest.NAME` before comparing. The spec explicitly sets the key to the
  pre-bump content, so this is authorized, but it is a weakening: nothing tests the shipped `plugin.json` (the version write) or the
  shipped manifest. The residual risk is small; a cheap post-bump check (parse plugin.json, `manifest.verify(where) == []`) before
  the push would close it with no suite cost.
- **Every changed pre-bump tree still gets its own suite.** On a moved base, `push.py:28-52` drops the bump, rebases, then `bump()`
  runs `suite.verify` on the new tree outside the lock, and the push happens only when `origin/main == base` under the lock.
  `flow.py:55` aborts if HEAD moved during the suite. Correct.
- **New failure mode:** a factory that lands during each suite run can now make a release fail ("lost the race three times"). Before,
  that could not happen once the lock was held. Announce it.

### Bugs
1. **The Mac pin cannot move for releases made on the devbox** (`pins.py:49`, `train.py:41,55`). Ring records live in the releasing
   machine's config dir (`<config>/release/rings/<v>.json`, written by `shipped`). `mac_pin_refusal` reads the *Mac's* config dir,
   and `--devbox-ok` refuses unless that same dir holds the ring record ("no release ring recorded"). Releases are cut from the
   devbox (this checkout, this review). Result: on the Mac, `tl pin <devbox-released version>` is always refused, and no supported
   command fixes it. The ring has to live somewhere both machines read (a tag or note on origin, the marketplace repo, or bd).
2. **Mac rollback is blocked.** Any `task_loop != old.task_loop` on darwin needs a devbox-ok record. Every version released before
   this branch has none, so `tl pin <previous good version>` is refused in an emergency. The SKILL's Night instruction ("run `tl pin
   VERSION` at Night start") will be refused on the Mac as well. Exempt versions older than the current pin, or the last known-good
   version.
3. **The 2-hour train is per machine and per URL spelling, not per origin** (`train.py:26`, state keyed by the local config dir
   and `clone_dir(url)`). A Mac release at 10:00 and a devbox release at 10:30 both pass, and so does the same repo under an ssh and
   an https URL. Take "last release" from origin: the newest `v*` tag or `<version>:` commit time.
4. **A train refusal is recorded as a failed release.** `require_slot` raises Abort. `main()` then writes `releases/last.json`
   ok=false, "nothing released: last release was less than 2 hours ago", and comments on `--bead`. Every early release attempt from
   an orchestrator spams the bead and flips the dashboard's release status to red. Refuse before `record`, or record a typed "held by
   train" result.
5. **The `--urgent` reason is not auditable**: it lives only in `<hash>.train.json`, which the next release overwrites, and in the
   ring file. Put it in the release commit message or the bead comment.
6. **The uv cache sits in the live config dir** (`suite.py:113,209`: `config_dir(...)/uv-cache`), and offline suite workers write
   to it. That runs against R9-25 / M-133 (tests must not write the live config dir) and puts gigabytes under `~/.config`. Use
   `~/.cache/task-loop/uv` or the default uv cache.
7. **Offline workers break on a dependency bump** (unverified). `prewarm` warms only the three tool scripts and the dev group of
   `tool_root`. A test that spawns `uv run --script` on any other script or fixture with different PEP 723 deps fails with
   `UV_OFFLINE=1`. So does a release whose tree bumps a pin, if `tool_root` is not the tree under test. Confirm that `tool_root` is
   the clone in the release path, and that no test fixture declares extra deps.
8. If `train.shipped` (`flow.py:117`) raises an OSError after the push, the release stops between push and tag/close/install, with a
   non-Abort traceback. Wrap it, or move it after install. Low probability.

### Behaviour changes to announce (all release behaviour)
- The second release within 2 h is refused without `--urgent "why"`. The task-loop's release step and every orchestrating session
  that releases per bead will fail and comment on the bead (bug 4) until they batch. On 2026-10-30 there were 69 releases.
- The Mac `tl pin` is gated on devbox-ok (and, with bug 1, is effectively frozen).
- The suite runs on pre-bump content; plugin.json and the manifest are not under test.
- The suite runs outside the land lock, and the release can fail after 3 lost races.
- No CI.

**Verdict: FIX FIRST.** (1) Put the ring and train state where both machines read them (bugs 1 and 3). (2) Allow rollback (bug
2). (3) Do not record a train refusal as a failed release (bug 4). (4) Move the uv cache out of `~/.config` (bug 6). (5) Split out
the CI deletion or get DQ-16 decided. (6) Add a post-bump sanity check of plugin.json and the manifest before the push.
