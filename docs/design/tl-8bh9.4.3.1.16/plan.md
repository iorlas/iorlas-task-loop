# Step sequencing and the implement step kind (slice S5)

Task: tl-8bh9.4.3.1.16 (proposed id; not in the tracker). Design, 2026-11-11, against HEAD edc4e31e2 (S4 built). Docs
only: nothing is built or run. Commands run: source and doc reads, `git status`, the policy's own line counter
(`tests/rules/test_policy.code_lines`) over every `src` and `tests` file, and reads of the installed `git_porcelain`
(`real_read.dirty`, `diff`, `Worktree.stage`). The working tree holds another agent's uncommitted edits (`attempt_status`,
`cli`, `cli_composition`, `step_render` and three test files); the counts below are of the tree as read and may move by a
few lines.

Read: CLAUDE.md, glossary, [.15](../tl-8bh9.4.3.1.15/plan.md) in full (3.2 to 3.5, 5, 7, 8, as built 10 to 16), source
`steps, plan_step, admit, attempt_types, factory_commit, verdict, verifier, prepare, repeat, attempt_status, round,
operations, tracker, task, selection, factory_schema, attempt, composition`, and `justfile`, `pyproject.toml`,
`mise.toml`, `.gitignore` (for the environment, 2.9).

The owner answered section 8's questions on 2026-11-11; section 8 records them as **decided**. Section 1 also lists the
.15 owner answers. Everything else in this document is **proposed**: section 9 lists what it decides without a
question, open to veto, and section 2.9 lists what is **unknown** until the S5e spike.

## 1. Goal, and what the owner gets

A task labelled `auto` runs **plan, then implement**, by itself, one `tl step next` round at a time:

1. A round admits the ready task: the plan step runs, is verified, its slot released (claim kept), `task/<id>` published.
2. A later round sees the plan attempt **done** (verified, settled, published) and a following step: its `Next` word is
   `advance`. One `bd show` confirms the task is still `in_progress` and assigned to `taskloop`; the implement attempt
   is admitted into a free slot **without claiming again**, starting from the published plan commit.
3. The implement step runs its own static analysis and tests in a prepared environment (2.9), is verified, released and
   published to the same `task/<id>` (a fast-forward of the plan commit). Its `Next` is `done`: implement is the last
   built step. Nothing merges or lands.

`tl step start TASK` does the same advance by hand. `tl step show/list` print `Step: implement` and `Next: advance`.

**Ingestion and execution are separate (decided, 8.6).** The label `auto` is checked only where the scheduler ingests a
fresh task from the tracker: a round's ready read (`tracker.ready_rows(label)`, as built), with readiness and priority.
Once a task is claimed and in progress it is the factory's claimed work, and no label check applies anywhere: neither
`tl step start TASK` nor a round's advance to the next step. Removing the label from a claimed task does not stop it;
`tl step release --abandon` does.

**Already decided (owner, .15 section 8, 2026-11-10; cited as ".15 Qn" to keep them apart from section 8 here):**
.15 Q2 a task advances automatically after one `bd show` confirms `in_progress` and claimed by `taskloop`; the claim is
never retaken (its "labelled `auto`" part is replaced by 8.6). .15 Q3 tasks waiting for their next step go before new
ready tasks, oldest first. .15 Q4 one `--model`/`--effort` pair for every step (and, by .15 3.8, one `--minutes`).

## 2. The implement step kind (`implement_step.py`, reached only through `steps`)

### 2.1 Who it is for

An agent that changes the repository's code, tests and docs as the committed plan says, in one session, without Git
writes or network, and that runs the project's static analysis and tests in its slot before answering (8.1). Its result
is a commit the factory makes of the paths the agent lists. It is not the checks step, not review and not land:
"verified" for implement is structural (2.6), never "the code works"; the agent's own test run is evidence it reports,
not a verdict.

### 2.2 Input text

`input_text(task, rules)`: the task's own prose (title, requirements, acceptance, exactly as for plan), then the closing
words. The plan is passed **by reference** (8.5): the slot is on `task/<id>` containing the plan commit (`prepare`
refuses otherwise, 3.4), so `docs/design/<task-id>/plan.md` is in the checkout. `StepKind.input_text` keeps its signature.

Closing words (proposed text; `<id>` and the caps are filled from the rules; the command names are this repository's
and come from the environment slice, 2.9):

> The plan for this task is `docs/design/<id>/plan.md`, committed on this branch by the plan step. Read it first and
> implement it, with tests for the behavior it adds or changes. If the code already does what the plan asks, change
> nothing and answer `unchanged`. Otherwise change the files the plan needs and answer `implemented`. You may add,
> change and delete plain files anywhere in the repository, at most 96 files of at most 1 MiB each, except: any path
> with a component starting with `.git`, anything under `.beads/`, executable files and symlinks. You may update the
> plan's own folder (for example an "As built" section). You may read Git; do not run `git add`, `git commit`, `git
> push` or any other Git write; they will fail. There is no network: do not add or upgrade dependencies. Temporary
> files go to `$TMPDIR`, which the factory empties after the step. Before answering, run the project's static analysis
> (`just check`) and its tests (`just test`) and fix what they report; both run offline in this slot. With
> `implemented`, list in `paths` every file you changed, added or deleted and give a one-line commit `message`; the
> factory commits exactly those paths. Remove any other file you created. Anything left uncommitted is reported back to
> you as a failed step. In `explanation`, say which commands you ran and how they ended, and name every test file you
> added. If you could not finish, answer `incomplete`; if the plan cannot be implemented as written or needs a
> decision, answer `needs_owner`; say why in `explanation`.

What the agent may do: read anything in the slot, run local offline commands (the static analysis and tests among them),
edit files within the rules, write `$TMPDIR`. What it may not do: any Git write (the sandbox blocks writes to the Git
directory, as for plan), commit (the factory commits the listed paths, kept from .4.3.1.7), network, `/tmp`, escalation
(`approval_policy=never`).

### 2.3 Dispositions, effects and answer schema

| Disposition | Effect | Decoder rule |
|---|---|---|
| `implemented` | `commit` | `paths` non-empty, each `path_allowed`, unique, at most `max_paths`; `message` 1..500 chars, no NUL, no trailer |
| `unchanged` | `keep` | `paths == []`, `message` null |
| `incomplete` | `none` | `paths == []`, `message` null |
| `needs_owner` | `none` | `paths == []`, `message` null |

`explanation` is a string of at most 2000 characters for every disposition. **What the agent ran is reported in
`explanation` only (proposed):** no structured field for commands, results or new test files. Nothing in the factory
reads it (the checks step reruns what counts), so a field would be an unused contract; new test files are already in
`paths`. The answer schema follows the plan's strict-format pattern (plain object, every property required, nullable
by type list, bounds only in the decoder) without `plan_path`:

```json
{"type": "object", "additionalProperties": false,
 "required": ["disposition", "paths", "message", "explanation"],
 "properties": {
  "disposition": {"type": "string", "enum": ["implemented", "unchanged", "incomplete", "needs_owner"]},
  "paths": {"type": "array", "items": {"type": "string"}},
  "message": {"type": ["string", "null"]},
  "explanation": {"type": "string"}}}
```

`needs_owner` has no questions machinery yet (tl-8bh9.6.1): it ends the step as a failed `done` whose explanation the
owner reads, exactly as for plan today.

### 2.4 StepRules

| Field | Plan (unchanged) | Implement (decided scope 8.2; caps proposed) |
|---|---|---|
| `root` | `docs/design/<id>/` | `""` (the repository) |
| `max_paths` | 32 | 96 (code, its tests and docs; was 64 before tests were part of the step) |
| `file_cap` | 1 MiB | 1 MiB |
| `deletions` | False | True |
| `excluded` (new field, default `()`) | `()` | `(".beads/",)` |

`path_allowed` gains one test: no path starting with an `excluded` prefix. The existing rules already refuse `.git*`
components, `..`, NUL and paths over 255 bytes, and `verdict._changes` and `factory_commit.unsafe_path` already refuse
any mode other than 100644 (so executable files and symlinks cannot be added or changed; stated in the input).

Three machinery changes the repository-wide root needs (each a no-op for plan):

- **Ignored-file scope.** `attributes(rules)` today passes the root as a pathspec to `ls-files -o -i`; with root `""`
  that is the empty pathspec, which Git refuses (and would report every `.venv`/`__pycache__` file if it did not).
  Becomes `attributes(rules, paths)`: the `.gitattributes` of every folder on the way to the root and the root (only
  when the root is not `""`), plus, for each listed path, the `.gitattributes` of every folder on its way and the path
  itself. For plan every added pathspec is already under the root: the result's meaning is unchanged (the
  `test_steps` attributes case gains a listed path). For implement an ignored file blocks the commit only when it is a
  listed path or an attributes file on a listed path's way; the slot's ignored `.venv/` and test run leftovers do not.
- **`.git*` files.** `git_file` with root `""` refuses any changed `.git*` path anywhere in the slot (`unsafe`, then a
  repeat with feedback). Kept: the agent may not change Git's own files (8.2).
- **Deletions.** `unsafe_path` today calls a listed path that is absent `unsafe`. With `rules.deletions`, an absent
  listed path is a deletion when it is a 100644 file in B's tree (one `repo.tree(base)` read); otherwise still `unsafe`.
  `Worktree.stage` already stages deletions (`add -A` on literal paths), `diff` runs with `--no-renames` (a rename is a
  deletion plus an addition, both listed), and `verdict._changes` already admits `D` when `rules.deletions`.

### 2.5 The artifact rule at X

None: `artifact(tip, rules)` returns None, so `Verified.blob` is NULL (nullable since v9, read back since S3).
`ARTIFACT_RULES = ()`.

### 2.6 What "verified" means for code

The generic rules only: the chain rules over the step run (`commit_absent`, `not_descendant`, `chain_length`, `paths`,
`mode`, `file_size`, `nothing_written`), judged from the implement step run's attempt 1 B (so the plan commit is never
re-judged), and the clean tree at X. `unchanged` is `reused`. The agent's own test run (8.1) is reported in
`explanation` and never read by the verdict; whether the code builds and passes tests is the checks step (its own
design, its own table), which reruns them outside the agent's control.

### 2.7 Repeat feedback

Same machinery, same `REPEATABLE` reasons, `ATTEMPTS = 3` (decided, 8.3). The implement kind's words:

- `OPENING`: `uncommitted` and `unsafe` as plan; `ignored`: "These paths are ignored by Git. A listed path Git ignores
  can never be committed, and an ignored attributes file on the way to a listed path blocks the commit."
- Instructions: remove every untracked file listed that you do not want committed; restore every tracked file you changed
  or deleted and do not want committed (`git show HEAD:<path> > <path>`; `git checkout`/`git restore` are unavailable);
  with `implemented`, `paths` lists every file you want committed, changed, added or deleted. The `unrecorded` variant
  ("nothing of attempt N was committed: list every file again") and the `unchanged` variant as for plan.

The frame around them (the opening, the nonce markers with the `git status` listing as data, the instructions, the task)
moves from `plan_step.feedback` to a new leaf module `step_text.py` with the one shared sentence about Git writes; both
kinds call it. Plan's input and feedback bytes stay identical (the S3 constants in `test_steps` guard them).

### 2.8 Access: a per-kind field (proposed; built in S5e)

**Known from the code.** `attempt.SANDBOX = "workspace-write"` and `attempt.CODEX_ACCESS` (`--ignore-user-config`,
`--ignore-rules`, `network_access=false`, `writable_roots=[]`, `exclude_slash_tmp=true`, `exclude_tmpdir_env_var=true`,
`approval_policy=never`, `tool_output_token_limit=3000`) are module constants. `operations` passes `SANDBOX` into every
admission (stored as `attempt.sandbox`, copied by a repeat); `Attempts._refusal` refuses `sandbox` when the stored value
is not `SANDBOX`; `Attempts._launch` passes `list(CODEX_ACCESS)` as `LaunchInputs.access`. The agent's environment is
the factory's own minus credentials and the factory's venv (`composition.credentials`); nothing sets `TMPDIR` or `UV_*`.

**Proposed.** A leaf module `access.py` holds `Access(sandbox: str, codex: Callable[[Path], tuple[str, ...]], env:
Callable[[Path], Mapping[str, str]])`, each function taking the slot's scratch folder (below). `StepKind` gains
`access: Access`. `PLAN.access` is today's values, byte for byte (`codex` ignores the scratch folder, `env` is empty);
a constant test guards them as S3's guard plan's input. `IMPLEMENT.access` differs (exact values from the spike):

| Setting | Plan | Implement (proposed) |
|---|---|---|
| sandbox | `workspace-write` | `workspace-write` |
| network | none | none (installs happen outside the sandbox, 2.9) |
| writable roots | none | the slot's scratch folder, `<factory state>/scratch/<slot>/`, outside the slot |
| `/tmp`, `$TMPDIR` | excluded | `/tmp` excluded; `TMPDIR` set to the scratch folder's `tmp/` |
| extra env | none | `UV_OFFLINE=1`, `UV_CACHE_DIR` in the scratch folder, `UV_PYTHON_DOWNLOADS=never` |

The scratch folder is outside the slot so nothing the tests write can make the tree unclean or reach a commit; the
factory empties it before dispatch and after release. Consumers: `_refusal` compares the stored sandbox to
`kind(admission.step).access.sandbox`; `_launch` passes `kind(step).access.codex(scratch)` and merges `access.env` into
the credentials' env; `operations.start` and `admit_next` store the admitted step's `access.sandbox`. `SANDBOX` and
`CODEX_ACCESS` leave `attempt.py`.

### 2.9 The environment for checks and tests (slice S5e)

**Known from the code and plans.**

- The dependencies come from GitHub Git sources (shelf packages) and PyPI (`pytest`, `pytest-xdist`, and the build
  backend `hatchling`); the first install needs network or a filled uv cache. The sandbox has no network, so the
  install runs **outside** it, before the agent.
- The project is installed as a **non-editable wheel** (`just install`: `uv sync --frozen --no-editable
  --reinstall-package iorlas-task-loop`; CLAUDE.md forbids editable installs and `PYTHONPATH`). Tests run the installed
  copy: after the agent edits `src`, tests see the old code until the wheel is rebuilt. So a **read-only shared venv
  outside the slot cannot test the slot's changes**; the rebuild must happen inside the sandbox, offline, every time the
  agent runs `just check`/`just test` (both call `install`).
- `just check` also runs `uv tool run ruff@<pin>` and `uv tool run pyrefly@<pin>` (tool environments in uv's cache) and
  `uv run --with import-linter==<pin>`; pyrefly and import-linter need the project's venv to resolve imports.
- pytest runs with `-p no:cacheprovider` (no `.pytest_cache`); 31 test files use `tmp_path` (a writable temp folder is
  required); the real-Git tests create repositories with their own `.git` under `tmp_path`.
- The slot's `.venv/` is ignored by `.gitignore`, so a venv in the slot does not make the tree unclean; the factory
  runs `prepare.base` in the entry process (outside the sandbox) before dispatch, which is where preparation fits.

**Decided (owner, 2026-11-11, 8.7).** The factory prepares the slot before the agent starts by running the repository's
own `setup` command(s): "that is the crucial part of slot setup, the reason we need slots". The commands are named in
the profile `.task-loop.json` (the repository may supply a script, such as a `just bootstrap` recipe, that the profile
names), read from the same ref as the checks: the task branch, like a GitHub `push`/`pull_request` workflow read at the
commit under test ([roadmap](../self-hosting-roadmap.md) section 7). For attempt 1 of a task that is the task branch at
admission (D); for implement it is the slot's checkout at the plan commit. Setup runs outside the agent's sandbox, with
network. When the profile names no `setup` (or until the profile reader, roadmap B3, exists), the default is
`just install`. Risk the owner accepts: a task may change `setup`, and that code runs with network outside the sandbox
before anyone reads it (flagged, not a blocker).

**Proposed.** A per-slot environment prepared by the factory: after `prepare.base` and before dispatch, for a kind whose
access asks for it, the entry runs the profile's `setup` at the slot's checkout (default `just install`; outside the
sandbox, with network), with `UV_CACHE_DIR` in the slot's scratch folder, so the slot's `.venv` and a cache holding every wheel, the build
backend and the pinned tools exist before the agent starts. It runs through the shelf process API the entry already
uses (`stream_proc`; an external-tool reason: uv), within the attempt's deadline. A failure is `unavailable
environment` and the attempt stays `admitted`, as for other pre-dispatch failures. Inside the sandbox the agent's `just
check`/`just test` then rebuild and run offline (`UV_OFFLINE=1`) against that cache. A shared read-only cache is the
fallback the spike measures.

**Unknown, settled by a spike before S5b** (one manual run of Codex with the implement access on this repository's slot;
written up as an as-built note in this folder, no code kept):

1. Whether `uv sync --frozen --no-editable --reinstall-package iorlas-task-loop` succeeds offline in the sandbox, with
   the cache in the scratch writable root (and whether a read-only shared cache could work instead: does uv need to
   write a lock or a build environment into the cache?).
2. Whether `uv run --frozen --no-sync` works offline with a read-only cache, and whether `uv tool run ruff@<pin>` and
   `pyrefly@<pin>` resolve from the cache offline (else: the mise-pinned binaries on `PATH`).
3. Whether `writable_roots=["<scratch>"]` together with `exclude_slash_tmp=true` and `exclude_tmpdir_env_var=true` is
   honored by Codex on the owner's machine, and pytest's `tmp_path` works with `TMPDIR` there.
4. Whether the real-Git tests can create and write `.git` folders under the scratch root, or the Codex sandbox protects
   every `.git` under a writable root (then those tests need a marker the agent skips, and the checks step runs them).
5. Time and disk for the first preparation and for an up-to-date one (per attempt, or only when `uv.lock` changed), and
   whether the uv cache can be shared across slots (hardlinks) or must be per slot.
6. What the agent sees when it changes `pyproject.toml` or `uv.lock` (offline sync fails): a clear message, so the input's
   "do not add dependencies" is enough.

If the spike shows a step that cannot work (for example the offline rebuild), S5e stops and this section is redesigned
before S5b.

## 3. Sequencing

### 3.1 `steps.next_step` (pure)

```python
def next_step(current: Step | None, done: bool) -> Step | None:
    """current: the task's current attempt's step, None when it has none or its abandon returned the claim.
    done: that attempt is verified, its release settled (claim kept) and its commit published."""
```

| `current` | `done` | Answer |
|---|---|---|
| None | any | `STEPS[0].step` (plan): a fresh admission |
| `plan` | True | `implement` |
| `implement` | True | None (the last built step: `done`) |
| any | False | None (the current attempt's own `Next` applies) |

`following(step)` is the one helper (the next entry of `STEPS`). `STEPS = (PLAN, IMPLEMENT)`, `kind()` gains its `case`,
`RULES` adds `implement_step.ARTIFACT_RULES` (empty), `Step = Literal["plan", "implement"]`, and the import-linter
contract `one-step-kind-owner` protects `implement_step` as it protects `plan_step`.

**After an abandon the task starts at plan (decided, 8.4; replaces .15 3.2's "the step after the last done step").** An
abandon is the owner deliberately giving up an attempt with `tl step release --abandon`: the slot is freed, the tracker
claim is returned and the task becomes ready again; a network or agent failure is never an abandon. The next admission
is fresh, like after a factory.db discard: the plan agent finds its plan and answers `unchanged` (`reused`) unless the
task changed; then the task advances. Fresh admission stays exactly as built (always `FIRST`, no `after_commit`), and
`next_step` needs no set of done steps.

### 3.2 `admit_chain.py`: the two admissions that continue a task

**Moves verbatim from `admit.py`** (about 65 code lines): `RepeatRequest`, `_Lost`, `PREVIOUS`, `admit_repeat` and
`_takeover`, as a class `ChainAdmission` with the same constructor ports it uses (`connect`, `begin`, `files`, `clock`).
`admit.py` keeps fresh admission and exposes, for `admit_chain`, the shared pieces it already has: `bound`, `as_count`,
`why`, the deadline check, `_open`, the free-slot observation and branch rule (`_observe`, `_branched`) and the
reservation insert (`_unheld`, `_issued`). They become module-level functions taking their ports, not private methods
called across modules. `repeat.py`, `operations`, `composition` and four test files change their imports only.

**New: `admit_next(request: NextStepRequest)`** where `NextStepRequest(previous: AttemptKey, checkout, model, effort,
deadline)` (no label, 8.6; the sandbox is the next kind's `access.sandbox`):

1. Read-only, before any effect: the deadline and choices; the task read (one `bd show`, below); the checkout's
   `repo_id` must equal the previous attempt's (`checkout` refusal otherwise); free slots and the branch rule, as fresh.
2. The input file is written under the new key (`implement` input text).
3. One write transaction, every fact re-read under the lock: the task's current attempt (highest `seq`) is exactly
   `previous` (else `task_attempted`); it is done (verdict `verified`, `slot_release.claim='kept'`, a `published_branch`
   row whose `commit_sha` is its `end_commit`; else `not_advanceable`); `next_step(previous.step, True)` is a step (else
   `not_advanceable`); an unheld free slot (else `no_free_slot`). Insert the reservation and the attempt: the new step,
   `number=1`, no `previous_attempt_id`, `after_commit = previous.end_commit`, `tracker_root` copied from `previous`,
   `seq + 1`, `slot_head = D`. Two concurrent advances meet the `UNIQUE(adapter, backlog, task_id, seq)`: one wins, the
   other is `task_attempted` (and launches the winner as existing, as fresh starts do).
4. **No claim call and no compensation.** The claim taken at plan admission is kept (.15 Q2).

**The tracker re-read** is the task read admission already does for the input text: `TaskInspection` gains `status` and
`assignee` (both on `beads_client.Bead`; `tracker.inspect_task` maps them). `admit_next` refuses `claim_lost` when the
status is not `in_progress` or the assignee is not `taskloop`. It reads no labels: the label is ingestion's (8.6), and
nothing else needs it on `TaskInspection`, so the `labels` field the earlier draft added is **dropped**. `tl step start`
and the round call `admit_next` identically. The word `claim_lost` keeps its one meaning (the tracker claim is gone; the
entry already refuses it).

### 3.3 Schema v11

`factory_schema` version 11, no migration (`current()` refuses v10, `refused:schema`):

- `attempt.step TEXT NOT NULL CHECK(step IN ('plan','implement'))`.
- `attempt.after_commit TEXT CHECK(after_commit IS NULL OR length(after_commit) IN (40,64))` and
  `CHECK((number = 1 AND step <> 'plan') = (after_commit IS NOT NULL))`: attempt 1 of every later step names the
  previous step's X; a plan attempt and every repeat name none (a repeat's chain reaches attempt 1).
- `ATTEMPT_ADMITTED` gains `after_commit` (fresh and repeat write NULL); `AttemptStore._load` reads it into
  `Admission.after_commit: str | None`. No other table changes (`attempt.sandbox` already holds the kind's sandbox).

### 3.4 `prepare` refuses `branch_moved`

In `_take` (attempt 1 on a clean detached slot), after the branch rule and before `take_branch`: when
`admission.after_commit` is set, the tip the slot would take (the local `task/<id>`, else the remote-tracking one, else
D) must contain it (`repo.is_ancestor(after_commit, start)`), else `refused branch_moved`, nothing taken, the attempt
stays `admitted`. Someone reset or deleted the branch after the previous step: the agent must start from the published
previous step. `branch_moved` already means "the local `task/<id>` is missing or does not contain a commit the factory
recorded for it" (publish); its GUIDE text fits both and is unchanged. Repeats start at E and are not checked again.

### 3.5 `Next: advance`, status and `tl step start`

- `attempt_status`: `Next` gains `advance`. `_released`: a settled, verified, published current attempt is `advance`
  when `steps.following(row.step)` is a step, else `done`. A verified unpublished one stays `publish` first (do not
  advance past an unpublished checkpoint). `list --stuck` is unchanged.
- `GUIDE["advance"]` (proposed): "The step is verified and on `origin`. The next step starts with `tl step start <task>`
  or the next `tl step next` round, after one tracker read confirms the task is in progress for taskloop." New GUIDE
  keys: `not_advanceable` and `environment`; `claim_lost` exists.
- `operations.start`: a settled release whose `Next` is `advance` goes to `admit_next` and launches the new attempt
  (`Started("started", ..., step="implement")`); every other settled release is `already_dispatched` as today.
- `STEP_ONLY` becomes "steps built: plan, implement; publishes task/<id>; no merge or land".

### 3.6 The round: settle, advance, admit, publish

- **settle**: unchanged; `advance` is skipped there like `publish`.
- **advance** (new phase, about 25 lines): the snapshot's `advance` attempts, oldest `release.released_at` first (FIFO,
  .15 Q3; no tracker priority read), each one `admit_next` with the round's choices, then the launch. No label: the
  round's `--label` is used only by the admit phase's ready read (8.6). The free-slot gate (`_full`) and the stop words
  (`STOPS`) are admission's: `no_free_slot` ends both advance and admit. `claim_lost`, `not_advanceable` and
  `task_attempted` are about one task: a `skip` move, nothing written.
- **admit**: unchanged, and the only place the label applies. A task with any attempt is skipped (`attempted`); claimed
  tasks are not in the ready set.
- **publish**: unchanged.

A plan attempt verified in this round's settle is advanced in the next round (the round works on its start snapshot;
no re-read). `rounds.log` lines (the step word is the move's attempt's step):

```
<time> <backlog> tl-1 implement advance started <new attempt>
<time> <backlog> tl-1 plan skip claim_lost <plan attempt>
```

`Action` gains `advance`; `round_log` grammar is unchanged (fixed words only).

## 4. Migration and cleanup

- v10 to v11 is a discard: the owner finishes or abandons attempts in flight (`tl step list` shows none `wait`,
  `start`, `verify`, `repeat` or `release`), stops `tl step rounds`, discards factory.db (the existing runbook), then
  installs. Published `task/<id>` branches stay; a task already planned restarts at plan, answers `unchanged`, and
  advances (one short plan attempt each).
- S5e adds no schema change; the scratch folders live under the factory's state folder and are recreated, never
  migrated.
- Docs with the code: glossary (`Next` words gain `advance`; step kind: `STEPS` is `(PLAN, IMPLEMENT)` and its
  `access`; disposition row lists the implement words; v11; `abandon` row, added with this design), README command
  list, the live-smoke runbook (`sqlite3` lines, the step word, the scratch folder), INDEX status, an as-built section
  here.

## 5. Tests and smoke

Behavior tests only, pytest functions; no test per private helper.

- `test_steps.py`: `next_step` as one parametrized table (section 3.1, every row); `kind("implement") is IMPLEMENT`;
  `STEPS` order; the plan bytes constants unchanged (they guard the `step_text` move); `PLAN.access` equal to the old
  `SANDBOX`/`CODEX_ACCESS` bytes; `IMPLEMENT.access.codex(scratch)` names the scratch root and keeps network off;
  `attributes` for plan with a listed path equals the old list, for implement equals only the listed paths' chains.
- `test_answer_contract.py`: the implement decoder (each disposition's valid and invalid shapes, an excluded path, a
  `.git*` path, 97 paths, a duplicate) through `kind("implement")`.
- `test_attempt.py` (S5e): an implement attempt launches with its kind's access and env, a plan attempt with today's; a
  stored sandbox not equal to the kind's is refused `sandbox`; a failed preparation leaves the attempt `admitted` with
  `unavailable environment` and nothing dispatched (a fake preparation port; no process in tests).
- `test_admit_chain.py` (new): `admit_next` never calls claim or unclaim; stores step, `after_commit`, copied
  `tracker_root`, the kind's sandbox, `number=1`, `seq+1`; refused `not_advanceable` when the previous attempt is not
  verified, released but abandoned, unpublished, or published at another commit; `task_attempted` when superseded; two
  concurrent advances admit one; `claim_lost` (status open, or another assignee) with nothing written; a task without
  the label still advances; a v11 CHECK test that an implement attempt 1 without `after_commit` is refused by the
  schema. The moved repeat-takeover tests keep their cases (imports only).
- `test_prepare.py`: `branch_moved` when the local `task/<id>` does not contain `after_commit` (nothing taken, slot still
  detached); passes when it does; a plan attempt is never checked.
- `real/test_commit_real.py`: a deletion listed by an implement answer is staged and committed; an absent listed path
  not in B is `unsafe`; an ignored `.venv/` file does not block a repository-wide commit; a changed `.gitignore` is
  `unsafe`.
- `test_operations.py` / `test_step_cli.py`: `Next: advance` in show, list and JSON; `tl step start` on an `advance`
  attempt admits the implement step and prints `Step: implement`.
- `test_round.py`: a round advances FIFO before admitting a ready task; `no_free_slot` stops both; `skip claim_lost`
  carries the plan attempt; the advance phase is called with no label.
- `test_advance.py` (new, end to end over fake ports): the round with real admission, verify, release and publish over
  factory.db and `git_porcelain`'s fake repo, a scripted agent (`Execution` is injected) that writes `plan.md` and then
  one code file and one test file, a fake tracker (claim, show) and a fake remote. Round 1 admits plan; round 2
  relaunches or verifies; the next round advances; then implement is verified and published on top of the plan commit;
  `Next: done`. If the attempt body cannot run synchronously over the fakes, the test seeds the captured plan attempt
  with SQL as `test_round` does and starts at the advance.
- **S5e spike (owner-run or agent-run by hand, on a scratch slot of this repository, before S5b):** the six unknowns of
  2.9, each with the command run and its result.
- **Live smoke (owner-run, scratch repo, scratch tracker, scratch `remote.git` only):** discard factory.db (v10
  refused first); `tl step next` rounds on one `auto` task until `Next: done`; check `rounds.log` shows `plan ... start`,
  `implement advance started`; `git log origin/task/<id>` shows the plan commit then the implement commit, with a test
  file in it; the implement answer's `explanation` names `just check` and `just test` and how they ended, and the
  agent transcript shows them run offline; the slot's tree is clean and the scratch folder emptied after release;
  `bd label remove <id> auto` between steps does **not** stop the advance; one `git branch -f task/<id> <base>`
  between steps gives `refused branch_moved` in entry.log. No agent runs whole-suite or live tests.

## 6. Slices and sizes (code lines; caps 400 per file, 80 per function, 800 per test file)

**Can S5a chain plan to a stub?** No. `STEPS` is a fixed tuple in code and `kind()` refuses an unknown step, so a stub
second kind would be an unused production kind (CLAUDE.md: no unused speculative features); and with plan alone,
`following("plan")` is None, so `advance` is unreachable and untestable without a second kind. So the split is a
behavior-preserving preparation, the environment, then the kind with sequencing, then the round's automation:

| Slice | What | Source | Tests |
|---|---|---|---|
| **S5a Preparation** (no behavior change) | the repeat takeover moved to `admit_chain` (3.2), `admit`'s shared pieces as module functions; `step_text` frame; `attributes(rules, paths)`; `TaskInspection` status and assignee | about +12 | imports; one attributes case; one inspection mapping case |
| **S5e Environment for running checks and tests in the sandbox** | spike first (2.9's six unknowns, no code kept); then `access.py` and `StepKind.access` (plan's values unchanged), `_refusal`/`_launch`/`operations` read the kind's access, the scratch folder (create, empty), the pre-dispatch preparation through `stream_proc`, `unavailable environment` and its GUIDE | about +110 | about +120 |
| **S5b Implement kind, hand advance, v11** | schema v11; `implement_step` (with its access values); `steps` (`IMPLEMENT`, `next_step`, `following`); `StepRules.excluded`; deletions in `unsafe_path`; `admit_next`; `prepare` `branch_moved`; `advance` in status and `tl step start`; GUIDE; `STEP_ONLY` | about +185 | about +300 |
| **S5c The round advances** | the advance phase, FIFO, `skip` words, `Action` `advance`; `test_advance` | about +35 | about +250 |

Order: S5a, S5e, S5b, S5c. S5b is reachable and useful alone (`tl step start` advances by hand); S5c makes it automatic.

**If S5e slips (proposed):** S5b may ship before S5e only for hand advances on scratch tasks, with `IMPLEMENT.access`
equal to plan's and the same input words, so the agent tries the commands and reports in `explanation` what could not
run. That is not "static analysis only": without the prepared venv only ruff can run (pyrefly and import-linter need the
project's environment, and `just check` starts with `install`). S5c (automatic advance of `auto` tasks) waits for S5e,
because 8.1 requires the agent to run its tests.

| Module | Now | After S5 |
|---|---|---|
| `admit` / `admit_chain` | 332 / new | about 270 / 145 |
| `steps` / `plan_step` / `implement_step` / `step_text` / `access` | 31 / 132 / new / new / new | 52 / 117 / 100 / 25 / 30 |
| `attempt` / `environment` (S5e: scratch folder and preparation) | 289 / new | 300 / 70 |
| `attempt_types` / `factory_schema` | 224 / 94 | 230 / 98 |
| `factory_commit` / `prepare` | 136 / 107 | 150 / 115 |
| `attempt_store` / `attempt_reads` | 312 / 194 | 316 / 196 |
| `attempt_status` / `operations` / `round` | 116 / 253 / 214 | 122 / 272 / 244 |
| `step_guide` / `tracker` / `task` | 97 / 54 / 47 | 104 / 56 / 49 |

Tests after: `test_admit` 456 (takeover tests stay where they are), `test_admit_chain` about 245, `test_round` 452 to
about 505, `test_operations` 577 to about 615, `test_steps` 56 to about 115, `test_answer_contract` 162 to about 210,
`test_attempt` plus about 80, `test_prepare` 234 to about 265, `test_commit_real` 163 to about 210, `test_advance` about
220, a new `test_environment` about 60. All under 800. No new function near 80 lines: the largest, `admit_next`'s
transaction, is about 40.

## 7. Risks, and what is deliberately not done

**Not done:** the checks step (after implement, its own design and table; it reruns tests outside the agent's control),
review, land (merge, completion, sync), questions and holds (`needs_owner` ends the step; tl-8bh9.6.1), automatic retry
of a failed implement (tl-7i9k.56.1), reading `setup` from the profile (roadmap B3; S5e uses the default `just install`
until it exists), network for the agent,
adding dependencies, per-step model/effort/minutes, executable files or symlinks, `.git*` files, a configurable step
order, tracker-visible step state, a label check on claimed work.

**Risks:**

- **Structural verification only.** An implement agent may answer `unchanged` or commit wrong code and still be
  `verified`; its report of a green test run is its own claim. Until the checks step exists, a `done` implement is
  "committed and published", never "works". The owner reads `task/<id>` before landing anything by hand.
- **The environment may not work as proposed.** Six unknowns (2.9) decide whether an offline rebuild and test run is
  possible in the Codex sandbox; the spike runs before S5b so a failure redesigns 2.8/2.9, not shipped code.
- **Preparation cost.** A per-slot `.venv` and uv cache cost disk per slot and time per attempt (counted against the
  one `--minutes`); a network failure during preparation leaves the attempt `admitted` (`unavailable environment`).
- **Test leftovers.** Tests writing outside `$TMPDIR` (into the slot) leave untracked files: a repeat (`uncommitted`)
  with the listing, at most twice, then a failed `done`.
- **Claim between steps.** Nothing renews the lease between plan end and the advance; a `bd reclaim` revert stops the
  task at `skip claim_lost`. Recovery: `tl step release --abandon` (flips the settled release's claim, returns it), then
  the task is ready again and restarts at plan (8.4).
- **A claimed task without the label keeps running** (8.6, by design): the owner stops one with
  `tl step release --abandon`, not by removing the label.
- **Branch rule D.** A slot adopted at a newer base than the plan's D may refuse `branch_diverged` for the implement
  step (.15 section 5). Slots adopted together keep passing.
- **Implement deadlines.** One `--minutes` for both steps, and implement now runs its tests; a plan-sized deadline may
  time out implement (`done`, failed). The owner raises `--minutes`.
- **Repository-wide leftovers.** Untracked files the agent's commands create outside `.gitignore` make the tree unclean:
  a repeat (`uncommitted`) with the listing, at most twice.
- **Discard.** v11 is the fourth discard of the smoke factory.db.

## 8. Decisions (owner, 2026-11-11)

Numbered as the questions were asked.

1. **Tests run inside the implement sandbox: decided, yes.** New tasks write new tests and running them is the only way
   to check they work, so the implement agent runs the project's tests in its slot, and the bare minimum static
   analysis (ruff, pyrefly, import-linter) too. Consequences in this design: implement has its own access (2.8), the
   factory prepares an environment per slot (2.9, slice S5e, after a spike), the input tells the agent to run both
   before answering and to name its new test files (2.2), it reports what it ran in `explanation` only (2.3, proposed),
   and the path cap is 96 (2.4, proposed).
2. **File scope: decided as recommended.** The whole repository: add, change and delete plain files, a capped number of
   at most 1 MiB each, except `.git*` paths (Git's own files, including `.gitignore` and `.github/`), `.beads/` (the
   tracker's) and executable files or symlinks (the factory's mode rule). A task needing those is not for the factory
   yet.
3. **A failing implement is retried like plan: decided as recommended.** A step repeats only when the agent left Git
   leftovers, at most 3 attempts; a rejected verdict, `incomplete`, `needs_owner` or a timeout ends the step as a
   failed `done` that the owner reads. Automatic retries of failed results belong to tl-7i9k.56.1.
4. **After an abandon the next start begins at plan, like a discard: decided.** An abandon is the owner deliberately
   giving up an attempt (`tl step release --abandon`): the slot is freed, the tracker claim is returned and the task
   becomes ready again; it is not a network or agent failure (3.1; glossary `abandon`).
5. **The plan is passed by reference: decided as recommended.** The input names `docs/design/<id>/plan.md`, which
   `prepare` guarantees is in the checkout at the plan commit.
6. **The label is checked only at ingestion: decided.** `auto` is checked only when the scheduler ingests a fresh task
   from the tracker (a round's ready read). After a task is claimed and in progress, no label check applies: not
   `tl step start TASK`, not a round's advance. The `in_progress` and `taskloop` assignee check stays on every advance.
   Ingestion (label, readiness, priority) and execution (claimed work) are separate concerns (section 1). The draft's
   `not_approved` word, `NextStepRequest.label` and `TaskInspection.labels` are dropped.
7. **Slot setup runs the repository's own `setup`, from the task branch: decided.** The factory prepares the slot
   before the agent starts, outside the sandbox and with network, with the command(s) named in the profile
   `.task-loop.json` at the ref under test (the task branch; at attempt 1, the branch at admission), following GitHub's
   model where a `push`/`pull_request` workflow is read at the commit under test. Default `just install` when the profile
   names none. This replaces the earlier proposal of "the repository's `just install` from main". The 2.9 unknowns and
   the S5e spike stay.
8. **The factory's checks run on the host: decided** (roadmap B4, not this slice). Before any review, with the agent's
   scrubbed environment and push bar; the owner accepts that agent-written code runs before anyone reads it ("the
   cheapest review: automatic checks").

## 9. Decided here (no owner question, open to veto; all proposed)

The dispositions `implemented`/`unchanged`/`incomplete`/`needs_owner` and their effects; the answer schema without
`plan_path`, with the test report in `explanation` only; no artifact (NULL blob); verified means the generic rules and
the clean tree; `excluded` as a `StepRules` field; `max_paths` 96; `attributes(rules, paths)`; deletions via
`unsafe_path` and B's tree; the `step_text` leaf; `admit_chain` holds repeat and next-step admission, fresh stays in
`admit`; `next_step(current, done)`; v11 columns and CHECKs as .15 3.4; `branch_moved` reused with its one meaning;
`advance`, `not_advanceable` and `environment` words; the advance phase uses the round's start snapshot; `Access` as a
`StepKind` field in a leaf `access.py`; a scratch folder outside the slot as implement's one writable root; preparation
in the entry before dispatch (the setup command itself is decided, 8.7); the four-slice split and its order; S5b before
S5e only for hand advances.

## 10. Not verified

- That `bd show --json` fills `assignee` and `status` for a claimed task (fields read in `beads_client` 0.2.0, not run).
- That Codex's strict response format accepts the implement schema (same pattern as plan's; not sent).
- That `git ls-files -o -i --exclude-standard -- <listed paths>` with many literal pathspecs stays within argument
  limits at 96 paths (likely; not measured).
- That the scripted-agent end-to-end test can run the attempt body synchronously over the fakes (fallback in section 5).
- That `stream_proc` offers a one-shot run with output and exit for the preparation (it is used for the entry and the
  agent; the one-shot shape is not read).
- Everything in 2.9's unknowns list: the S5e spike settles them.
- Line estimates: from the counter at this tree; S5a's diff is the first check.

## 11. As built: S5a (preparation, 2026-11-11)

Tracker tl-8bh9.4.3.1.16.1. Behavior-preserving: no schema, CLI word, exit code, JSON key, log line or agent-facing
byte changes (the S3 constants in `test_steps` still pass unchanged).

- **`admit_chain.py` (new, 85 code lines).** `PREVIOUS`, `RepeatRequest`, `_Lost`, and `ChainAdmission(connect, begin,
  files, clock)` with `admit_repeat` and `_takeover`, moved verbatim except for the calls into `admit`'s shared pieces.
  `composition.open_chain(database, artifacts)` wires it (its own `Store`, as `open_admission` has);
  `cli_composition._starting` passes it to `StepRepeat` instead of the `AttemptAdmission`. `repeat`, `composition`,
  `cli_composition` and five test files (`test_repeat`, `test_repeat_dispatch`, `test_slot_release`, `test_slot_lock`,
  `real/test_repeat_real`) changed imports and constructors only; the repeat tests construct `ChainAdmission` with its
  four ports (the `never` tracker/checkout/claim stubs they passed are gone). `operations` needed no change.
- **`admit`'s shared pieces, module functions (`admit` 332 to 272 code lines).** `deadline_refusal(clock, deadline)`
  (was `_deadline`), `open_store(connect)` (was `_open`), `free_slots(con, repo, repo_id, probe)` and `branched(repo,
  task_id, free)` (the free-slot observation and the branch rule, were `_observe`'s second half and `_branched`; the
  task-attempted check stays in `AttemptAdmission._observe`), `Free` (was `_Free`), `unheld`, `issued`, plus the
  existing `bound`, `as_count`, `why`. Chosen here (the plan was silent): the two SQL writes both admissions make are
  `admit` functions too, `insert_attempt(con, attempt)` and `issue(con, repo_id, slot, generation)` (the slot's
  counter), so each (verb, table) keeps one owner in `test_policy.WRITERS`; the reservation takeover (`UPDATE
  reservation`) moved with `_takeover`, so its owner there is now `admit_chain.py`. `admit_chain` imports only
  `deadline_refusal`, `open_store`, `insert_attempt`, `issue`, `as_count`, `why` and the result types; `free_slots`,
  `branched`, `unheld` and `issued` are public for `admit_next` (S5b) and used only by `admit` until then.
- **`step_text.py` (new leaf, 19 code lines).** `GIT_WRITES`, the one sentence about Git writes, and `feedback(opening,
  listing, instructions, task, nonce)`, the repeat frame (markers, `shown` listing, instructions, the task).
  `plan_step._closing_words` and `plan_step.feedback` call them (`plan_step` 132 to 119). No import-linter contract
  added for it (the plan names none; it is a leaf any kind may import).
- **`factory_commit.attributes(rules, paths)`.** The root's chain and the root (only when the root is not `""`), then
  each listed path's chain and the path, **skipping entries under the root** and each entry once, in order. The
  skipping is chosen here so the pathspecs for plan are byte-identical to before (section 2.4 says "meaning
  unchanged"; this makes the argv unchanged too). `refusal` passes `answer.paths`.
- **`TaskInspection.status` and `.assignee`** (required, the tracker's words as read; `tracker.inspect_task` maps
  `Bead.status` and `Bead.assignee`). `tl task show --json` printed `asdict(TaskInspection)`; it now leaves the two new
  keys out, so its JSON keys are unchanged. Nothing reads the two fields yet (`admit_next`, S5b).
- **Tests.** `test_steps`: the attributes case passes listed paths (plan with two listed paths equals the old list;
  root `""` gives only the listed paths' chains); `test_task_inspection`: one mapping case (status `in_progress`,
  assignee `taskloop`); `test_policy.WRITERS`: `UPDATE reservation` owned by `admit_chain.py`.

Gates: `just check` clean (ruff, pyrefly 0 errors, import-linter 8 contracts kept); `just test` 1380 passed. Code lines
(policy counter): `admit` 272 (-60), `admit_chain` 85, `step_text` 19, `plan_step` 119 (-13), `factory_commit` 144
(+5), `composition` 283 (+4), `task` 49 (+2), `tracker` 56 (+2), `cli` 142, `cli_composition` 208, `repeat` 142 (+1
each): +47 source code lines against the estimate of about +12 (the moved class carries its own imports, docstring and
constructor, and the two shared SQL writes became functions); tests +6. Live smoke not run (no behavior change).
