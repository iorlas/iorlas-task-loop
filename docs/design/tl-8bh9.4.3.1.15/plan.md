# Generalize the step machinery once: plan becomes the first step kind

Task: tl-8bh9.4.3.1.15 (proposed id; not in the tracker). Design, 2026-11-10, against HEAD 283ae2271. Docs only:
nothing is built or run. Commands run: source and doc reads, and the policy's own line counter
(`tests/rules/test_policy.code_lines`) over every `src` and `tests` file at HEAD. The working tree also holds another
agent's uncommitted deadline-renewal follow-up ([.14](../tl-8bh9.4.3.1.14/plan.md) section 16, about +40 lines in
`plan_launch`, `plan_store`, `plan_ops`, `plan_next`, `plan_repeat`, `cli_plan`, the two compositions); the counts below
are HEAD's and do not include it.

Read: CLAUDE.md, glossary, [.8.7](../tl-8bh9.8.7/plan.md), [coverage](../tl-8bh9/coverage.md),
[delivery/publication](../tl-8bh9.9/delivery-publication.md), [one-shot plan](../tl-8bh9.3.2.1/plan.md),
[.4.3.1](../tl-8bh9.4.3.1/plan.md) and slices [.1](../tl-8bh9.4.3.1.1/plan.md) to [.14](../tl-8bh9.4.3.1.14/plan.md);
all of `src/taskloop/`, `tests/`, `.importlinter`, `justfile`; installed `beads_client` 0.2.0 `records.py`.

## 1. The decision, and words

**Owner decision (given):** design the generalization first (what is step-generic, what is plan-specific), then rename
and generalize once, rather than copy the machinery per step. The next step is implement; checks, review and land
follow ([coverage](../tl-8bh9/coverage.md), sequence item 2). This document does not design the implement step: only
what the machinery must offer it.

**Owner answers to section 8 (2026-11-10), all four as recommended:**

1. `tl step` replaces `tl plan` in one cut, no alias; the cut is slice S4, not earlier.
2. A task moves to its next step automatically, after one `bd show` confirms it is still `in_progress`, claimed by
   taskloop and labelled `auto`; the claim is never retaken.
3. Tasks waiting for their next step go before new ready tasks, oldest first.
4. One `--model`/`--effort` pair for every step, for now.

- **step** (glossary): plan, implement, check, review, land. **attempt**: one try at a step. **step run** below is
  plain prose for attempts 1..3 of one step linked by repeats (`previous_attempt_id`); it is not a new entity.
- **step kind** (code name `StepKind`): the few values and functions that make a step the plan step and not the
  implement step. A code concept, not a product noun, registry or plugin; the set of kinds is a fixed tuple in code.
- **release** stays the verb for ending a slot reservation (a lease: the glossary keeps standard lease words). The
  glossary's **release** (a versioned distribution) never names a module or table here: the module is `slot_release`.
- **mutating step**: a step whose agent changes files the factory then commits (plan, implement). Delivery/publication
  item 2 already uses this distinction.

## 2. Inventory

Counts are physical lines / code lines (the policy's count: no blank, comment or docstring lines) at HEAD.
Class: **generic** (no plan meaning, at most a `plan_` name or "plan" in prose), **plan** (only meaningful for the plan
step), **mixed** (generic machinery with plan-specific pieces named in the next column).

### 2a. Source modules (37 files, 5,405 code lines)

| Module | Lines | Class | Plan-specific content | Target (section 3.6) |
|---|---|---|---|---|
| `plan_types.py` | 374/252 | mixed | `DISPOSITIONS`, `PLAN_NAME`, `plan_stage`, `Admission.rules`, `PlanAnswer`, `ANSWER_KEYS`, `decode_plan_answer`, the `plan_*` words in `Rule` | `attempt_types` + `plan_step` |
| `plan_schema.py` | 109/96 | mixed | tables named `plan_*`; columns `plan_commit`, `plan_path`, `plan_blob`; CHECK verified implies `plan_blob` | `factory_schema` |
| `plan_store.py` | 352/302 | mixed | `'planned'`/`'unchanged'` in three SQL fences; method `plan_commit` | `attempt_store` |
| `plan_reads.py` | 259/179 | generic | names only | `attempt_reads` |
| `plan_admit.py` | 443/338 | mixed | `task_text` closing words; `'planned','unchanged'` in `PREVIOUS` | `admit` (+ `admit_chain` in S5) |
| `plan.py` | 344/285 | mixed | `report` and `outcome` test `planned`/`unchanged`; default decoder `decode_plan_answer` | `attempt` |
| `plan_files.py` | 117/84 | mixed | `ANSWER_SCHEMA` (the plan answer's JSON schema) | `evidence_files`; schema to `plan_step` |
| `plan_commit.py` | 209/133 | mixed | `attributes()` hardcodes `docs/.gitattributes`, `docs/design/.gitattributes`; `unchanged`/`planned` tests | `factory_commit` |
| `plan_verify.py` | 279/188 | mixed | `_plan`/`_content`: the plan.md rule at X; `planned` in `judge` | `slot_state` + `verdict`; plan.md rule to `plan_step` |
| `plan_verifier.py` | 170/126 | mixed | `STAGED = ("planned", "unchanged")` | `verifier` |
| `plan_repeat.py` | 223/173 | mixed | `feedback` instructions name `plan.md` and "the plan folder" | `repeat`; instructions to `plan_step` |
| `plan_prepare.py` | 169/107 | generic | none (the task branch rule and the first attempt's branch take) | `prepare` |
| `plan_launch.py` | 203/143 | generic | none | `launch` |
| `plan_session.py` | 83/58 | generic | none | `session` |
| `plan_release.py` | 332/238 | generic | names only | `slot_release` |
| `plan_publish.py` | 266/193 | generic | refusal prose ("The plan is not verified yet") | `publish` |
| `plan_ops.py` | 531/370 | generic | prose and `tl plan` spellings | `operations` + `attempt_status` (S4) |
| `plan_next.py` | 302/220 | generic | "plan step" in prose | `round` |
| `plan_rounds.py` | 174/108 | generic | names only | `rounds` |
| `plan_data.py` | 121/91 | generic | names only | `result_data` |
| `attempt_entry.py` | 295/216 | generic | prose: "verified plan" | stays |
| `cli_plan.py` | 437/379 | mixed | the `plan` noun, `PLAN_ONLY`, plan wording in `GUIDE` (section 2d) | `cli_step` + `cli_guide` (S4) |
| `cli.py` | 111/98 | mixed | root description quotes `PLAN_ONLY` | stays |
| `cli_composition.py` | 274/205 | generic | `open_plan_*` names | stays, `open_step_*` |
| `composition.py` | 386/249 | generic | `open_plan_attempts`/`open_plan_*` names; Codex credentials are agent-generic | stays |
| `slots.py` 197/142, `slot_lock.py` 94/46, `claim_lease.py` 101/62, `selection.py` 76/49, `tracker.py` 79/51, `task.py` 67/47, `repo.py` 35/21, `machine_config.py` 149/101, `rounds_lock.py` 43/18, `interrupts.py` 59/35, `__main__` 5/2, `__init__` 1/0 | | generic | none (prose mentions `tl plan`) | stay |

Plan-specific code in total is small: about 110 code lines (the answer contract and decoder, the schema, the input's
closing words, the plan.md rule at X, the repeat instructions). The rest is the step machinery under a plan name.

### 2b. factory.db tables (schema v8)

| Table | Class | Plan-specific columns or checks |
|---|---|---|
| `slot`, `reservation` | generic | none |
| `plan_attempt` | generic | name; `plan_commit` (X, the commit the step ends at) |
| `plan_execution` | mixed | `plan_path` (validated by the decoder, never read for control); `disposition` words used in fences |
| `plan_verification` | mixed | `plan_blob`; `CHECK((verdict='verified') = (plan_blob IS NOT NULL))` |
| `plan_release` | generic | name |
| `published_branch` | generic | none |

### 2c. CLI verbs

| Verb | Class |
|---|---|
| `tl repo inspect`, `tl task show`, `tl config show`, `tl slot adopt` | generic |
| `tl plan start/show/list/verify/release/publish/next/rounds` | generic operations under the `plan` noun: each follows a task's current attempt, whatever its step |

### 2d. GUIDE keys, help strings and log words

- **GUIDE (42 keys in `cli_plan.py`)**: every key names a generic state or refusal. Plan wording is in the text only:
  `start` ("plan the task again"), `publish` ("The plan is verified"), `done` ("whether the plan was verified"),
  `failed` ("without a verified plan"), `stuck:expired_admitted` ("plans it again"), `not_verified` ("Only a verified
  plan"), `unsettled` ("the stage"). The other 35 are generic apart from the `tl plan` spelling. `PLAN_ONLY`, `HELD`,
  `ROUNDS`, `ABANDON`, `PUBLISH` and `discard()` likewise.
- **`entry.log`**: one line of fixed words, `<status> <reason> [publish= then=] verify= claim= release= [branch=]`:
  generic. Verdict words `verified`, `reused`, `rejected:<rule>` are generic except the rules `plan_missing`,
  `plan_encoding`, `plan_empty`, `plan_size`.
- **`rounds.log`**: `<time> <backlog> <task> <action> <words> [<attempt>]`, actions `start relaunch repeat verify
  publish report skip`, `round moves=N [stopped=W]`, `rounds started/stopped`: generic.

### 2e. Test files (38 files, 8,021 code lines)

| File | Lines | Class |
|---|---|---|
| `tests/plan/test_answer_contract.py` | 202/160 | plan (decoder and schema) |
| `tests/plan/test_verify.py` | 683/531 | mixed (generic chain verdict and slot pointer; plan.md content rules) |
| `tests/plan/test_repeat.py` | 533/421 | mixed (generic repeat; plan feedback text) |
| `tests/plan/test_admit.py` | 557/455 | mixed (generic admission; `task_text` words) |
| `tests/cli/test_plan_cli.py` | 608/510 | generic behaviors under the `tl plan` spelling |
| `tests/plan/test_attempt.py` 784/622, `test_ops.py` 678/542, `test_next.py` 539/427, `test_repeat_run.py` 485/379, `test_entry.py` 428/333, `test_publish.py` 386/286, `test_release.py` 353/271, `test_prepare.py` 316/234, `test_rounds.py` 274/200, `test_slots.py` 260/201, `test_launch.py` 251/196, `conftest.py` 210/155, `test_credentials.py` 200/170, `test_slot_lock.py` 185/137, `test_entry_store.py` 145/113, `test_dispatch_slot.py` 140/112, `test_claim_lease.py` 125/92, `test_selection.py` 105/71, `test_rounds_lock.py` 30/21, `test_interrupts.py` 16/11 | | generic (plan answers appear only as data) |
| `tests/plan/real/test_commit_real.py` 212/163, `test_publish_real.py` 185/146, `test_release_real.py` 134/99, `test_repeat_real.py` 116/95, `test_prepare_real.py` 82/65 | | generic (plan paths as data) |
| `tests/cli/test_cli.py` 72/56, `test_config.py` 159/133, `test_repo*.py`, `test_task*.py`; `tests/rules/test_isolation.py` 109/90, `test_policy.py` 209/159 | | generic (`test_policy` and `.importlinter` name modules and tables) |

Raw SQL in tests names the `plan_*` tables or columns about 230 times across 25 files: the schema slice edits them.

## 3. Target design

### 3.1 What a step kind is

One frozen dataclass per step, holding exactly what plan and implement differ in. Everything else is the shared
machinery: admission, launch, entry, session, capture, factory commit, chain verdict, clean-tree check, repeat,
release, publish, status, rounds.

```python
type Step = Literal["plan"]            # S5 adds "implement"
type Effect = Literal["commit", "keep", "none"]

@dataclass(frozen=True)
class Answer:                          # replaces PlanAnswer; the decoder's one result
    disposition: str                   # the step's own word, for display (`planned`)
    effect: Effect                     # commit the listed paths / B stands / nothing to verify
    paths: tuple[str, ...]
    message: str | None
    explanation: str

@dataclass(frozen=True)
class StepKind:
    step: Step
    rules: Callable[[str], StepRules]                     # task id -> root, caps, deletions
    input_text: Callable[[TaskInspection, StepRules], str] # the task prose plus the step's closing words
    answer_schema: Mapping[str, object]                    # the strict JSON schema Codex forwards
    decode: Callable[[object, StepRules], Answer]          # every bound and cross-field rule; ValueError otherwise
    artifact: Callable[[Tree, StepRules], Rejected | str | None]  # the step's own rule at X: broken rule, blob, or nothing
    feedback: Feedback  # a repeat's complete input: (found, rules, number, task, nonce, *, unrecorded) -> str
```

As built in S3 (section 15): `artifact` returns `Rejected` (not a bare `Rule`, which is also a `str`) and `feedback` is
`plan_step.feedback`'s full signature as a Protocol (the opening per reason and the instructions are the kind's words).

`steps.py` owns the kinds: `PLAN = StepKind("plan", ...)`, `STEPS: tuple[StepKind, ...] = (PLAN,)` (the fixed order),
`kind(step) -> StepKind` (a `match`, no lookup table of strings to callables supplied from elsewhere), `RULES` (the
generic rules plus every kind's artifact rules, for the stored-verdict reader). `plan_step.py` holds the plan's values:
the four dispositions mapped to effects (`planned` commit, `unchanged` keep, `incomplete` and `needs_owner` none), the
plan answer schema (unchanged bytes), the decoder (unchanged rules, plus the effect), `task_text`'s closing words, the
plan.md rule (`_plan`/`_content`, returning the blob), and the repeat instructions. **Only `steps.py` imports
`plan_step`** (an import-linter contract), so no generic module can grow a plan branch again.

What each field answers, from the brief:

| Concern | Where it lives |
|---|---|
| prompt / task text | `input_text`; the admitted input stays a stored file under its digest |
| output schema / answer decode | `answer_schema` (written to `schema.json` by `evidence_files.prepare`) and `decode` |
| what "verified" means | generic: the chain rules (`commit_absent`, `not_descendant`, `chain_length`, `paths`, `mode`, `file_size`, `nothing_written`) and the clean tree at X; per kind: `artifact` at X (plan: plan.md exists, mode 100644, UTF-8, not blank, at most 1 MiB; a kind with no artifact returns None) |
| what is committed / published | generic: the factory commits exactly the listed paths within `StepRules`; a verified X is pushed to `task/<id>` (delivery/publication item 2: every mutating step). Not a field |
| repeat policy | generic: `REPEATABLE` leftovers, `ATTEMPTS = 3` per step run, fresh session; per kind only the `feedback` instructions |
| access / sandbox | generic for now: `SANDBOX` and `CODEX_ACCESS` (no network, no `/tmp`, never escalate). Not a field until a kind needs other values (section 5) |

`StepRules` (renamed from `StageRules`; the glossary retires "stage") keeps its four fields: `root`, `max_paths`,
`file_cap`, `deletions`. `attributes()` becomes the `.gitattributes` of every folder on the way to `root`, plus `root`:
for the plan root that is exactly today's list.

### 3.2 Which step a task is in next: derived from factory.db, owned by `steps.py`

**Decided.** The step is local execution state (glossary storage table: factory.db owns steps and attempts). The
tracker never stores it, no label or metadata carries it, and no log is read for it.

- A task's attempt is **done** when its verdict is `verified` (new or `reused`), its release is settled (`slot_release`
  row, `abandoned=0`) and its commit is recorded published (`published_branch`). Delivery/publication: do not advance
  to another mutating step until the checkpoint is published.
- `steps.next_step(done, current)` is pure: given the steps that have a done attempt for the task and the task's
  current attempt (highest `seq`), it answers the step to admit next, or None. No attempt, or a current attempt that
  was abandoned with its claim returned: the step after the last done step (the first step when none is done). A
  current attempt that is done: the following step in `STEPS`, or None when it was the last built step. Anything else:
  None (the current attempt is still in its step; its own `Next` word applies).
- Admission is the only writer and re-derives under its write lock; the status read and the round call the same
  function. One owner of the fact, one function, every consumer.
- **After a deliberate factory.db discard** the derivation restarts at the first step. The plan agent reads the
  committed plan and answers `unchanged` (`reused`), the publish is an up-to-date push, and the task advances: normal
  reevaluation, as CLAUDE.md requires, at the cost of one short plan attempt. No history reconstruction.

### 3.3 How attempts of different steps chain on one task

| Column | Meaning (existing unless marked) |
|---|---|
| `seq` | the attempt's order among all its task's attempts, every step and every fresh start |
| `step` (new, S2) | which step the attempt belongs to |
| `number`, `previous_attempt_id`, `repeat_reason` | the attempt's place in its step run; a repeat links to the attempt it repeats, never across steps |
| `base_commit` B, `end_commit` X (renamed from `plan_commit`) | where the attempt started and ended |
| `after_commit` (new, S5) | for attempt 1 of a later step only: the previous step's done X, read under admission's lock |

The current attempt stays "highest `seq`" (`attempt_of`, unchanged), so `show/verify/release/publish` keep following the
task's current attempt whatever its step. The chain verdict stays per step run: B1 is the step run's attempt 1 B, so a
later step is judged only on its own commits. Three admission paths, one module family:

| Path | When | Claim | Slot |
|---|---|---|---|
| fresh (`admit`, exists) | no attempt, or the current one abandoned with its claim returned | taken (`Bd.claim`) | a free slot, branch rule |
| repeat (`admit_repeat`, exists) | the current attempt captured with repeatable leftovers | copied | the same reservation, taken over |
| next step (`admit_next`, S5) | the current attempt is done and a following step exists | kept from the previous step (never retaken; Q2) | a free slot, branch rule |

A next-step attempt copies `tracker_root`, takes `model`/`effort` from the request (Q4), stores `after_commit`, and
its preparation refuses `branch_moved` when the local `task/<id>` it checks out does not contain `after_commit`
(someone moved the branch; the agent must start from the published previous step). The first beat of the entry's
claim keep-alive still re-arms a lapsed lease or refuses `claim_lost` before the agent runs (.9 section 5), as for
every step.

### 3.4 Schema

Direct version bumps, no compatibility: `current()` refuses the older file (`refused:schema`), the owner discards
factory.db (the existing discard runbook), nothing migrates. Before a bump the owner finishes or abandons the attempts
in flight.

- **v9 (S2): generic names and the step column.** `plan_attempt` to `attempt`, `plan_execution` to `execution`,
  `plan_verification` to `verification`, `plan_release` to `slot_release`; `published_branch`, `slot`, `reservation`
  keep their names. `plan_commit` to `end_commit`, `plan_blob` to `blob` (nullable: a kind without an artifact stores
  none; the CHECK tying it to `verified` goes, the `reason` CHECK stays). `attempt.step TEXT NOT NULL CHECK(step IN
  ('plan'))`. `execution.effect TEXT CHECK(effect IN ('commit','keep','none'))`, written by `answer()` with the
  disposition; every fence that today names `'planned'`/`'unchanged'` (the end-commit write, the verdict insert, the
  repeat's `PREVIOUS`) reads `effect` instead. `plan_path` is dropped (the decoder already validated it; nothing reads
  it). The `UNIQUE(adapter, backlog, task_id, seq)` and every other constraint stay.
- **v10 (C): schema cleanup** (section 13): `execution.publication` to `session_state`, `slot.cwd` to `path`;
  `reservation.cwd`, `slot_release.abandoned`, `execution.tokens_known` and `cumulative_known` dropped.
- **v11 (S5): a second step.** `step IN ('plan','implement')`; `attempt.after_commit TEXT` with
  `CHECK(after_commit IS NULL OR length(after_commit) IN (40,64))` and `CHECK((number = 1 AND step <> 'plan') =
  (after_commit IS NOT NULL))`. Each later step kind (review) is another bump of this kind; that is accepted, not
  avoided with an unchecked column.

No other table gains a `step` column: execution, verification, release and publication rows are one per attempt and
join to it. Reservations and slots know nothing of steps.

### 3.5 Release and publish per step

Unchanged in meaning, generic in name. Release (settled) parks the slot at the attempt's D and keeps the claim: a
verified step result is not task completion, land is. Abandon returns the claim. Publish pushes the attempt's verified
X to origin's `task/<id>`, never forced, and records it; it runs per attempt, so every mutating step publishes its own
tip (delivery/publication item 2). A `reused`/`keep` result pushes the same X again (an up-to-date push records it).
Checks, review and land are not mutating agent steps in this machinery (section 5).

### 3.6 Naming

No generic module keeps a `plan_` prefix; only `plan_step.py` means the plan step. Renames (S1 unless noted):

| Old | New | Classes and functions |
|---|---|---|
| `plan_schema` | `factory_schema` | |
| `plan_types` | `attempt_types` (+ `plan_step` in S1, + `steps` in S3) | `StageRules` to `StepRules`, `StepAttempt` to `ChainLink`, `PendingPlanResult` to `PendingResult`, `PlanDecoder` to `Decoder`; `PlanAnswer` becomes `Answer` (S3) |
| `plan_reads`, `plan_store` | `attempt_reads`, `attempt_store` | `PlanReads`/`PlanStore` to `AttemptReads`/`AttemptStore`; `plan_commit()` to `end_commit()` (S2) |
| `plan_admit` | `admit` (+ `admit_chain` in S5: repeat takeover and next step) | `PlanAdmission` to `AttemptAdmission` |
| `plan` | `attempt` | `PlanAttempts` to `Attempts` |
| `plan_launch`, `plan_session`, `plan_prepare` | `launch`, `session`, `prepare` | |
| `plan_files` | `evidence_files` | `PlanFiles` to `EvidenceFiles` |
| `plan_commit` | `factory_commit` | |
| `plan_verify` | `slot_state` (pointer, observation, listing, staged) + `verdict` (`judge` and the chain) | |
| `plan_verifier` | `verifier` | `PlanVerifier` to `Verifier` |
| `plan_release`, `plan_publish`, `plan_repeat` | `slot_release`, `publish`, `repeat` | `PlanRelease` to `SlotRelease`, `PlanPublish` to `BranchPublish`, `PlanRepeat` to `StepRepeat` |
| `plan_ops` | `operations` (+ `attempt_status` in S4) | |
| `plan_next`, `plan_rounds`, `plan_data` | `round`, `rounds`, `result_data` | |
| `cli_plan` | `cli_step` + `cli_guide` (S4) | `open_plan_*` to `open_*` (S1) |
| `tests/plan/` | `tests/steps/` (S1; `justfile` follows) | `test_plan_cli.py` to `test_step_cli.py` (S4) |

### 3.7 CLI shape

**Decided (Q1, owner): `tl step <verb>` replaces `tl plan <verb>` in one cut, no alias.** The verbs and flags stay:
`start show list verify release publish next rounds`. The person never names the step: `tl step start TASK` relaunches,
repeats, advances or freshly admits whatever the task's current attempt and `steps.next_step` call for; `show` and
`list` print a `Step:` line and a `step` column; `--json` rows gain `"step"`. The help scope string replaces
`PLAN_ONLY`: "steps built: plan; publishes task/<id>; no merge or land" (S5: "plan, implement"). `tl plan` then exits 2
like any unknown command. The [.8.7](../tl-8bh9.8.7/plan.md) exception paragraph is rewritten for `tl step` in the
same slice. Until that slice (S1 to S3) `tl plan ...` works exactly as today.

`rounds.log` move lines gain the step word after the task (`<time> <backlog> <task> <step> <action> ...`). It is
evidence for a person, never read back; the live-smoke runbook's greps follow. `entry.log` is per attempt and does not
change.

### 3.8 Rounds and scheduling

A round today: settle each current attempt, admit ready tasks, publish. With S5 it becomes **settle, advance, admit,
publish** (Q3):

- `Next` gains `advance`: the current attempt is done and a following step exists (`done` stays for a failed result
  and for the last built step).
- **advance**: each `advance` attempt, oldest settled release first (FIFO, no tracker priority read), gets one
  `tl step start` through the same operation; the free-slot gate and the stop words are admission's. One tracker read
  per candidate (`show`) confirms it may continue (Q2): status `in_progress`, assignee `taskloop`, the round's approval
  label still present. Otherwise a `skip` move with `claim_lost` or `not_approved`, nothing written. That read also
  supplies the task prose for the next step's input. `TaskInspection` gains `status`, `assignee`, `labels`, all
  already on `beads_client.Bead`.
- **admit**: unchanged. A ready task with any attempt is still skipped (`attempted`/`abandoned`); claimed tasks are not
  in the ready set anyway, so advancing never comes from the tracker's ready list.
- One `--model`/`--effort`/`--minutes` per request applies to every step (Q4).

### 3.9 Decided in this document (no owner question)

Names in 3.6; `release` kept in its lease sense; the step stored only in factory.db; discard restarts at the first
step; the stored `effect` instead of disposition words in SQL; `plan_path` dropped; `blob` nullable; the `StepKind`
fields in 3.1 and nothing more; two step version bumps (v9, v11; v10 is the C cleanup); the step order a fixed tuple in
code, never configuration.

## 4. Migration: bounded slices

Each slice lands green with `just check` and `just test`, reviewed independently, one source writer at a time.
**S0, precondition:** the uncommitted deadline-renewal follow-up lands first; S1 renames the files it touches.

| Slice | What | Schema | CLI / words | Size |
|---|---|---|---|---|
| **S1 Renames and moves** | Every rename in 3.6 except S4's; `plan_types` split into `attempt_types` and `plan_step` (moved verbatim: dispositions, `PLAN_NAME`, rules, decoder, `ANSWER_SCHEMA` from `plan_files`, `task_text`'s closing words, the plan.md rule from `plan_verify`, the repeat instructions); `tests/plan` to `tests/steps`; `.importlinter`, `test_policy` (`WRITERS`, `git_writers`), `justfile` updated | none (tables keep `plan_*` names for one slice) | none: `tl plan` and every word unchanged | about +20 code lines (new module headers); about 25 source and 35 test files touched, imports and names only |
| **S2 factory.db v9** | 3.4 v9: table and column renames, `step` (plan), `effect`, drop `plan_path`, nullable `blob`; `end_commit()`; fences on `effect`; `AttemptRow`/`AttemptRecord`/`Admission` carry `step` | v8 to v9, discard | none | about +15 source; about 230 test SQL references edited |
| **S3 The step port** | `steps.py` (`StepKind`, `PLAN`, `STEPS`, `kind`, `RULES`); `Answer` with `effect`; the five consumers (`admit` input text, `evidence_files.prepare` schema, `attempt._validate`, `verifier`/`verdict` artifact, `repeat` feedback) call `kind(admission.step)`; `attributes()` derived from the root; import-linter: only `steps` imports `plan_step` | none | none: identical input text and schema bytes | about +45 source |
| **S4 CLI cut (Q1)** | `tl step` replaces `tl plan`; `cli_guide.py` takes `GUIDE`, `discard`, help strings (generic wording); `attempt_status.py` takes `show_attempt`, `list_attempts` and `next_action` from `operations`; `step` in rows, JSON and `rounds.log`; .8.7 exception and live-smoke runbook updated | none | the cut | about +30 source |
| **S5 Step sequencing** (lands with the implement kind) | `steps.next_step`; `admit_next` in `admit_chain` (with the repeat takeover moved there); the `after_commit` check in `prepare`; `advance` in status, `tl step start` and the round (3.8); `TaskInspection` status, assignee, labels; the implement `StepKind` per its own design | v10 to v11, discard | `advance` word and GUIDE entry; scope string names implement | about +250 source, +350 test |

**What stays plan-only after S5:** `plan_step.py` (its answer contract, words, input closing words, plan.md rule,
repeat instructions) and the plan.md artifact rules' verdict words. Nothing else names the plan step.

Ordering rationale: pure renames first, so S2's schema diff and S3's behavior-preserving port read cleanly; the CLI
cut waits for the owner's answer but must precede S5, because with two steps `tl plan start` would start an implement
step. S1 to S4 change no behavior a person sees except S4's spelling.

## 5. Not generalized yet, and risks

**Not generalized (only the implement step's needs are covered):**

- **Checks** (a non-agent step with individual check attempts, check keys, passes and reuse), and **land** (merge,
  final squash, task completion, sync) are not step kinds of this machinery: no session, worker, answer or factory
  commit. They get their own designs and tables; attempt rows are not made nullable for them now.
- **Review**: an agent step, but whether it commits (delivery/publication item 3 says checks/review do not commit to
  record results; .7 section 14 floated committed review reports) is review's own design. No read-only step mode now.
- **Repair** (returning to implement after failed checks or review): the retry owner tl-7i9k.56.1, later.
- **Per-step access/sandbox**, per-step caps beyond `StepRules`, per-step deadlines, per-step harness, multiple commit
  groups per answer, factory reverts, session resume, a configurable step order, tracker-visible step state.

**Risks:**

- **Implement's rules will differ from the plan's in ways the plan never met.** With `root=""` the ignored-file check
  (`dirty(..., ignored_under=attributes(rules))`) would report every ignored file in the repository (`__pycache__`,
  `.pytest_cache`, `.venv`) and repeat the step; the `.git*` rule refuses `.gitignore` and `.github/`; 32 paths may be
  too few; the sandbox excludes `/tmp`, which test runs use. These are implement's decisions; when it makes them,
  `StepRules` (ignored-file scope, `.git*` policy) and possibly an `access` field grow in S5, not before.
- **The branch rule's D for a later step.** Admission accepts a slot only when every existing `task/<id>` tip contains
  the slot's parked HEAD D. Slots park back at their own D, so slots adopted at one base keep passing; slots adopted at
  different bases may refuse `branch_diverged` for a later step. Stated, not changed; `after_commit` covers the real
  requirement (start from the published previous step).
- **The claim between steps.** Nothing renews the lease between steps (.9 section 5): a `bd reclaim` can revert it
  minutes after a step ends; the next step then stops at `claim_lost` (Q2), as the plan step does today.
- **Rename churn.** S1 touches most files: it must run with no other source writer in the tree, right after S0.
  Proof of no behavior change: the existing suites, unchanged except imports and names.
- **Caps.** `cli_plan` is at 379/400 code lines, `plan_ops` 370, `plan_admit` 338, `plan_store` 302: S4 and S5 split
  them (section 7) before they grow. `test_attempt.py` is at 622/800.
- **Three discards** (v9, v10, v11) of the owner's smoke factory.db; in-flight attempts must be finished or abandoned first.

## 6. Tests and smoke

- **S1:** no new tests. The existing suites, with only import and name edits, are the proof; the reviewer reads
  `git diff -M` and checks that no logic line changed. `test_policy` and `.importlinter` follow the new names.
- **S2:** the existing tests with their SQL renamed. New, only for new behavior: `answer()` stores `effect`, and the
  end-commit and verdict fences accept `commit`/`keep` and refuse `none` (one parametrized test replacing the
  disposition-word fixtures it supersedes); a v8 factory.db is refused `schema` (reuse the existing refusal test).
  **Live smoke after S2 (owner-run, scratch repo and tracker):** the runbook's plan path end to end (start, show,
  verify, release, publish), one repeat with leftovers, one abandon and fresh start, and one `tl plan next` round;
  first, the old v8 file refused `schema`. The runbook's `sqlite3` lines use the new table names.
- **S3:** `tests/steps/test_steps.py`: the plan kind's input text for a fixed task, its `schema.json` bytes and two repeat
  inputs equal constants recorded before the port, at `ac11e63e4` (the agent-facing contract did not move); the
  import-linter contract. The decoder tests in `test_answer_contract.py` call it through `kind("plan")`. As built:
  section 15.
- **S4:** CLI tests respelled `tl step` (`test_step_cli.py`); `tl plan` exits 2; `step` in JSON and human rows. A short
  owner smoke: `tl step --help`, one `tl step next` round.
- **S5:** new behavior tests: `next_step` over its cases (pure table test); `admit_next` (no claim call, root copied,
  `after_commit` stored, refused when the previous attempt is not done, unpublished, abandoned or superseded, two
  concurrent advances admit one); `prepare` refuses `branch_moved` without `after_commit`; status `advance`; a round
  advances FIFO before admitting a ready task and skips `claim_lost`/`not_approved`. Live smoke: plan then implement
  on a scratch task, both published to scratch `remote.git`. No agent runs whole-suite or live tests.

## 7. Module plan (code lines; caps 400 per file, 80 per function, 800 per test file)

| Module after S5 | Estimate | From |
|---|---|---|
| `factory_schema` | 105 | `plan_schema` 96 |
| `attempt_types` | 210 | `plan_types` 252 minus plan content |
| `plan_step` | 115 | moved plan content |
| `steps` | 85 | new (S3 45, S5 +40) |
| `attempt_reads` / `attempt_store` | 200 / 305 | 179 / 302 |
| `admit` / `admit_chain` | 285 / 145 | `plan_admit` 338 (repeat takeover moves out) + next step |
| `attempt` / `session` / `launch` / `attempt_entry` | 280 / 58 / 143 / 216 | 285 / 58 / 143 / 216 |
| `prepare` / `evidence_files` / `factory_commit` | 115 / 72 / 133 | 107 / 84 / 133 |
| `slot_state` / `verdict` / `verifier` | 128 / 62 / 126 | `plan_verify` 188 (plan.md rule out), 126 |
| `slot_release` / `publish` / `repeat` | 238 / 193 / 160 | 238 / 193 / 173 |
| `operations` / `attempt_status` | 235 / 180 | `plan_ops` 370 |
| `round` / `rounds` / `result_data` | 265 / 108 / 96 | 220 / 108 / 91 |
| `cli_step` / `cli_guide` | 295 / 105 | `cli_plan` 379 |
| `cli_composition` / `composition` / `cli` | 210 / 252 / 98 | 205 / 249 / 98 |
| `task` / `tracker` | 50 / 53 | 47 / 51 |

Unchanged: `slots`, `slot_lock`, `claim_lease`, `selection`, `repo`, `machine_config`, `rounds_lock`, `interrupts`.
New test files: `test_steps.py` (about 70), `test_advance.py` (about 300); `test_admit.py` (455) and `test_next.py`
(427) take S5's smaller additions. No function nears 80 lines; the largest new one, the round's advance phase, is
about 30.

## 8. Owner questions

**Answered 2026-11-10: yes to all four, as recommended** (recorded in section 1). Q1's cut is S4; Q2 to Q4 are S5.

1. **The command noun: `tl step` instead of `tl plan`, in one cut, no alias?** Today every verb is `tl plan ...`. With
   implement added, `tl plan start` would also start implementation steps, which reads wrong; a second noun per step
   (`tl implement start`) would duplicate every verb. With `tl step`, the factory picks the task's next step from its
   own records and the person only names the task. **Recommendation: yes, `tl step`, landing before implement (S4);
   `tl plan` stops working at that commit.**
2. **May a task move from one step to the next by itself?** When the plan is verified, released and published, the
   next round (or `tl step start`) would start implementation without asking again. Before it does, it reads the task
   once: still `in_progress`, still claimed by taskloop, still carrying the approval label (`auto`). If the claim was
   lost (for example `bd reclaim` reverted it during the idle gap) or the label was removed, it does not continue and
   never retakes the claim; removing the label is then the owner's way to stop a task between steps.
   **Recommendation: yes, automatic, with that check; no retaking.**
3. **Finish started tasks before starting new ones?** When a slot frees, a round could give it to a task waiting for
   its next step or to a new ready task. **Recommendation: tasks waiting for their next step first, oldest first;
   new ready tasks only with slots left over** (fewer half-done tasks; the priority order still decides among new ones).
4. **One model and effort for every step, for now?** `tl step rounds --model --effort` would use the same pair for
   planning and implementing. Separate pairs per step mean new flags or machine-config keys. **Recommendation: one pair
   now; add per-step settings only when implement's design or a smoke shows the plan model is wrong for it.**

## 9. Not verified

- The rename and split sizes are estimates from the line counter; S1's real diff is the check.
- `beads_client.Bead` has `status`, `assignee` and `labels` (read in the installed 0.2.0 `records.py`); that `bd show`
  fills `labels` for a claimed task was not run.
- That an up-to-date push of the same X (a `keep` result after a discard) returns `Pushed` is what the plan step's
  `reused` path relies on today; not re-measured here.
- The implement step's rules, prompt, answer contract and access are not designed here; section 5 lists what its design
  must decide before S5.

## 10. As built

### S1 renames and moves (2026-11-10)

Names and imports only: no schema, CLI, word or behavior change, no new behavior test. Files moved with `git mv`.
Earlier slice documents keep the old names as their history; this table maps them.

| Old | New |
|---|---|
| `plan_schema.py` | `factory_schema.py` |
| `plan_types.py` | `attempt_types.py`; plan content to `plan_step.py` (below) |
| `plan_reads.py`, `plan_store.py` | `attempt_reads.py`, `attempt_store.py` |
| `plan_admit.py` | `admit.py` |
| `plan.py` | `attempt.py` |
| `plan_launch.py`, `plan_session.py`, `plan_prepare.py` | `launch.py`, `session.py`, `prepare.py` |
| `plan_files.py` | `evidence_files.py` (`ANSWER_SCHEMA` to `plan_step.py`) |
| `plan_commit.py` | `factory_commit.py` |
| `plan_verify.py` | `slot_state.py` (pointer, observation, listing, staged) + `verdict.py` (`judge`, the chain); the plan.md rule to `plan_step.py` |
| `plan_verifier.py` | `verifier.py` |
| `plan_release.py`, `plan_publish.py`, `plan_repeat.py` | `slot_release.py`, `publish.py`, `repeat.py` |
| `plan_ops.py` | `operations.py` |
| `plan_next.py`, `plan_rounds.py`, `plan_data.py` | `round.py`, `rounds.py`, `result_data.py` |
| `tests/plan/` | `tests/steps/` (`justfile` and `pyproject.toml` `testpaths` follow) |
| `StageRules`, `StepAttempt`, `PendingPlanResult`, `PlanDecoder` | `StepRules`, `ChainLink`, `PendingResult`, `Decoder` |
| `PlanReads`, `PlanStore`, `PlanAdmission`, `PlanAttempts`, `PlanFiles` | `AttemptReads`, `AttemptStore`, `AttemptAdmission`, `Attempts`, `EvidenceFiles` |
| `PlanVerifier`, `PlanRelease`, `PlanPublish`, `PlanRepeat` | `Verifier`, `SlotRelease`, `BranchPublish`, `StepRepeat` |
| `open_plan_*` (`admission`, `attempts`, `next`, `publish`, `reads`, `release`, `rounds`, `start`, `verifier`, `verify`) | `open_*` |

`plan_step.py` holds, moved verbatim: `DISPOSITIONS`, `PLAN_NAME`, `ANSWER_KEYS`, `plan_stage`, the decoder
(`decode_plan_answer` with `_message`, `_paths`), `ANSWER_SCHEMA` and its comment, the input's closing words
(`closing_words(rules)`, called by `admit.task_text`), the repeat's `OPENING` and instructions (`repeat_instructions`,
called by `repeat.feedback`), and the plan.md rule (`plan_rule`, was `plan_verify._plan`/`_content`, now computing the
plan path from the rules itself; called by `verdict.judge`).

Deviations from section 3.6 and S1, each to avoid an import cycle (`plan_step` imports `attempt_types`):

- `PlanAnswer` and `Decoder` stay in `attempt_types` (the generic consumers read the answer; S3 replaces `PlanAnswer`
  with `Answer` there).
- `Admission.rules` (it called `plan_stage`) is removed; its six call sites in `attempt`, `factory_commit` (3),
  `verifier` and `repeat` call `plan_stage(admission.task.task_id)`, the same value. S3 turns them into
  `kind(admission.step).rules(...)`.
- `MODE` and `Unreadable` (used by both the chain and the plan.md rule) move to `attempt_types`.
- The test fake `Verifier` in `tests/steps/test_operations.py` is now `FakeVerifier`; `tests/steps/test_slot_lock.py` imports
  the `verifier` module as `verifier_module` (its helper function is named `verifier`).
- `plan_stage` keeps its name (not in the 3.6 table). Table and column names (`plan_attempt`, `plan_commit`,
  `plan_release`, ...) and their mentions in prose wait for S2.

Gates: `just check` clean (ruff, pyrefly 0 errors, import-linter 6 contracts kept); `just test` 1229 passed. The two
more than 1227 are `test_source_policy`'s parametrized cases for the two new source files (`plan_step.py`,
`verdict.py`); no behavior test was added or removed. Code lines after: `attempt_types` 223, `plan_step` 109,
`slot_state` 116, `verdict` 52, `evidence_files` 72, `admit` 331, `repeat` 158, `operations` 382.

## 11. As built: S2 factory.db v9 (2026-11-11)

Schema version 9; no migration: `current()` refuses a v8 file (`refused:schema`), the owner discards factory.db.

| v8 | v9 |
|---|---|
| `plan_attempt`, `plan_execution`, `plan_verification`, `plan_release` | `attempt`, `execution`, `verification`, `slot_release` (`slot`, `reservation`, `published_branch` unchanged) |
| `plan_attempt.plan_commit` | `attempt.end_commit` |
| `plan_verification.plan_blob`, NOT NULL exactly when `verified` | `verification.blob`, nullable; the `reason` CHECK stays |
| `plan_execution.plan_path` | dropped (nothing read it; `PlanAnswer.plan_path` and the answer schema keep the key) |
| (none) | `attempt.step TEXT NOT NULL CHECK(step IN ('plan'))` |
| (none) | `execution.effect TEXT CHECK(effect IN ('commit','keep','none'))` |

- **Effect.** `attempt_types.Effect`/`EFFECTS`; `AnswerState.plan_path` is replaced by `AnswerState.effect` (the stored
  answer read back must equal the one written). `plan_step.EFFECT_OF` maps the dispositions (`planned` to `commit`,
  `unchanged` to `keep`, `incomplete` and `needs_owner` to `none`); `attempt._validate` sets it, `AttemptStore.answer`
  writes it with the disposition, an unusable answer stores NULL for both. The three SQL fences read `effect` only:
  `AttemptStore.end_commit` (`commit` with X != B, `keep` with X = B), the verdict insert (`commit`/`keep`;
  `nothing_written` needs `commit`, `reused` needs `keep`) and `admit.PREVIOUS` (a repeat needs `commit`/`keep`).
  Python branches on the disposition word (`verifier`, `factory_commit`, `verdict`, `repeat`) are unchanged; S3 moves
  them to the step port.
- **Step.** `plan_step.STEP = "plan"`. A fresh admission writes it, a repeat copies the previous attempt's (`PREVIOUS`
  reads `p.step`). `Admission.step` (loaded by `AttemptStore._load`, so `AttemptRecord` carries it through its
  admission, no second field) and `AttemptRow.step` (`attempts()`). Not displayed: rows, JSON and `rounds.log` gain it
  in S4 (section 16).
- **Names.** `AttemptStore.end_commit()` (was `plan_commit()`); `AttemptRecord.end_commit`, `ChainLink.end_commit`,
  `Verified.blob`, `factory_commit.leftovers(..., end_commit)`.
- **Tests.** SQL renamed everywhere; every test `INSERT INTO attempt` names `step`. New: `test_attempt.py`
  `test_the_answer_is_stored_with_its_effect` (4 cases: `planned`, `unchanged`, `needs_owner`, invalid JSON) and
  `test_verify.py` `test_the_end_commit_and_verdict_fences_read_the_stored_effect` (3 cases; the disposition stays
  `planned`, only `effect` varies). The repeat gate's `incomplete` disposition fixture became `no_effect`
  (`effect='none'`). The schema refusal tests (`test_ops`, `test_launch`) now refuse version 8 (and 10).
  `test_policy` `WRITERS` names the new tables. The live-smoke runbook's `sqlite3` lines use the new names.

Gates: `just check` clean (ruff, pyrefly 0 errors, import-linter 6 contracts kept); `just test` 1237 passed (1229 + 4
answer-effect cases + 3 fence cases + the version-10 refusal case). Source code lines +16 over the touched modules
(2436 to 2452): `admit` 331, `attempt_store` 317, `attempt_types` 226, `attempt_reads` 180, `plan_step` 112,
`factory_schema` 97; `operations` 382 untouched.

## 12. As built: A1-A3, B (naming review, 2026-11-11)

Four commits after S2, no stored or printed word changed except the B rows below. Counts are `git show --stat`.

- **A1 `53f60dd84`** (47 files, +708/-680): internal renames from the naming review (types, functions, locals, test
  doubles); no behavior change.
- **A2 `ac4e92e40`** (20 files, +431/-383): moves, no behavior change: `exit_codes`, `round_log`, `plan_guide` and
  `plan_render` are new modules (`cli_plan` split); `EvidenceFiles.last_entry` is the entry-log reader;
  `plan_step.feedback` is the repeat feedback; the justfile recipe `prepare` became `install`.
- **B `f4e7cfd8e`** (25 files, +86/-64): word changes, before to after:
  - `tl plan verify` release and branch lines: before `released`/`published` counted as done and `already_*` as held,
    after `released`/`already_released` and `published`/`already_published` are both done (`publish_word` and
    `release_word` own the words, shared by verify, publish, release and the round print).
  - `tl plan start` on an uncertain launch: before `uncertain`, after `uncertain:launch` (`Failed.word` renders
    `kind:reason` everywhere).
  - Claim-leak text: before two texts (`GUIDE["claim_leaked"]` and the round's `LEAKED`), after one,
    `tracker.leaked_claim`.
  - `stage` became `step` in the agent input and the CLI help text.
- **B repairs** (uncommitted): `tracker.leaked_claim` is the one claim-leak text, now with the in-progress/not-ready
  explanation and `ACTOR`; the round renderer prints it with the real task id (the `GUIDE["claim_leaked"]` placeholder is gone).
- `publish.is_published` and `slot_release.is_released` own the done words; `plan_render` uses them and `release_word`
  instead of hardcoded words. A render test covers `already_*` (no guide) against a held release (guide).
- `live-smoke.md` entry.log grammar lists `already_released` for `release=` and `already_published` for `branch=`.
- **A3** (this repair, uncommitted): test doubles moved to `tests/steps/doubles.py`; `gated`, `_freed_*`, `checked`,
  `Shown.status` (now `view`), `_status*` in `operations`/`plan_render`/`result_data` (now `_show*`) and the test
  `Launcher` doubles (now `FakeLauncher`) renamed; two prose fixes. No printed or JSON word changed.

## 13. As built: C, factory.db schema v10 (2026-11-11)

Schema version 10; no migration: `current()` refuses a v9 file (`refused:schema`), the owner discards factory.db. The
step bump planned as v10 in 3.4 and section 4 (S5) is now v11.

| v9 | v10 |
|---|---|
| `execution.publication` (`complete`/`pending`/`conflict`/`fault`) | `execution.session_state`: the session ref's capture, never the Git push |
| `slot.cwd` | `slot.path` |
| `reservation.cwd` (a copy of `slot.cwd`; slots never re-path: `adopt` refuses `other_root`) | dropped; the slot path is read by joining `slot` on (repo_id, slot) |
| `slot_release.abandoned` with `CHECK((abandoned = 0) = (claim = 'kept'))` | dropped with its CHECK; SQL reads `claim<>'kept'` (abandoned) or `claim='kept'` (settled) |
| `execution.tokens_known`, `execution.cumulative_known` | dropped; counts are known when any of the three is non-NULL, an unknown count stays NULL (never 0) |

- **C1 session state.** `StoredExecution.session_state`; `AttemptStore.capture(..., session_state)`; every fence reads
  `session_state` (`end_commit`, the verdict insert, `admit.PREVIOUS`, `verifier`). `Attempts.publish`/`_publish` are
  `Attempts.capture`/`_capture` and `PublicationResult` is `CaptureResult` (the retry stores the evidence files, the facts
  and the session state, not only the session); `attempt_entry._capture` and `CAPTURE_RETRIES`; `SessionLatch._record`.
  Unchanged on purpose: the `pending session_<state>` result reason and `verify=unavailable:session_<state>` (logged in
  `entry.log`) and the entry log key `publish=` (the capture retry's DB acceptance; live-smoke already says it is not the
  branch push).
- **C2 abandoned.** `ReleaseRow(head, released_at, claim)` with `abandoned` a property (`claim != 'kept'`);
  `slot_release._Row.released` is the claim alone; `Released` and `AlreadyReleased` keep their `abandoned` bool. The
  abandon flip is `UPDATE slot_release SET claim='unclaiming' ... AND claim='kept'`; `admit._attempted` reads
  `r.claim IN ('unclaimed','not_held')`; `publish` `ROW`/`FENCE`/`ABANDONED` read the claim.
- **C3 token counts.** `_facts_values` writes the six counts only; `attempt_store._counts` reads (in, cached, out) back as
  None when all three are NULL. `ExecutionFacts` is unchanged (`_usage` never yields three unknown counts).
- **C4 slot path.** `Admission.slot_path` (was `cwd`), read in `AttemptStore._load` from `slot.path`; the release's `ROW`
  joins `reservation` to `slot`; `slot_lock.lock_path/acquire/custody/repeating/probe(slot_path, ...)`, `slots`,
  `slot_state.repository/observe_slot`, `factory_commit`, `prepare`, `repeat`, `verifier`, `attempt_entry`,
  `publish._Row.slot_path`. `admit._unheld` returns the slot name only; the reservation insert has no path. Kept as
  `cwd`: the agent's and the entry's process cwd (`LaunchInputs.cwd`, `launch.py`), bd's cwd (`composition`), and the
  `lsof ... -d cwd` advice in the guide.
- **C5, C6 JSON.** See the words below. Human text is unchanged; `rounds.log` never carried `detail`.

Visible words, before to after:

- `Next:`/`stuck` word `stuck:unpublished` to `stuck:uncollected` (show, list, `tl plan list --stuck`, rounds report),
  with its guide text before "The result is incomplete; keep the evidence. `tl plan release --abandon` ..." and after
  "The result was captured but never collected: its answer or its session is still pending or faulted (the attempt's entry.log
  says why), and no verify can judge it. Keep the evidence. `tl plan release --abandon` ..." (a verify cannot judge such a
  result: it answers `unavailable:validation_pending`/`unavailable:session_<state>` for a planned or unchanged answer
  and `not_applicable:<end word>` otherwise, so the guide does not offer it).
- `tl plan next --json`: a move's `attempt_id` is `null` (was `""`) when the move has none, like `detail`.
- `tl plan start --json`: key `entry` (the entry process object) to `entry_process`, as show and list already name it
  (their `entry` stays the state word).
- JSON empty strings to null: `tl plan start --json` `result` (`""` to `null` when nothing was found), the error
  object's `message` of every plan command (`""` to `null` when a refusal has no detail), `tl plan next --json` each
  move's `detail`, and `tl plan rounds --json`'s end `detail`.
- `sqlite3` lines of the live-smoke runbook: `publication` to `session_state`.

Tests: SQL renamed; every raw `INSERT INTO reservation` lost its path, and the seeds without a `slot` row
(`test_attempt`, `test_attempt_store`, `test_repeat`, `test_repeat_real`, `test_plan_cli`) gained one; the other-repo
cases also move the `slot` row. The refusal tests refuse 1 to 9 and 11 (`test_operations`), 9 (`test_launch`,
`adopt`). Two stored-count assertions in `test_attempt` (a known partial count is stored as `(8, NULL, 3)`, unknown
usage as six NULLs). `test_policy` `WRITERS` unchanged.

Gates: `just check` clean (ruff, pyrefly 0 errors, import-linter 6 contracts kept); `just test` 1248 passed (1247 + the
version-11 refusal case). Code lines of the big modules: `admit` 331, `operations` 354, `attempt_store` 318,
`factory_schema` 94 (was 97). Live smoke not run.

## 14. As built: D (glossary and docs, 2026-11-11)

Docs only; no source or test change.

- **New glossary section** "Factory vocabulary as built" (30 rows): phase, admission, reservation, slot custody, entry
  process, launch, relaunch, dispatch, claim, backlog, round, move, settle, repeat, verdict, disposition, effect, agent
  answer, execution, agent process, session state, capture, evidence files, park, slot release, publish, deadline, stuck,
  reserved/locked/held, label. Plus the tables "Commit letters" (B, D, E, X, T and their columns) and "CLI flags"
  (11 rows; notes the S4 `tl plan` to `tl step` cut).
- **Fixed rows:** `RunKey`/`Carry` (reference-implementation identifiers, absent here), `host` (no `*Host` Protocols),
  `profile` (target concept; `.task-loop.json` unread), `push` (points to publish), `reuse` (versus the `reused` verdict),
  `release` (points to slot release), `attempt` (a repeat is the step-level retry), retired `gate`, `outcome` (new row),
  `worker`, `stage`, and `run, call or harness invocation` (names the retired `step run`).
- **New files:** `docs/design/INDEX.md`. README links it and states that `tests/steps` holds all factory tests.
- **Dangling links:** `slot-grant.md` (incident path now plain text, marked absent), `dashboard/README.md` (design-only
  note, two links de-linked), `sqlite-store-plan.md` (`docs/dev/integrations.md` marked a baseline document).
- **Decisions (the five word picks):** `repeat` is the step-level retry (CLI, DB and log say repeat); `slot release` is
  the glossary term and cross-refers the distribution `release`; `entry process` (not launcher or runner); `slot custody`
  (code: `custody`, `hold`); `agent answer` versus the owner's answer to an `ask`.
- **Retired words:** `step run` (say attempt), `publication` for the session capture (say session state), the `publish`
  sense of storing a result (say capture), `stage` (step), `worker` for the agent (agent; library `Worker` type excepted),
  `outcome` (result, conclusion or verdict).
- **Known leftover words in code, not changed:** entry.log key `publish=` (capture retry), three "outcome" comments
  (`attempt.py` 71, 82, 83; `attempt_entry.py` 185), "publication" for the branch push in `attempt_entry.py`,
  `publish.py`, `composition.py` comments, and `tl plan release` help saying "parked at its base".

## 15. As built: S3 (step port, 2026-11-11)

Behavior-preserving: no schema, CLI, JSON, log or agent-facing text change.

- **`steps.py` (new, 31 code lines).** `StepKind` (frozen: `step`, `rules`, `input_text`, `answer_schema`, `decode`,
  `artifact`, `feedback`), `Feedback` (the Protocol of `feedback`'s keyword-only signature), `PLAN`, `STEPS = (PLAN,)`,
  `kind(step)` (a `match`; an unknown step raises `ValueError`) and `RULES = CHAIN_RULES + plan_step.ARTIFACT_RULES`,
  read by `attempt_store`'s stored-verdict reader. It re-exports nothing: consumers import types from their owner.
- **`attempt_types`.** `Answer(disposition, effect, paths, message, explanation)` replaces `PlanAnswer` (no `plan_path`:
  the decoder still validates it, nothing read it); `Decoder` is gone; `type Step = Literal["plan"]`; `CHAIN_RULES`
  (the seven generic words) replaces `RULES`; the `Rule` type still lists every word, since `Rejected` lives here
  (`test_verifier` checks `steps.RULES` equals it); `ChainLink.disposition` became `ChainLink.effect` (the chain query
  reads `e.effect`; `attempt_reads.stored_effect` is the one effect parser, moved from `attempt_store`);
  `Verified.blob` is `str | None` and the reader accepts a NULL blob.
- **`plan_step`** keeps the plan's values only: `DISPOSITIONS`, `EFFECT_OF`, `ANSWER_SCHEMA` (unchanged), `step_rules`
  (was `plan_stage`), `decode` (was `decode_plan_answer`; same rules, now returns `Answer` with the effect),
  `input_text` (the task prose plus the closing words, moved from `admit.task_text`), `feedback` with `OPENING` and
  `repeat_instructions`, `artifact` (was `plan_rule`: the plan.md rule, returning the blob or `Rejected`) and
  `ARTIFACT_RULES`. `STEP` is gone: a fresh admission writes `admit.FIRST = STEPS[0].step`.
- **Consumers through `kind(admission.step)`.** `admit.task_text(task, step)`; `EvidenceFiles.prepare(key, schema)`
  (the attempt passes `kind(admission.step).answer_schema`); `attempt._validate` (`decode`; the `decoder` constructor
  parameter is gone, the decoder-fault test patches `attempt.kind`); `verifier` passes the kind to `verdict.judge`
  (`judge(repo, root, commit, step, rules, chain)`), which turns the kind's `artifact` into `Verified(blob, reused)`;
  `repeat._input` (`feedback`); `factory_commit.refusal` (one `rules` read instead of three `plan_stage` calls).
  `plan_stage` is removed. `factory_commit.attributes(rules)` is derived from the root: the `.gitattributes` of every
  folder above it, then the root (for `docs/design/<id>/` exactly the old list; asserted in `test_steps`).
- **Effect, not disposition words.** `attempt.committing(stored)` (a clean run's valid answer of effect `commit`/`keep`)
  replaces `("planned", "unchanged")` in `attempt.report` and `verifier.applicable` (`COMMITTING` is gone);
  `factory_commit.settle`/`leftovers`, `verifier._settle`, `verdict.judge` and `repeat._input` test `effect`.
  Display still uses the disposition (`end_word`).
- **Contract.** `.importlinter` `one-step-kind-owner`, type `protected`: `taskloop.plan_step` may be imported only by
  `taskloop.steps`. A `forbidden` contract with `source_modules = taskloop` was tried first and stayed kept with a
  probe import in `verdict` (the forbidden module sits inside the source package), so `protected` it is; the probe
  then broke it (`taskloop.verdict -> taskloop.plan_step`). Tests import `steps` too (`kind("plan")`).
- **Byte identity.** Before any edit, at `ac11e63e4`, the installed package produced: `admit.task_text` for a fixed
  `TaskInspection` (tl-1, a two-line requirement and acceptance), the `schema.json` bytes `EvidenceFiles.prepare` wrote,
  and `plan_step.feedback` for (`uncommitted`, recorded) and (`ignored`, unrecorded). `tests/steps/test_steps.py` holds
  them as constants and asserts the ported paths return them exactly, plus `kind("plan") is PLAN`, `STEPS == (PLAN,)`,
  an unknown step refused and the attributes list.
- **Tests otherwise.** `judge` callers pass the kind; `ChainLink` fixtures say `commit`/`keep`; the repeat feedback and
  decoder tests go through `kind("plan")`; the decoder test checks `effect` instead of `plan_path`; new
  `test_verifier.test_a_verified_row_without_a_blob_reads_back`.

Gates: `just check` clean (ruff, pyrefly 0 errors, import-linter 7 contracts kept); `just test` 1257 passed (1248 + 2
policy cases for the new files + 6 `test_steps` cases + the NULL-blob case). Code lines: `steps` 31, `plan_step` 132
(131), `attempt_types` 224 (225), `admit` 332 (331), `attempt` 289 (286), `factory_commit` 136 (134), `verdict` 55 (52),
`repeat` 141 (139), `attempt_reads` 190 (185), `attempt_store` 312 (318), `evidence_files` 83, `verifier` 129,
`operations` 354 untouched: +41 source code lines with `steps` (estimate +45). Live smoke not run.

## 16. As built: S4 (the CLI cut, 2026-11-11)

`tl step` replaces `tl plan` in one cut, no alias (Q1). The verbs and flags are unchanged: `start show list verify release
publish next rounds`. `tl plan ...` (bare, with a verb, or with `-h`) now exits 2 with argparse's own
`invalid choice: 'plan'` message, like any unknown command. No schema, agent-facing text or `entry.log` change.

- **Modules (A2 structure kept, renamed with `git mv`).** `cli_plan.py` to `cli_step.py` (parsers, run, wiring;
  `COMMANDS = ("config", "slot", "step")`, `OPERATIONS` keyed `("step", <verb>)`), `plan_guide.py` to `step_guide.py`
  (`PLAN_ONLY` to `STEP_ONLY`), `plan_render.py` to `step_render.py`; `tests/cli/test_plan_cli.py` to
  `tests/cli/test_step_cli.py`. Section 3.6's `cli_guide` name was not used: the guide module already existed as
  `plan_guide` since A2 and is now `step_guide`.
- **`attempt_status.py` (new).** `EntryState`, `Stuck`, `Next`, `Leftovers`, `StatusPorts`, `AttemptView`, `Shown`,
  `Listed`, `next_action`, `_stopped`, `_show`, `_released`, `show_attempt`, `_ended`, `list_attempts`, moved verbatim
  from `operations` (no word change; it imports `Clock` and `Failed` from `operations`). To avoid an import cycle
  (`operations`'s `Result` union named `Shown`/`Listed`), the `Result` union moved to `result_data` (the one JSON shape of
  every result; `exit_codes`, `step_render` and `cli_step` import it there). Importers updated: `round`, `cli_composition`,
  `result_data`, `step_render`, `cli_step` and five test files. `.importlinter`: `cli_plan`, `plan_guide`, `plan_render`
  renamed in all three lists, `attempt_status` added to both forbidden lists; 7 contracts kept.
- **`step` in the data.** `AttemptView.step` (required, after `task_id`, from `AttemptRow.step`); `tl step show` prints
  `Step: plan` after `Task:`; `tl step list` has a `step` column after `backlog`
  (`task backlog step attempt slot phase entry result next`); `--json` of show and list gain `"step"`. `Started.step`
  (`str | None`): `operations.start` reads it back after any start (`AttemptReads.step_of(attempt_id)`, one `SELECT step`),
  `None` (JSON null) only when that read fails, so a launched start is never turned into a failure by its label;
  `tl step start --json` gains `"step"`. Its human text is unchanged apart from the scope line below.
- **`rounds.log`.** `Move.step` (set for every move that carries an attempt: the snapshot's step for relaunch, repeat,
  verify, report, skip and publish moves; `Started.step` for a round's start). An attempt-bearing move line is now
  `<time> <backlog> <task> <step> <action> <words> <attempt>`, e.g. `... tasks tl-1 plan relaunch relaunched <id>`; a
  move without an attempt (a refused start, `claim_leaked`) and the `round`/`rounds` lines are unchanged. It is exactly
  one more fixed word: `round_log.WORD`/`IDENT` and `fixed()` are unchanged (`plan` passes `WORD`); the round tests'
  `LINE` grammar gained one optional `(plan )?` group and their expected word lists the step word. The quiet key
  `(task, action, word, attempt)` is unchanged (the attempt fixes the step). `Move.step` is not in the `tl step next`
  JSON (not asked for; the dashboard can take it later).

Visible text, before to after:

- **Spelling, every command named:** `tl plan <verb>` to `tl step <verb>` in every help string, `GUIDE` text, `HELD`,
  `ABANDON`, `ROUNDS`, `discard()`, `UNCLAIMING`, the `Admitted:`/`Abandoned:`/rounds-stopped lines, the uncertain-launch
  detail, the rounds-lock refusal (`another \`tl step rounds\` runs ...`), the slot release's tracker detail, and
  docstrings. `tracker.leaked_claim` names no command and is unchanged.
- **Scope string:** `PLAN_ONLY` "plan step only: publishes task/<id>; no merge or land" to `STEP_ONLY` "steps built:
  plan; publishes task/<id>; no merge or land" (in the root description, the noun's help and the start, show, list,
  verify, release, next and rounds help).
- **Help:** root "Plan commands run the plan step only: ..." to "Step commands: steps built: plan; ..."; noun `plan`
  "Plan attempts (...)" to `step` "Step attempts (...)"; verify "... publish a verified plan (...)" to "... publish a
  verified result (...)"; next "Run one scheduling round for the plan step: ..., publish verified plans; ..." to "Run one
  scheduling round: ..., publish verified results; ..."; publish "Push the verified plan commit to origin's task/<id> ..."
  to "Push the step's verified commit to origin's task/<id> ..."; release `--abandon` help spelling only.
- **Start line:** "This runs the plan step only: .... Follow it with `tl plan show ...`" to "Step commands: steps built:
  plan; .... Follow it with `tl step show ...`".
- **GUIDE wording (6 of 41 keys):**
  - `start`: "... then `tl plan start` to plan the task again." to "... then `tl step start` to admit a fresh attempt."
  - `publish` (`PUBLISH`): "The plan is verified but not on `origin` yet: ..." to "The step's result is verified but not
    on `origin` yet: ...".
  - `done`: "Collected: `succeeded` tells whether the plan was verified." to "... whether the step's result was
    verified."
  - `stuck:expired_admitted`: "... Then `tl plan start` plans it again. ..." to "... Then `tl step start` admits a fresh
    attempt. ...".
  - `failed`: "The step ended without a verified plan; ... to plan it again, `tl plan release --abandon` then `tl plan
    start`." to "The step ended without a verified result; ... to try it afresh, `tl step release --abandon` then
    `tl step start`."
  - `not_verified`: "Only a verified plan is published: `tl plan verify` first; a rejected plan has nothing to publish."
    to "Only a verified step result is published: `tl step verify` first; a rejected result has nothing to publish."
  - Spelling only (21): `wait`, `verify`, `repeat`, `repeats_exhausted`, `release`, `abandoned`, `unknown`, `attempted`,
    `abandoned_skip`, `no_free_slot`, `rounds_running`, `stuck:entry_lost`, `stuck:hung`, `stuck:uncollected`,
    `stuck:conflict`, `unsettled`, `registration_conflict`, `not_terminal`, `no_remote`, `branch_moved`, `remote_moved`.
    Unchanged (14): the rest.
- **Publish refusal details (`not_verified`):** "The plan was rejected (<rule>)." to "The step's result was rejected
  (<rule>)."; "The plan is not verified yet: `tl plan verify`." to "The step's result is not verified yet: `tl step
  verify`."
- **Kept on purpose:** text about the plan artifact (`plan.md`, the plan answer contract, the verdict words
  `plan_missing` ...), `plan_step` and the `plan` step value; docstrings outside the renamed modules that say "plan"
  as prose (`attempt_entry`, `attempt`, `launch`, `slot_release`) were not reworded.

Docs: README's command list; glossary admission, round and stuck rows and the CLI-flags table (now `step`, the S4 note
says done); [.8.7](../tl-8bh9.8.7/plan.md) exception paragraph rewritten for `tl step` (with its history); a one-line
note in [.3.2.1](../tl-8bh9.3.2.1/plan.md); the live-smoke runbook's commands (`T step ...`, `START=(step start ...)`,
`NEXT=`, `ROUNDS=`, 83 lines) and its `rounds.log` comment; CLAUDE.md and AGENTS.md (`tl step rounds` in the
`one-signal-owner` sentence; still byte-identical). The slice documents .1 to .14 (other than that runbook) and the
history entries in INDEX.md, selection-review and .8.7 implementation.md are history and keep `tl plan`.

Tests: `test_step_cli.py` respelled; new `test_plan_is_an_unknown_command_after_the_cut` (bare `tl plan`, `tl plan
start ...`, `tl plan show ...`: exit 2, `invalid choice: 'plan'`); `step` asserted in the show/list JSON key sets and the
start key set, in the real read path (`"step": "plan"` in show and list JSON, the list row `tl-1 tasks plan 1/3 ...`,
the show lines `Task:`/`Step: plan`/`Attempt:`); `test_cli` checks `tl step` help and that bare `tl plan` and `tl step`
exit 2; `test_operations`/`test_repeat` expect `Started(..., step="plan")` where the store holds the attempt;
`test_round` expects the step in moves and log lines.

Gates: `just check` clean (ruff, pyrefly 0 errors, import-linter 7 contracts kept); `just test` 1262 passed (1257 + the
3 unknown-command cases + 1 `test_cli` invalid-request case (`step`) + 1 policy case for `attempt_status.py`; the renamed
files keep their cases). Code lines (policy counter): `cli_step` 160 (159), `step_guide` 97 (97), `step_render` 131
(132), `operations` 253 (354), `attempt_status` 116 (new), `round` 214 (213), `result_data` 105 (105), `attempt_reads`
194 (190); source +21 code lines (5585 to 5606; estimate +30). Live smoke not run (owner: `tl step --help`, one
`tl step next` round).

S4 review repair (no output word changed except the scope line):
- `test_round`: the log test's admission seeds a real attempt row, so the start line carries `plan`; `LINE` now requires the step word on every attempt-bearing line (refused/unavailable starts, `claim_leaked` and `round` lines stay without); removing `step=result.step or ""` fails it. `test_operations` pins `Started.step is None` when `step_of` raises `StoreUnavailable`.
- Naming and prose: the Next word in `attempt_status._show` and in `test_step_cli` is `next_word`, not `step`; `cli_composition` and README say "step" not "plan".
- Help: "Step commands: steps built: plan; ...." (two colons) is now "Step commands (steps built: plan; publishes task/<id>; no merge or land)." in root help and the `tl step start` line; `STEP_ONLY` unchanged and single-sourced.
