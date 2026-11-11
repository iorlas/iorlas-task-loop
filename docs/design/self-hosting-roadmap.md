# Roadmap: the factory develops itself (self-hosting)

Written 2026-11-11 against HEAD 0304f0abf (S4 built). Docs only. Goal (owner, 2026-11-11): "by the end of it we will be
able to run the factory to develop the factory itself". Everything below that is not in section 1 or in the owner
decisions list is **proposed**. Vocabulary: [glossary](../glossary.md). Order of work: section 4. The older
[2026-11-06 roadmap](roadmap.md) stays historical; this file orders the work toward self-hosting only. Task ids are the
tracker's; a block without one has no tracker entry yet (block B14).

**Owner decisions this roadmap respects (2026-11-11):**

| # | Decision |
|---|---|
| D1 | The implement agent may change any plain file in the repository. |
| D2 | The implement agent MUST be able to run the project's tests: new tasks write new tests, the only way to check they work. Bare minimum static analysis (ruff, pyrefly, import-linter) always runs. |
| D3 | The label `auto` is checked only when the scheduler ingests a new task; a task already claimed and in progress advances without a label check. |
| D4 | After an abandon, the next start begins at plan. |
| D5 | `tl step` is the CLI. |
| D6 | The factory never starts at boot: a foreground `tl step rounds` loop, Ctrl-C to stop. |
| D7 | No hung-agent detection until a real case shows the need. |
| D8 | The dashboard later shows the time since the agent's last command. |
| D9 | Already accepted earlier: runtime version fixed until restart ([operations](tl-8bh9.8/operations.md)); normal host networking for checks ([coverage](tl-8bh9/coverage.md)); lifetime-scoped keep-awake ([.4.6](tl-8bh9.4.6/plan.md)); merge plus final squash, one resumable land ([delivery](tl-8bh9.9/delivery-publication.md)); one mandatory check set, no pass cache ([candidate checks](tl-8bh9.5.1/candidate-checks.md)). |

D2 reverses the recommendation of [.16](tl-8bh9.4.3.1.16/plan.md) Q1 (tests "may not run"), and D3 removes the label
re-check that .15 Q2 and .16 sections 3.2 and 3.6 put before an advance (`not_approved` goes away). .16 needs both edits
before S5 is built.

## 1. Current state

| Area | State | Commits |
|---|---|---|
| Successor foundation: CLI, own environment, `just check` (ruff, pyrefly, import-linter), `just test` (focused pytest), isolation rules | built, gated | 256d4643b |
| `tl repo inspect`, `tl task show` (Beads, backlog scope) | built, gated | 7ef198472, c05e19df7 |
| Plan attempt: admission, slot provenance, registered entry process, launch | built, gated, live smoke | 0400c1d28, 84a7fedbb, 74c73a691, c32d2994a |
| Verification (chain, path, mode, size rules), factory commit of listed paths outside the sandbox, slot pointer checks | built, gated, live smoke | 2c81e6d03, 8f461d9d6, cdfa00b4b |
| Repeat with sanitized feedback (max 3), claim lease keep-alive, worktree onto `task/<id>` under custody lock | built, gated, live smoke | 24f74c375, 4a4ab31a9, 7a66d0dff |
| Slot release and abandon; publish `task/<id>` to origin, never forced | built, gated, live smoke | e6f567929, 2f2c3b900, a2c7a47ed |
| Scheduling: `tl step next` (one round); `tl step rounds` (foreground, Ctrl-C); deadline renewal once per reboot | built, gated, live smoke (Runs F-H) | 35bf31804, c26fb0643, 283ae2271, 5ec5fe9c9 |
| Step generalization S1-S4: generic tables (factory.db v10), step port, `tl step` replaces `tl plan` | built, gated | 43616e040, d2f41da10, cf4df5cff, 9c1cbe426, edc4e31e2, 0304f0abf |
| Implement step and step chaining (S5) | design ([.16](tl-8bh9.4.3.1.16/plan.md), proposed; under revision) | none |
| Test environment inside the agent sandbox | not built, no design | none |
| Repository profile reader (`.task-loop.json` successor) | not built; the file in the tree is baseline-only, nothing reads it | none |
| Checks step, review step, land (merge, close, sync) | not built; contracts agreed in candidate-checks and delivery-publication | none |
| Questions and holds; a failed result today leaves the task claimed with no signal | not built | none |
| Install, pin, release; session resume; dashboard; keep-awake; account routing | not built | none |
| Tracker entries for slices .4.3.1.2 to .16 | missing (only .4.3.1 and .4.3.1.1 exist, `in_progress`) | none |

Today the factory takes an `auto` task, plans it, verifies and publishes the plan, and stops. A plan result that is not
`verified` ends as a failed `done`: the slot is released, the claim kept, and nothing tells the person.

## 2. "Self-hosting ready": observable checklist

1. The person starts `tl step rounds ... --label auto` from a pinned factory version and leaves it running for hours;
   Ctrl-C stops it; a restart continues unfinished work.
2. A ready `auto` task of this repository is claimed, planned (`docs/design/<id>/plan.md`) and implemented (code and
   new tests) as commits on `task/<id>`, published to origin.
3. During implement, the agent runs `just check` and `just test` (or their parts) inside its sandbox, offline, and the
   transcript shows the results.
4. After implement, the factory runs the required checks itself on the implement commit X, outside the agent's
   control, and `tl step show` reports passed or failed per check with an output path.
5. Every way a task can stop (needs_owner, incomplete, rejected verdict, repeats exhausted, failed checks, timeout)
   ends as a held task with the reason on the task in the tracker. No task is left claimed and silent.
6. The person reads the diff and check results and lands with one command: a squash commit on origin `main` and the
   task closed in the tracker. The person's main checkout is never written by the factory.
7. Changes landed on `main`, including changes to the factory, never affect the running factory; they take effect when
   the person changes the pin and restarts.
8. `tl step list` (later the dashboard) shows each running attempt's time since the agent's last command.

## 3. Blocks, in dependency order

Size is in slices (one reviewed commit each, under the 400/80/800 caps). "Design" says whether the block needs its own
plan under `docs/design/<task-id>/` before code. "Smoke" is an owner-run live smoke on a scratch repo, tracker and
remote.

### B14. Tracker entries for built slices and for this roadmap

| | |
|---|---|
| What | File .4.3.1.2 to .4.3.1.15 as closed tasks with their commit refs; .16 and the blocks below as open tasks with dependency edges and acceptance; close or update .4.3.1 and .4.3.1.1. |
| Why | The factory takes only tracker tasks. Self-hosting starts by giving it its own well-specified tasks. |
| Depends on | nothing |
| Size | none (tracker writes only) |
| Open decisions | Q9 (permission to write the tracker) |
| Design / smoke | no / no |

### B13. Shelf follow-ups

| Item | Why for self-hosting | Needed by |
|---|---|---|
| **Pinned `git_dir`** in `git_porcelain` ([.7](tl-8bh9.4.3.1.7/plan.md) section 4(a), HIGH residual): pin `GIT_DIR`/`GIT_WORK_TREE` from the verified value, never re-read `<slot>/.git` | B2 adds a writable root outside the slot. That reopens the place `/tmp` was excluded to remove: a Git directory the agent can create outside the slot, swapped into the pointer between check and Git call. Running tests also means more background processes. | B2 |
| **Git read timeout** per call (.7 section 4(b), [.5](tl-8bh9.4.3.1.5/plan.md)) | A FIFO or a stuck file system hangs a local Git read with no bound; an unattended loop must not hang. | M4 |
| `core.sshCommand` honoured ([.12](tl-8bh9.4.3.1.12/plan.md) finding 3) | Only if the person's push key is selected by `core.sshCommand`. | when needed |
| beads-client child env per call ([.9](tl-8bh9.4.3.1.9/plan.md)) and a `ClaimClient` contract fake | Hygiene; the per-process scrub works today. | later |

Size: one shelf release plus one pin bump per item. Design: no (the APIs are written in the plans). Smoke: no.

### B1. S5: implement step kind and step chaining

| | |
|---|---|
| What | [.16](tl-8bh9.4.3.1.16/plan.md): `implement` step kind (repository-wide paths, deletions, excluded `.beads/`, `.git*` refused), `next_step`, `admit_next` (no new claim), schema v11 with `after_commit`, `prepare` refuses `branch_moved`, `Next: advance`, the round's advance phase (FIFO, before new tasks). |
| Changes from .16 required by owner decisions | D2: the input text says tests can and should be run (needs B2; the input names the commands and the scratch folder). D3: drop the label from `NextStepRequest` and the `not_approved` word; the advance still checks `in_progress` and assignee `taskloop`. D4 matches .16 Q4. |
| Why | Without it nothing writes code. |
| Depends on | S4 (built). S5a can start now. S5b's input text and smoke need B2. |
| Size | 3 slices: S5a preparation (about +15 source lines), S5b kind and hand advance (about +190 / +300 test lines), S5c round advance (about +40 / +260). |
| Open decisions | .16 Q2, Q3, Q5, Q6 (recommendations stand); Q1 and the label check are answered by D2 and D3. |
| Design / smoke | yes, .16 (revise for D2, D3) / yes (.16 section 5, plus one implement run that runs a test in the sandbox) |

### B3. Profile reader (`.task-loop.json` successor)

| | |
|---|---|
| What | One reader and validator for a minimal repository profile, hard cut, no old-key reader: `setup` (argv run to prepare a slot's environment), `checks` (ordered list of id, argv, timeout), `target` (land branch, default `main`). Tasks tl-8bh9.1.1 PROFILE-READS, tl-8bh9.1.2 PROFILE-SURFACE. |
| Why | B2 needs the setup command, B4 the required checks, B6 the target. Without a profile they become hard-coded factory knowledge of this repository. |
| Which version is read (proposed) | The target's (the slot's parked HEAD D, from Git, not the working tree). By D1 the implement agent can edit `.task-loop.json`, the `justfile` and `pyproject.toml`; a candidate profile would let it weaken its own checks (Q2). |
| Depends on | nothing; small |
| Size | 1 slice (reader, validation, `tl config show`-style print) plus the new `.task-loop.json` content |
| Open decisions | Q2 (target or candidate profile), Q8 (setup outside the sandbox) |
| Design / smoke | short design section (schema, refusals), may live in B2's plan / no |

### B2. Sandbox and environment: tests inside the agent's sandbox

**What exists today** (`attempt.CODEX_ACCESS`, `SANDBOX`): Codex `workspace-write` on the slot only;
`network_access=false`; `writable_roots=[]`; `exclude_slash_tmp=true` and `exclude_tmpdir_env_var=true` (no `/tmp`, no
`$TMPDIR`); `approval_policy=never`; `--ignore-user-config --ignore-rules`; the agent environment scrubbed of
credentials and push-barred. One `SANDBOX` value for every step; `StepKind` has no access field. Run C (owner-run probe,
[live smoke 6b](tl-8bh9.4.3.1.4/live-smoke.md)) checks that Git writes and `/tmp` writes are refused.

**Why tests fail there today:**

| Need of `just check` / `just test` | Today in the slot |
|---|---|
| An installed environment (`.venv`, the project wheel, pytest) | A fresh slot has none (`.venv` is ignored, per worktree). |
| `uv sync --reinstall-package`, `uv tool run ruff@...` / `pyrefly@...` / `import-linter` | Need the uv cache (`~/.cache/uv`, outside the writable roots) and the network for anything not cached. |
| A temp directory: 642 `tmp_path`/`basetemp` uses in `tests/` | `/tmp` and `$TMPDIR` are excluded. |
| `just`, `mise` shims on `PATH` | Unknown whether mise shims need to write their own state. |

**Proposed shape:**

1. **Prepared per-slot environment.** At preparation, before dispatch and outside the sandbox, with network, the
   factory runs the profile's `setup` (B3) in the slot at D, with `UV_CACHE_DIR` and the tool directories pointed at a
   per-slot folder. For this repository, `setup` is a new just recipe: `uv sync --frozen --no-editable` and a warm-up of
   the pinned ruff, pyrefly and import-linter. Runs once per slot and again only when `uv.lock` or the pins changed.
   It runs code of the target (D), never of the candidate.
2. **Per-attempt scratch folder** as the one writable root outside the slot (for example
   `<artifacts>/<attempt>/tmp`), with `TMPDIR` set to it; `/tmp` stays excluded. Never inside a Git directory.
3. **Offline inside**: `UV_OFFLINE=1` and the per-slot cache, writable, so `just test`'s reinstall of the project wheel
   works from the cache.
4. **Access per step kind**: one access for every agent step (plan gets the scratch folder too; harmless) unless the
   design finds a reason; no new `StepKind` field (.16 Q1 kept).
5. The input text names the commands (`just check`, `just test`, or a focused `pytest` path) and says the factory's
   checks (B4) decide, not the agent's runs.

**Unknown, to settle with a spike first (an owner-run "Run S", like Run C):**

- Whether Codex passes `TMPDIR`, `UV_*` and `PATH` to the agent's shell commands under `--ignore-user-config` (its
  default `shell_environment_policy`).
- Whether a `writable_roots` entry outside the cwd works with Landlock on this Linux and Seatbelt on macOS.
- Whether `uv sync --frozen --no-editable --reinstall-package` builds the wheel offline from a prepared cache (the build
  backend must be cached), and whether `uv tool run` of the pinned tools works offline.
- Whether mise shims and `just` run without writing outside the roots.
- Whether a long scratch path breaks Unix socket paths (108-byte limit) used by any test or by bd.
- Whether tests that spawn processes leave descendants outside the agent's process group (the release's stop proof
  does not cover them, .4.4).

| | |
|---|---|
| Why | D2. Without it the implement agent works blind and new tests are never run before checks. |
| Depends on | B3 (setup command), B13 pinned `git_dir` (recommended before a writable root outside the slot) |
| Size | spike (Run S) plus 2 slices: preparation (`setup` run and its record in factory.db) and access (scratch root, env, input words) |
| Open decisions | Q8 |
| Design / smoke | yes (own plan) / yes (Run S first, then an implement run that runs a new test) |

### B4. Checks step

| | |
|---|---|
| What | A non-agent step after implement: the factory runs the profile's required checks (B3) on exactly X, each with its timeout, output kept as evidence files, one result row per check in factory.db (check id, argv digest, profile digest, X, exit, timed out, duration). The step's verdict is passed only when every required check passed. |
| What "passed" means (proposed) | Exit 0, not timed out, launched on X with the profile read at D, and the tree still clean at X afterwards (a check that changes tracked files invalidates the candidate, candidate-checks). A failure is a result, never a pass; a missing result runs again (glossary: check, pass). No reuse across candidates. |
| How it runs | Through the shelf process API (no subprocess in factory source); with normal host networking (D9); environment per Q1. In a slot holding X (the implement slot is released; checks admits one like an advance). An interrupted block repeats after stop proof. |
| Step or verify rule | Its own step (`check` in `Next`/`rounds.log`), not a verify rule: it needs its own attempt, deadline, evidence, restart and failure route. Not a `StepKind` (no agent, answer or commit, .15 section 5); own table. |
| Failure route | Q3. Proposed: failed checks hold the task (B7) with the output path; automatic repair (back to implement with the output) later, tl-7i9k.56.1. |
| Why | Without it, "implemented" means only "committed": the person runs the checks by hand. |
| Depends on | B1, B3; B2 for the same prepared environment |
| Size | 3 slices: schema and result store; the check runner and step in `tl step` (show, list); the round phase |
| Open decisions | Q1, Q2, Q3 |
| Design / smoke | yes (own plan, tasks tl-8bh9.5, tl-8bh9.5.1, tl-8bh9.5.2) / yes |

### B5. Review step

An agent step reading the diff and check results, answering accept or changes, no commit. **Recommended optional for
self-hosting:** the person reads every diff before landing until M5; add review only when the person wants to stop
reading every diff. Depends on B4. Size about 2 slices. Design: yes (later). Not in any milestone below.

### B6. Land and close

| | |
|---|---|
| What | `tl step land TASK` (proposed name), person-run at first: requires checks passed on X; in a slot, squash X onto the current origin target; if the target moved, the new candidate runs the checks again (B4); conditional non-force push to origin `main` naming the expected old tip; then `bd close` with the land commit; records each action so a rerun does only what is missing (delivery-publication, D9). |
| Glossary | land = accepted integration, confirmed task completion and any required task sync; merge and push are its actions, not steps. Publishing `task/<id>` does not land. |
| Repository rule | CLAUDE.md: the main checkout is the person's; local Git permission does not authorize remote publication or merge. The factory never writes the main checkout; the person pulls. A factory push to origin `main` needs the owner's explicit permission (Q4). Task sync (`bd dolt push`) is a remote operation (Q5). |
| Why | Closes the loop: without it every task ends with hand merge, push and close. |
| Depends on | B4 |
| Size | 2-3 slices (land record and actions; conflict and moved-target refusals; tracker close) |
| Open decisions | Q4, Q5 |
| Design / smoke | yes (own plan, tasks tl-8bh9.9, tl-br2.8 SETTLE, tl-br2.19 ACCEPTDONE) / yes (scratch remote and tracker) |

### B7. Questions and holds

| | |
|---|---|
| What (proposed, Q6) | Every terminal non-success (needs_owner, incomplete, rejected verdict, repeats exhausted, failed checks, timeout, `branch_moved`) holds the task: the factory adds the agent's explanation (or the check output path) as a task comment, removes the label `auto`, and returns the claim (the existing abandon path). By D3 and D4, the person answers by editing the task's requirements and adding `auto` again; the next round starts it at plan. |
| Why | Today such a task stays claimed and silent forever; an unattended loop needs every stop to be visible in the tracker. |
| Not now | Structured questions with choices and dashboard answers (tl-8bh9.6.1, settled design), answer revisions, local waits. |
| Depends on | B1 (implement dispositions); B4 adds failed checks as one more reason. Needs beads-client writes for comment and label (not verified in 0.2.0: may need a shelf request). |
| Size | 2 slices (hold operation and words; the round applies it) |
| Open decisions | Q6 |
| Design / smoke | short plan / yes |

### B11. Keep-awake

Lifetime-scoped while `tl step rounds` runs (accepted, .4.6): macOS `caffeinate -i -w <pid>`, Linux `systemd-inhibit`,
through the shelf process API. Needed for M4 on a laptop. 1 slice, no design, small smoke.

### B8. Install, pin, release

| | |
|---|---|
| What (proposed, Q7) | Until M5: a dedicated runner worktree at a known commit with its own `.venv`, never synced while rounds run. At M5: one install directory per version (a venv per commit or tag), a durable owner pin in `config.toml`, `tl` resolving the version once at start; the entry process already uses the same interpreter (`sys.executable`). Release: an annotated tag on `main` by the person. No marketplace, plugin cache or canary. Task tl-8bh9.8.3 INSTALL-OWNER. |
| Why | D9: version fixed until restart. Self-hosting lands changes to the factory's own code while it runs; a reinstall under a running loop would give new entry processes new code against an old round and factory.db. |
| Depends on | nothing (the runner worktree is the interim); built after M4 |
| Size | 2 slices (install directory and pin; resolve once) |
| Open decisions | Q7; the reduced release scope in [operations](tl-8bh9.8/operations.md) stays proposed |
| Design / smoke | yes / yes |

### B10. Time since the last command (dashboard later)

`tl step list` and `show` gain the time since the agent's last command, read from the attempt's evidence (the agent
event stream) behind `EvidenceFiles`: display only, never control state (D7, D8). The web dashboard (tl-8bh9.7.x) comes
later on the same reader. 1 slice; no design for the CLI column; dashboard needs its own.

### B9. Session resume

After a reboot during an agent run the attempt is `stuck:entry_lost`; the hand step is `tl step release --abandon`,
which by D4 restarts the task at plan (`unchanged` when the plan still fits). Admitted attempts already relaunch and
renew their deadline. Resume of the same session (tl-8bh9.3.4 RESTART) is **deferred**: by D6 the loop does not run
across a reboot anyway.

### B12. Account and provider routing

One Codex login (`auth.json`) and one model pair (.15 Q4). A usage-limit failure is a failed attempt, held by B7.
**Deferred**: routing, several accounts, quota reads (tl-7i9k.16 QUOTA, narrowed).

### B15. Earlier small assessment items

| Item | Source | Disposition (proposed) |
|---|---|---|
| Protected files: the baseline gated changes to `.task-loop.json`, `mise.toml` and agent instructions | [.13 audit](tl-8bh9.13/audit.md) | Not carried as a gate. B3 reads the profile from the target; B6's land summary lists changed check-configuration files (`justfile`, `.task-loop.json`, `pyproject.toml`, `mise.toml`, import-linter contracts, `tests/rules/`) for the person. |
| Check environment shaping (credential strip, scratch HOME) | .13 audit | Decided with Q1 in B4. |
| Review verdict rewriting, stray-file quarantine | .13 audit | Not carried; review is B5, strays are repeats. |
| `tl step verify` does not check the claim | .9 known gap | Unchanged until a case appears. |
| Branch rule D for a later step (`branch_diverged`) | .15 section 5 | Adopt all slots at one base; revisit if S5's smoke hits it. |
| Claim lease between steps (`bd reclaim`) | .15, .16 section 7 | Hold via B7 on `claim_lost`. |
| `rounds_lock.holder`, entry.log `publish=` word, three "outcome" comments | .14, glossary | Small cleanup tasks, good first self-hosted tasks. |

## 4. Recommended order and milestones

```
B14 tracker ─┐
S5a ─────────┼─> B3 profile ─> B13 pinned git_dir ─> Run S ─> B2 env ─> S5b ─> S5c   = M1
             │                                                              └─> B4 checks = M2 ─> B6 land = M3
             └─> (parallel) B10 CLI column, B15 small items                     B7 holds + B11 + git timeout = M4
                                                                                B8 install/pin (+ dashboard) = M5
```

| Milestone | Blocks | The owner can | Still by hand |
|---|---|---|---|
| **M1 semi-assisted** | B14, S5 (a-c), B3, B13 pinned `git_dir`, B2 | Label an own task `auto`, run `tl step rounds` from a runner worktree, get plan and implementation (with new tests the agent ran) on `task/<id>` | Run `just check`/`just test` on `task/<id>`; read the diff; squash-merge, push, `bd close`; spot failed tasks in `tl step list` and abandon them; stop rounds before any factory upgrade |
| **M2 checks in the factory** | B4 | See per-check passed/failed on X in `tl step show` | Read the diff; land and close; handle failures |
| **M3 land and close** | B6 | Run `tl step land TASK` after reading diff and checks: squash on origin `main`, task closed | Decide each land; tracker sync if Q5 says so; failures |
| **M4 unattended loop** | B7, B11, B13 Git read timeout | Leave rounds running overnight; find held tasks with reasons in the tracker; answer by editing the task and re-adding `auto` | Land; reboot recovery (`--abandon`); upgrades |
| **M5 daily self-hosting** | B8, B10 (then the dashboard) | Run a pinned version; land factory changes and adopt them by changing the pin and restarting; see time since last command | Land decisions; pin changes; anything deferred (section 6) |

## 5. The simplest path to the first self-implemented task

Prerequisites: S5 (a-c), B3 (`setup` only), B13 pinned `git_dir`, B2. Checks and land stay with the person.

| # | Who | Step |
|---|---|---|
| 1 | person | Pick a small, self-contained task of this repository with acceptance that names a test (for example `rounds_lock.holder`); label it `auto`; dependencies closed. |
| 2 | person | Runner: `git worktree add <runner> <S5 commit>`, `uv sync --frozen --no-editable` there; machine config with slots root and count 1. |
| 3 | person | If factory.db is older than v11: finish or abandon attempts, discard it. `tl slot adopt <checkout>` from the runner. |
| 4 | person | `tl step rounds --backlog <key> --tracker-root <checkout> --checkout <checkout> --label auto --model <m> --effort <e> --minutes 60` |
| 5 | factory | Round: claim, prepare slot environment, plan, verify, publish. Next round: advance, implement (agent runs tests in its sandbox), verify, publish. `Next: done`. |
| 6 | person | Ctrl-C. Fetch `task/<id>`, check it out in a separate worktree, run `just check` and `just test`, read the diff. |
| 7 | person | Land: `git merge --squash` into `main` in their checkout, commit, push; `bd close <id>`; optional `bd dolt push`. |
| 8 | person | On failure: read `tl step show`, `tl step release --abandon`, edit the task, label again. |

The runner is not updated by step 7; the landed change takes effect only after the person re-creates the runner (D9).

## 6. Risks and what is deliberately deferred

| Risk | Mitigation (proposed) |
|---|---|
| Agent-written code runs on the host: B4 runs the candidate's tests outside the agent's sandbox, before any person reads them; B2's `setup` could run candidate code if it ran on X | `setup` runs only target code (D). Checks: Q1 (sandboxed or scrubbed environment). The person reads the diff before land until review exists. |
| The agent weakens its own checks (D1: it may edit `justfile`, profile, `pyproject.toml`, import-linter contracts, `tests/rules/`) | Profile and check commands read from the target (Q2); the land summary lists changed check-configuration files; no automatic land. |
| Running tests in the sandbox widens it: a writable scratch root outside the slot, more background processes | Pinned `git_dir` first; pointer checks unchanged; scratch never in a Git directory; worker-gone gate before every Git write. |
| Runaway agents and cost | Deadline per attempt (`--minutes`); at most 3 repeats; no automatic retry or repair; failures hold (B7); D3 means removing `auto` does not stop a task in progress: `tl step release --abandon` does. |
| The factory edits itself while running | Runner worktree (later pinned install) separate from slots; the entry uses the runner's interpreter; never sync or reinstall the runner while rounds run; upgrade = stop, finish or abandon, discard factory.db if the schema changed, switch, start (D9). |
| Schema discards (v11 S5, then checks, land, holds) | Finish or abandon in-flight attempts before each; planned tasks restart at plan and reuse their plan (D4). Batch schema changes where slices allow. |
| Claim lease lapses between steps | Hold on `claim_lost` (B7). |
| Unobserved platforms | macOS Seatbelt, codex versions other than 0.167.0: Run S on each machine used. |

**Deferred deliberately:** review step (B5); automatic land; PR mode and the merge queue (held); structured questions
with choices and dashboard answering (tl-8bh9.6.1); session resume (B9); hung-agent detection (D7); account routing
(B12); per-step model, effort or minutes; automatic retry and repair (tl-7i9k.56.1); start at boot or a service (D6);
multi-machine tracker sync; release publication beyond a tag; pass reuse or a check cache; Windows.

## 7. Owner questions

1. **Where do the factory's checks run?** They execute agent-written code. Options: inside a sandbox like the agent's
   (no network, if `codex sandbox` or an equivalent can wrap a command; unverified), or on the host with host
   networking (accepted 2026-11-09) and the agent's credential scrub and push bar. **Recommendation: host, with the
   agent's scrubbed environment and push bar, no scratch HOME; revisit if a sandbox wrapper proves simple in Run S.**
2. **Which profile sets the required checks: the target's or the candidate's?** The glossary says candidate; with D1
   the agent could then remove its own checks. **Recommendation: the target's (D) for checks and setup; a candidate
   that changes check configuration is listed at land for the person.**
3. **When required checks fail, hold or repair automatically?** **Recommendation: hold the task with the output path
   (B7) first; add at most one or two automatic repair rounds after smokes show how often it would help.**
4. **Who pushes to origin `main` at M3?** **Recommendation: the factory, but only when the person runs
   `tl step land TASK`; a direct squash push with the expected old tip, no PR; no automatic land before review exists.**
5. **Does land sync the tracker (`bd dolt push`)?** **Recommendation: no; land closes the task locally, sync stays the
   person's until a second machine is used.**
6. **How is a task held?** **Recommendation: comment the reason on the task, remove `auto`, return the claim; the
   person answers by editing the task and adding `auto` again, and the task restarts at plan.**
7. **How is the factory installed until M5?** **Recommendation: a runner worktree at a chosen commit, never synced
   while running; per-version install directories with a pin in `config.toml` at M5.**
8. **May the factory run the repository's own `setup` command outside the sandbox, with network, to prepare slots?**
   It runs code from `main`, never from the task branch. **Recommendation: yes; this is what makes D2 possible.**
   Cost: about one `just install` per slot and per lock or pin change.
9. **May the tracker be updated now (B14): closed entries for built slices, open tasks for these blocks?**
   **Recommendation: yes, so the factory has its own tasks to take at M1.**
