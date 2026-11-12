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
| D10 | The factory's checks run on the host, before any review, with the agent's scrubbed environment and push bar. The owner knowingly accepts that agent-written code runs before anyone reads it: "it is the cheapest review: automatic checks". (Section 7.) |
| D11 | Required checks and setup commands follow GitHub's model: "copy GitHub security and configuration model; best developer experience for AI and humans". Its reading for the factory is in section 7; one part of that reading is an inference awaiting confirmation (O1). |
| D12 | The factory prepares the slot before the agent starts by running the repository's own setup command(s), named in `.task-loop.json`: "that is the crucial part of slot setup, the reason we need slots" (example: Unity with assets pre-downloaded, Unity and its license pre-installed). Outside the sandbox, with network, from the same ref as the checks. |
| D13 | Tracker entries for this roadmap (B14): "yes, file them". |
| D14 | Owner, 2026-11-11, after Run S: the factory does not care about developer tooling (it will be installed as a pip package). All its temporary and slot files live in one hidden per-user folder (default `~/.local/share/task-loop`, the platform equivalent elsewhere), never in a workspace. `mise` trust of that folder is a machine prerequisite the person meets once; the factory neither moves its folders nor launches real binaries to get around shims. What a task-changed `mise.toml` needs is the repository's `setup` command (D12). ([Run S](tl-8bh9.4.3.1.16/run-s-findings.md)) |

D2 reverses the recommendation of [.16](tl-8bh9.4.3.1.16/plan.md) Q1 (tests "may not run"), and D3 removes the label
re-check that .15 Q2 and .16 sections 3.2 and 3.6 put before an advance (`not_approved` goes away). .16 needs both edits
before S5 is built. D12 replaces the earlier proposal that setup and checks run only `main`'s (the target's) code: .16
section 2.9 and its decision 8.7 now run `setup` from the task branch.

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
| Implement step and step chaining (S5) | design ([.16](tl-8bh9.4.3.1.16/plan.md)); S5a, S5b (implement kind, hand advance, factory.db v11), S5c (round advance) built, gated; live smoke not run | f5ee65990, 872e6d2c9, da4245d9c; S5c: .16 section 14 |
| Test environment inside the agent sandbox (B2, [S5e](tl-8bh9.4.3.1.16.2/plan.md)) | S5e-0 pins, S5e-1 setup and S5e-2 access built, gated (Linux only); live smoke not run ([checklist and M1 runbook](tl-8bh9.4.3.1.16.2/live-smoke.md)) | 06b656747, bbbb0c775, 5cfcaa2fb; S5e-2: plan section 18 |
| Repository profile reader (`.task-loop.json`, B3) | built, gated; `tl profile show` | 85c9e68fc, 2bb02d106 |
| Checks step (B4, [tl-8bh9.14.6](tl-8bh9.14.6/plan.md)): factory.db v12, the block, the checks entry and release, admission and `tl step`, the round's routing | S6a-S6e built, gated; M2 live smoke not run ([M2 runbook](tl-8bh9.14.6/live-smoke.md)) | 3ce982650, 89a4a0608, f28337f41, a7dc16784, eba237919 (each with its review repairs) |
| Land and close (B6, [tl-8bh9.14.8](tl-8bh9.14.8/plan.md)): factory.db v13, `tl step land TASK` (squash onto origin `main`, validated when its tree changed, pushed never forced, task closed locally), `Next: land`/`landed`, the abandon going candidate first | L0-L5 built, gated; M3 live smoke not run ([M3 runbook](tl-8bh9.14.8/live-smoke.md)); `origin` trusted as configured, no push-URL guard (owner decision 2026-11-12, plan section 29.3) | L0-L5 commits with their review repairs (plan sections 25-29) |
| Review step | not built; contract agreed in candidate-checks | none |
| Questions and holds; a failed result today leaves the task claimed with no signal | not built | none |
| Install, pin, release (B8, [tl-8bh9.8.3](tl-8bh9.8.3/plan.md)): `tl install`, `tl pin`/`--clear`, `tl` resolving the pin once at start (one exec), `tl version`, the `rounds install` line | I1-I3 built, gated; M5 B8 live smoke passed on Linux 2026-11-12, macOS step not run ([M5 runbook](tl-8bh9.8.3/live-smoke.md), [findings](tl-8bh9.8.3/m5-smoke-findings.md): installs are built by the `uv` the installs root resolves, here not the pinned one); Q9 (baseline `devbox-ok`, macOS pin policy) open, blocking the first release | bb830cfa7, 054662704, I3 (plan section 21) |
| Session resume; dashboard; account routing | not built | none |
| Keep-awake while rounds run (B11) | K1 built, gated; live smoke not run (M4 step 6) | tl-8bh9.14.9 section 27 |
| Tracker entries for the roadmap (B14) | filed (D13): epic tl-8bh9.14 with 25 children (blocks B3 to B15 and audits; tl-8bh9.14.1 and .14.2 closed), S5 slices under tl-8bh9.4.3.1.16; stale-entry hygiene remains open (tl-8bh9.14.15) | none |

Today a `tl step rounds` loop takes an `auto` task, plans it, verifies and publishes the plan, then advances it in a
later round (S5c: no second claim, no label check; claimed work before new tasks) to implement, whose entry runs the
profile's `setup` and then an agent that may write three folders beside the slots, offline, and is told to run the
profile's checks (S5e); the implement commit is verified and published on the same `task/<id>`, `Next: done`. With S5c
every block of M1 is built (B14 filed, B3, B13 pinned `git_dir`, B2, S5a-c): **M1 is reached once the owner-run live smoke
([M1 end to end](tl-8bh9.4.3.1.16.2/live-smoke.md)) passes**. A result that is not `verified` ends as a failed `done`:
the slot is released, the claim kept, and nothing tells the person.

Since S6e the loop goes on: a done implement attempt advances (claimed work first) to the **check step**, which runs
every check of the profile at X on the host in a free slot (reset to X, `setup` at X) and concludes `passed` only when
every check `main` requires passed (`tl step show`: one `Check:` line per check, `Next: done`). A failed checks attempt
is a visible failed `done` (`check report failed:<reason>` once in `rounds.log`, the claim kept, never re-run by a
round; `tl step start` re-runs it). **M2 is reached once the owner-run [M2 live smoke](tl-8bh9.14.6/live-smoke.md)
passes.**

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
| Open decisions | none (D13) |
| Design / smoke | no / no |

### B13. Shelf follow-ups

| Item | Why for self-hosting | Needed by |
|---|---|---|
| **Pinned `git_dir`** in `git_porcelain` ([.7](tl-8bh9.4.3.1.7/plan.md) section 4(a), HIGH residual): pin `GIT_DIR`/`GIT_WORK_TREE` from the verified value, never re-read `<slot>/.git`. **Closed** (tl-8bh9.14.2): git-porcelain 0.14.0 (`git-porcelain-v0.14.0`, `RealRepo(pins=...)`), pinned here. Every Git view of a slot opens pinned to the G its full check verified (`observe_slot`: pointer layout, then the common directory bound to this repository): the status read of dispatch, verify, commit and `plan show`; the free-slot observation and `tl slot adopt`'s status read; prepare's take and staged read; the commit's refusal, stage, record, foreign check and clean listing; release's listing and park; a repeat's staged read. Only the person's checkout opens unpinned. The test fake fails any unpinned slot open | B2 adds a writable root outside the slot. That reopens the place `/tmp` was excluded to remove: a Git directory the agent can create outside the slot, swapped into the pointer between check and Git call. Running tests also means more background processes. | B2 |
| **Git read timeout** per call (.7 section 4(b), [.5](tl-8bh9.4.3.1.5/plan.md)) | A FIFO or a stuck file system hangs a local Git read with no bound; an unattended loop must not hang. | M4 |
| `core.sshCommand` honoured ([.12](tl-8bh9.4.3.1.12/plan.md) finding 3) | Only if the person's push key is selected by `core.sshCommand`. | when needed |
| beads-client child env per call ([.9](tl-8bh9.4.3.1.9/plan.md)) and a `ClaimClient` contract fake | Hygiene; the per-process scrub works today. | later |

Size: one shelf release plus one pin bump per item. Design: no (the APIs are written in the plans). Smoke: no.

### B1. S5: implement step kind and step chaining

| | |
|---|---|
| What | [.16](tl-8bh9.4.3.1.16/plan.md): `implement` step kind (repository-wide paths, deletions, excluded `.beads/`, `.git*` refused), `next_step`, `admit_next` (no new claim), schema v11 with `after_commit`, `prepare` refuses `branch_moved`, `Next: advance`, the round's advance phase (FIFO, before new tasks). |
| Changes from .16 required by owner decisions | D2: the input text says tests can and should be run (needs B2; the input names the commands and the scratch folder). D3: drop the label from `NextStepRequest` and the `not_approved` word; the advance still checks `in_progress` and assignee `taskloop`. D4 matches .16 Q4. D12: S5e's preparation runs the profile's `setup` at the slot's checkout of the task branch (default `just install`), recorded in .16 2.9 and 8.7. |
| Why | Without it nothing writes code. |
| Depends on | S4 (built). S5a can start now. S5b's input text and smoke need B2. |
| Size | 3 slices: S5a preparation (about +15 source lines), S5b kind and hand advance (about +190 / +300 test lines), S5c round advance (about +40 / +260). |
| Open decisions | .16 Q2, Q3, Q5, Q6 (recommendations stand); Q1 and the label check are answered by D2 and D3. |
| Design / smoke | yes, .16 (revise for D2, D3) / yes (.16 section 5, plus one implement run that runs a test in the sandbox) |

### B3. Profile reader (`.task-loop.json` successor)

| | |
|---|---|
| What | One reader and validator for a minimal repository profile `.task-loop.json`, hard cut, no old-key reader: `setup` (ordered argv list run to prepare a slot's environment; may name a repository script such as `just bootstrap`; default `just install` when absent), `checks` (named checks: name, argv, timeout), `required` (the names of the checks required to land), `target` (land branch, default `main`). Tasks tl-8bh9.1.1 PROFILE-READS, tl-8bh9.1.2 PROFILE-SURFACE. |
| Why | B2 needs the setup command, B4 the checks and their required names, B6 the target. Without a profile they become hard-coded factory knowledge of this repository. |
| Which version is read (D11, reading in section 7) | `setup` and the `checks` commands: from Git at the commit under test (the task branch; X for checks, the branch at admission for attempt 1's setup), never the working tree, like a GitHub `push`/`pull_request` workflow. `required` and `target`: from the target (`main`), like branch protection, so a task cannot drop a required check (O1). A required name the candidate's `checks` does not define fails the checks step, as a required GitHub check that never reports blocks the merge. |
| Accepted risk | A task may change `setup` (D1); that code runs outside the sandbox, with network, before anyone reads it (D12). Flagged, not a blocker; B6's land summary lists every changed `setup`/`checks` entry for the person. |
| Depends on | nothing; small |
| Size | 1 slice (reader at a commit, validation, `tl config show`-style print) plus the new `.task-loop.json` content |
| Open decisions | O1 (confirm required names from `main`; not blocking) |
| Design / smoke | short design section (schema, refusals), may live in B2's plan / no |

### B2. Sandbox and environment: tests inside the agent's sandbox

**Built (2026-11-11)** as [S5e](tl-8bh9.4.3.1.16.2/plan.md) S5e-1 (setup) and S5e-2 (access: `access.py`, preflight with
the `codex sandbox` probe, the agent's roots and offline environment); live smoke not run. The text below is the design
input as it stood before.

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

1. **Prepared per-slot environment (decided, D12).** At preparation, before dispatch and outside the sandbox, with
   network, the factory runs the profile's `setup` (B3) in the slot, with `UV_CACHE_DIR` and the tool directories
   pointed at a per-slot folder. `setup` is read from the same ref as the checks: the task branch as checked out in the
   slot (for attempt 1, the branch at admission, D; for implement, the plan commit). Default `just install` when the
   profile names none. For this repository, `setup` names a new just recipe (for example `just bootstrap`):
   `uv sync --frozen --no-editable` and a warm-up of the pinned ruff, pyrefly and import-linter. For other
   repositories it is whatever makes the slot ready (the owner's example: Unity with assets pre-downloaded, Unity and
   its license pre-installed). Runs once per slot and again only when its inputs changed (for this repository `uv.lock`
   or the pins; the exact "changed" key is a design point of this block). Accepted risk: a task can change `setup`, and
   that code runs with network outside the sandbox (B3).
2. **Per-attempt scratch folder** as the one writable root outside the slot (for example
   `<artifacts>/<attempt>/tmp`), with `TMPDIR` set to it; `/tmp` stays excluded. Never inside a Git directory.
3. **Offline inside**: `UV_OFFLINE=1` and the per-slot cache, writable, so `just test`'s reinstall of the project wheel
   works from the cache.
4. **Access per step kind**: as .16 section 2.8 now proposes, a `StepKind.access` field; plan keeps today's values,
   implement gets the scratch root and offline env.
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
| Open decisions | none (D12); Run S's unknowns remain |
| Design / smoke | yes (own plan) / yes (Run S first, then an implement run that runs a new test) |

### B4. Checks step

| | |
|---|---|
| What | A non-agent step after implement: the factory runs the checks (B3) on exactly X, each with its timeout, output kept as evidence files, one result row per check in factory.db (check name, argv digest, profile digest, X, exit, timed out, duration). The step's verdict is passed only when every check named required (by `main`'s profile, O1) passed. |
| What "passed" means (proposed) | Exit 0, not timed out, launched on X with the commands from the profile at X, and the tree still clean at X afterwards (a check that changes tracked files invalidates the candidate, candidate-checks). A required name with no command at X is a failure. A failure is a result, never a pass; a missing result runs again (glossary: check, pass). No reuse across candidates. |
| How it runs | Through the shelf process API (no subprocess in factory source); on the host with normal host networking (D9), before any review, with the agent's scrubbed environment and push bar, no scratch HOME (D10). In a slot holding X, prepared by `setup` (B2) at X (the implement slot is released; checks admits one like an advance). An interrupted block repeats after stop proof. |
| Step or verify rule | Its own step (`check` in `Next`/`rounds.log`), not a verify rule: it needs its own attempt, deadline, evidence, restart and failure route. Not a `StepKind` (no agent, answer or commit, .15 section 5); own table. |
| Failure route | O2. Proposed: failed checks hold the task (B7) with the output path; automatic repair (back to implement with the output) later, tl-7i9k.56.1. |
| Why | Without it, "implemented" means only "committed": the person runs the checks by hand. |
| Depends on | B1, B3; B2 for the same prepared environment |
| Size | 3 slices: schema and result store; the check runner and step in `tl step` (show, list); the round phase |
| Open decisions | O1 (not blocking), O2; where they run is decided (D10) |
| Design / smoke | yes ([tl-8bh9.14.6](tl-8bh9.14.6/plan.md); earlier tasks tl-8bh9.5, tl-8bh9.5.1, tl-8bh9.5.2) / yes ([M2 runbook](tl-8bh9.14.6/live-smoke.md)) |
| Built | S6a-S6e (5 slices, each reviewed): failure route as in O2's M2 reading (a failed `done`, claim kept, no hold); holds are B7 |

### B5. Review step

An agent step reading the diff and check results, answering accept or changes, no commit. **Recommended optional for
self-hosting:** the person reads every diff before landing until M5; add review only when the person wants to stop
reading every diff. Depends on B4. Size about 2 slices. Design: yes (later). Not in any milestone below.

### B6. Land and close

| | |
|---|---|
| As built | L0-L5 of [tl-8bh9.14.8](tl-8bh9.14.8/plan.md) (sections 25-29): squash in Git objects, no slot unless S's tree differs from X's or the required names changed; non-forced push from the person's checkout with no lease (the read right before it and Git's fast-forward rule); close as `taskloop`, never synced (O3, O4 decided there). M3 is reached once the [M3 live smoke](tl-8bh9.14.8/live-smoke.md) passes, owner- or authorized-agent-run. |
| What | `tl step land TASK` (proposed name), person-run at first: requires checks passed on X; in a slot, squash X onto the current origin target; if the target moved, the new candidate runs the checks again (B4); conditional non-force push to origin `main` naming the expected old tip; then `bd close` with the land commit; records each action so a rerun does only what is missing (delivery-publication, D9). |
| Glossary | land = accepted integration, confirmed task completion and any required task sync; merge and push are its actions, not steps. Publishing `task/<id>` does not land. |
| Repository rule | CLAUDE.md: the main checkout is the person's; local Git permission does not authorize remote publication or merge. The factory never writes the main checkout; the person pulls. A factory push to origin `main` needs the owner's explicit permission (O3). Task sync (`bd dolt push`) is a remote operation (O4). |
| Land summary | Lists for the person every changed `setup`, `checks` or other check-configuration file between the target and X (D11: a task may change them). |
| Why | Closes the loop: without it every task ends with hand merge, push and close. |
| Depends on | B4 |
| Size | 2-3 slices (land record and actions; conflict and moved-target refusals; tracker close) |
| Open decisions | O3, O4 |
| Design / smoke | yes (own plan, tasks tl-8bh9.9, tl-br2.8 SETTLE, tl-br2.19 ACCEPTDONE) / yes (scratch remote and tracker) |

### B7. Questions and holds

| | |
|---|---|
| What (proposed, O5) | Every terminal non-success (needs_owner, incomplete, rejected verdict, repeats exhausted, failed checks, timeout, `branch_moved`) holds the task: the factory adds the agent's explanation (or the check output path) as a task comment, removes the label `auto`, and returns the claim (the existing abandon path). By D3 and D4, the person answers by editing the task's requirements and adding `auto` again; the next round starts it at plan. |
| Why | Today such a task stays claimed and silent forever; an unattended loop needs every stop to be visible in the tracker. |
| Not now | Structured questions with choices and dashboard answers (tl-8bh9.6.1, settled design), answer revisions, local waits. |
| Depends on | B1 (implement dispositions); B4 adds failed checks as one more reason. Needs beads-client writes for comment and label (not verified in 0.2.0: may need a shelf request). |
| Size | 2 slices (hold operation and words; the round applies it) |
| Open decisions | O5 |
| Design / smoke | short plan / yes |
| Built | H1-H3 of [tl-8bh9.14.9](tl-8bh9.14.9/plan.md) (each reviewed): schema v14 and the hold record, the hold operation and its words, the round applying it; the M4 smoke waits for B11 and B13 |

### B11. Keep-awake

Lifetime-scoped while `tl step rounds` runs (accepted, .4.6): macOS `caffeinate -i -w <pid>`, Linux `systemd-inhibit`,
through the shelf process API. Needed for M4 on a laptop. 1 slice, no design, small smoke.

| | |
|---|---|
| Built | K1 of [tl-8bh9.14.9](tl-8bh9.14.9/plan.md) (section 27): `keep_awake.py`, spawned before the rounds' SIGINT handler with the shelf's hold replayed first, stopped with `stop_tree` on every way out; best effort (`rounds keep_awake unavailable:<why>`). Gated; not observed on macOS, ineffective on a Linux host whose logind refuses the inhibitor (seen on OrbStack); M4 not reached (smoke step 6) |

### B8. Install, pin, release

| | |
|---|---|
| What (proposed, O6) | Until M5: a dedicated runner worktree at a known commit with its own `.venv`, never synced while rounds run. At M5: one install directory per version (a venv per commit or tag), a durable owner pin beside the machine config (`<config stem>.pin.toml`, [plan](tl-8bh9.8.3/plan.md) Q2), `tl` resolving the version once at start; the entry process already uses the same interpreter (`sys.executable`). Release: an annotated tag on `main` by the person. No marketplace, plugin cache or canary. Task tl-8bh9.8.3 INSTALL-OWNER. |
| Why | D9: version fixed until restart. Self-hosting lands changes to the factory's own code while it runs; a reinstall under a running loop would give new entry processes new code against an old round and factory.db. |
| Design | [tl-8bh9.8.3](tl-8bh9.8.3/plan.md) (2026-11-12, proposed): `tl install REV --checkout PATH` (annotated tag or full commit id; Git objects exported natively, `uv --project <source> sync --frozen --no-editable --no-dev --reinstall-package iorlas-task-loop` from the installs root, verified, manifest last; an interrupted install refuses `incomplete` and is removed by the person) into `~/.local/share/task-loop/installs/<commit>/`; `tl pin REV` / `--clear` writing `<config stem>.pin.toml` beside the machine config; the `tl` console entry resolving the pin once at start and exec'ing the pinned install (`python -I -m taskloop`), `refused pin:missing|incomplete|broken|invalid` otherwise, never another install; `tl version`; running rounds and their entries keep their interpreter until restarted, and every switch drains first; factory.db unchanged (v14), `refused schema` kept both ways; release an annotated `factory-v*` tag by the person |
| Depends on | nothing (the runner worktree is the interim until I3); built after M4 |
| Built | I1 (resolver, pin file, `installs.state`, the one exec in `start`, `tl version`), I2 (`tl install`) and I3 (`tl pin REV` / `--clear`, the `rounds install` line, the implement input's and AGENTS.md/CLAUDE.md's `tl` sentence, the schema-word tests, the [M5 runbook](tl-8bh9.8.3/live-smoke.md)); plan section 21. Q13 proposed, built per its recommendation (rollback by `tl pin <older>` is notice-only; the older code's `refused schema` is the refusal); needs the owner's sign-off. M5 B8 smoke passed on Linux 2026-11-12 ([findings](tl-8bh9.8.3/m5-smoke-findings.md)); macOS (its step 8) not run. Q9 open (blocks the first release) |
| Size | 3 slices (I1 resolver, pin file, the one exec and `tl version`; I2 `tl install`; I3 `tl pin`, words, runbook) plus the M5 B8 smoke; about +760 source, +2,200 test lines, no shelf change |
| Open decisions | O6 answered by the plan's Q1-Q15 (proposed; Q9 blocks the first release; Q13 proposed, built per its recommendation (notice-only), needs the owner's sign-off); the reduced release scope in [operations](tl-8bh9.8/operations.md) stays proposed and unbuilt |
| Design / smoke | yes ([plan](tl-8bh9.8.3/plan.md)) / yes (plan section 17) |

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
| Protected files: the baseline gated changes to `.task-loop.json`, `mise.toml` and agent instructions | [.13 audit](tl-8bh9.13/audit.md) | Not carried as a gate. B3 reads the required check names from the target (O1) and the commands from the task branch (D11); B6's land summary lists changed check-configuration files (`justfile`, `.task-loop.json`, `pyproject.toml`, `mise.toml`, import-linter contracts, `tests/rules/`) for the person. |
| Check environment shaping (credential strip, scratch HOME) | .13 audit | Decided (D10): the agent's scrubbed environment and push bar, no scratch HOME. |
| Review verdict rewriting, stray-file quarantine | .13 audit | Not carried; review is B5, strays are repeats. |
| `tl step verify` does not check the claim | .9 known gap | Unchanged until a case appears. |
| Branch rule D for a later step (`branch_diverged`) | .15 section 5 | Adopt all slots from `main`'s history. Since .15 section 17 a new task branch starts at the local `main`'s tip (it must contain the slot's D), so slots no longer need moving and the rule holds for every later `main`. |
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
| **M2 checks in the factory** | B4 (built S6a-S6e; reached once the [M2 live smoke](tl-8bh9.14.6/live-smoke.md) passes) | See per-check passed/failed on X in `tl step show`; rounds run the checks after implement | Read the diff; land and close; handle failures (re-run with `tl step start`, or abandon) |
| **M3 land and close** | B6 (built L0-L5; reached once the [M3 live smoke](tl-8bh9.14.8/live-smoke.md) passes) | Run `tl step land TASK` after reading diff and checks: squash on origin `main`, task closed | Decide each land; tracker sync if O4 says so; failures |
| **M4 unattended loop** | B7 (built H1-H3), B11 (built K1), B13 Git read timeout; not reached until the M4 live smoke passes | Leave rounds running overnight; find held tasks with reasons in the tracker; answer by editing the task and re-adding `auto` | Land; reboot recovery (`--abandon`); upgrades |
| **M5 daily self-hosting** | B8 (built I1-I3; its smoke passed on Linux 2026-11-12, macOS not run), B10 (then the dashboard); not reached while B10 is not built | Run a pinned version; land factory changes and adopt them by changing the pin and restarting; see time since last command | Land decisions; pin changes; anything deferred (section 6) |

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
| Agent-written code runs on the host before any person reads it: B4 runs the candidate's checks outside the agent's sandbox, and B2's `setup` is read from the task branch and runs with network outside the sandbox | **Accepted by the owner** (D10, D12): automatic checks are the cheapest review. Mitigation: the agent's scrubbed environment and push bar for checks and setup; the land summary lists changed `setup`/check configuration; the person reads the diff before land until review exists. A review of the change set for suspicious code is a later, separate block (deferred). |
| The agent weakens its own checks (D1: it may edit `justfile`, profile, `pyproject.toml`, import-linter contracts, `tests/rules/`) | Required check names from `main` (O1), so a task cannot drop one; it can still change a required check's command (as a GitHub PR can edit its workflow), so the land summary lists every changed check configuration; no automatic land. |
| Running tests in the sandbox widens it: a writable scratch root outside the slot, more background processes | Pinned `git_dir` first; pointer checks unchanged; scratch never in a Git directory; worker-gone gate before every Git write. |
| Runaway agents and cost | Deadline per attempt (`--minutes`); at most 3 repeats; no automatic retry or repair; failures hold (B7); D3 means removing `auto` does not stop a task in progress: `tl step release --abandon` does. |
| The factory edits itself while running | Runner worktree (later pinned install) separate from slots; the entry uses the runner's interpreter; never sync or reinstall the runner while rounds run; upgrade = stop, finish or abandon, discard factory.db if the schema changed, switch, start (D9). |
| Schema discards (v11 S5, then checks, land, holds) | Finish or abandon in-flight attempts before each; planned tasks restart at plan and reuse their plan (D4). Batch schema changes where slices allow. |
| Claim lease lapses between steps | Hold on `claim_lost` (B7). |
| Unobserved platforms | macOS Seatbelt, codex versions other than 0.167.0: Run S on each machine used. |

**Deferred deliberately:** review step (B5); a review of the change set for suspicious code before checks or setup run
it (owner, 2026-11-11: a separate idea, not now); automatic land; PR mode and the merge queue (held); structured questions
with choices and dashboard answering (tl-8bh9.6.1); session resume (B9); hung-agent detection (D7); account routing
(B12); per-step model, effort or minutes; automatic retry and repair (tl-7i9k.56.1); start at boot or a service (D6);
multi-machine tracker sync; release publication beyond a tag; pass reuse or a check cache; Windows.

## 7. Decisions and open questions

### 7.1 Decided (owner, 2026-11-11)

These replace the earlier proposals that checks and setup run only `main`'s code.

1. **Where the factory's checks run: DECIDED, on the host** (D10), in the factory, before any review, with the agent's
   scrubbed environment and push bar (no scratch HOME, no sandbox wrapper). The owner knowingly accepts that
   agent-written code runs before anyone reads it: "it is the cheapest review: automatic checks". A review of the
   change set for suspicious code is a separate, later idea (section 6, deferred).
2. **Which configuration the checks and setup use: DECIDED, GitHub's model** (D11): "copy GitHub security and
   configuration model; best developer experience for AI and humans".
3. **Slot environment: DECIDED, the factory runs the repository's own setup** (D12) before the agent starts, outside
   the sandbox, with network; commands named in `.task-loop.json` (which may name a repository script such as
   `just bootstrap`), read from the same ref as the checks. Default `just install` when the profile names none.
4. **Tracker entries: DECIDED, file them** (D13; filed separately).

**GitHub's model, as this roadmap understands it** (from knowledge of GitHub Actions and branch protection, not
re-checked against current GitHub documentation for this file):

| GitHub | Which configuration applies |
|---|---|
| `push` event | The workflow files at the pushed commit. A push that edits a workflow runs the edited workflow. |
| `pull_request` event | The workflow files at the PR's merge commit (head merged into base, `refs/pull/<n>/merge`), so a PR that edits a workflow is tested with its own edit. For a PR from a fork, the `GITHUB_TOKEN` is read-only and repository secrets are not passed. |
| `pull_request_target` event | The base branch's workflow files, in the base's context with secrets; the PR cannot change what runs (it is the risky event when such a workflow checks out the PR's code). |
| Required status checks | Configured on the base branch (branch protection or rulesets), not by the PR. They match checks by name; a required check that never reports blocks the merge. A PR can change what a required check's workflow does, which is why repositories add CODEOWNERS review on `.github/workflows/`; rulesets can also require a workflow file from a named repository and ref (for example a pinned branch or SHA), where available on the plan. |

**Proposed reading for the factory:**

- Commands (`setup`, the `checks` argv) are read from the profile `.task-loop.json` at the branch or commit under test
  (the task branch; X for the checks step), like a `push`/`pull_request` workflow. A task may legitimately change them.
- Which check names are **required** to land, and the land target, are read from `main`'s profile, like branch
  protection, so a task cannot drop a required check. A required name the task branch does not define fails.
- Land lists every changed `setup`, check or check-configuration entry for the person (the factory's analogue of
  CODEOWNERS review on workflow files).
- **Accepted risk, flagged, not a blocker:** setup from the task branch runs with network outside the sandbox before
  anyone reads it.

### 7.2 Still open (recommendations; none blocks M1)

1. **O1. Required check names from `main`.** The "required names from `main`" part of the reading above is this
   roadmap's inference from GitHub's branch protection, not the owner's words. **Recommendation: confirm it; until then
   B3 builds it that way.** Not blocking; settle before B4 is built.
2. **O2. When required checks fail, hold or repair automatically?** **Recommendation: hold the task with the output
   path (B7) first; add at most one or two automatic repair rounds after smokes show how often it would help.**
3. **O3. Does land push to origin `main`, and who runs it?** **Recommendation: the factory pushes, but only when the
   person runs `tl step land TASK`; a direct squash push with the expected old tip, no PR; no automatic land before
   review exists.**
4. **O4. Does land run `bd dolt push`?** **Recommendation: no; land closes the task locally, sync stays the person's
   until a second machine is used.**
5. **O5. How is a task held?** **Recommendation: comment the reason on the task, remove `auto`, return the claim; the
   person answers by editing the task and adding `auto` again, and the task restarts at plan.**
6. **O6. How is the factory installed before M5?** **Recommendation: a runner worktree at a chosen commit, never
   synced while running; per-version install directories with a pin file beside the machine config at M5 ([tl-8bh9.8.3](tl-8bh9.8.3/plan.md)).**
