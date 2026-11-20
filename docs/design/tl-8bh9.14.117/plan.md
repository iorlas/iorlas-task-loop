# Declarative workflows (proposal, round 4)

Round 4 (2026-11-15): the owner delegated the remaining choices to the independent reviewer ("decide with Fable"); its
verdicts, checked against the code, are applied below. They are still proposals until the owner's yes on the words in
section 6.

Status: BUILT 2026-11-19 (PRs #818-#828) except `max_attempts` (bead tl-7125.4.2, deferred: see its notes). Decisions below are the record; where the code differs, the code and the glossary rows `workflow` and `engine_digest` win (e.g. `--workflow NAME` without `@sha`, decision 6; `--from implement` is `Overrides.start`; `[[step.feedback]]` is built). Parent task: tl-8bh9.14.117 (step prompts and agent as step data).
Purpose: let the owner measure workflow changes (noise of an unchanged workflow, then A/B variants, then a regression
check on other tickets) by making the workflow a Git-versioned file whose content, and the engine that ran it, are recorded
on every attempt. The owner decided the order: this comes first. Inputs: seven independent reviews by Fable (transitions,
single-file shape, five draft shapes `drafts/v1`..`v5`, three lens reviews of `drafts/v6-candidate.toml`, and a simplicity
and consistency pass on round 2 of this paper, whose contradictions this round fixes). OWNER marks what the owner decided;
everything else is a recommendation with its reason, waiting for the owner's yes.

## 1. Decisions, each with its reason

| # | decision | reason |
|---|---|---|
| 1 | OWNER. One TOML file per workflow, `.task-loop/workflows/<name>.toml`, read from Git with stdlib `tomllib` into frozen strict pydantic models (`extra="forbid"`). The workflow's name is its file name; the file has no `name` or `schema` key. No YAML, no packaged default; a missing file is a typed refusal. | No new dependency (repo already reads TOML); one file is one thing to diff and pin. A format version key would imply a compatibility reader, which AGENTS.md forbids; a format change is a hard cut that changes the digest anyway. |
| 2 | OWNER. Prompt text is data in that file: an ordered list of sections per step, each either `text = """..."""` (verbatim) or `use = "<renderer>"`. No placeholders, no template language, no renderer arguments. Reverses round 25 (prompts as Python modules). Slice-1 renderers are exactly two: `task` and `input_context`. Everything else that is not strategy (plan template and byte caps, plan reference, answer contract, repeat frames) is appended by code and is not a renderer a file can name. | One owner per kind of prompt fact. `str.format` breaks on JSON braces, `string.Template` on `$TMPDIR`. Fewer renderers means less surface to rot into a template language. |
| 3 | Contract and safety live in code and are appended by code: answer schema and decoder, dispositions and effects, `StepRules`, the final-answer warning, Git-write, saved-work, plan-handoff and plan-metadata sentences, the plan template, the plan reference sentence, repeat frames, access policy, attempt ceiling. They are not listed in the file. File prose may *mention* a disposition word; checking that the words match the step kind is deferred (it would be prose matching). | The agent can write the file on its branch; "ignore the contract" text cannot be detected, so safety is the decoder, rules, sandbox and checks, never prose. |
| 3a | Consequence to accept: today's prompts put contract sentences in the middle of prose (`implement_step._closing_words`, `plan_step._closing_words`). Splitting them into code-appended contract and file strategy makes the new default prompt different from today's. The first workflow slice therefore creates a NEW baseline; the A/A noise test runs on it and is never compared with runs from before the split. | Honest cost of "contract in code": reordering may move cost by itself. An A/A arm of the old and the reordered prompt measures that (section 6). |
| 4 | DECIDED WITH THE REVIEWER. Step identity in slice B is `kind` only (the existing glossary term `step kind`: `plan`, `implement`, `check`). The file holds keyed tables `[step.plan]` and `[step.implement]`, so a duplicate, missing or misordered kind cannot be written; the order is fixed in code (plan, implement, check); the check step has no table and no agent. An `id` (and `[step.<id>]`) arrives with edges or step reuse. | `attempt.step` is a closed `CHECK(step IN ('plan','implement'))` (`factory_schema.py:110`) and decision 16 generates it from the enum, so a free `id` fights it today; adding `id` later costs one file edit and a schema bump that edges need anyway. Reverse if a second step of one kind is scheduled before edges. |
| 5 | DECIDED WITH THE REVIEWER. Start at implement from a frozen plan is a run parameter `--from implement`, not omission of steps from the file (the digest stays equal across arms) and not a seeded database. It skips the database evidence, requires `plan_reuse.evaluate` to return REUSE at the source commit (the committed plan, its metadata and unchanged cited paths) and refuses otherwise. No schema change: implement at number 1 with `after_commit` already satisfies the CHECK (`factory_schema.py:136`, `admit.py:320`). | On a fresh `--db`, `ResumePlans.select` returns PLAN (`resume_plan.py:52`) because `latest_plan` finds no row; reusing it would need forged rows in `attempt`, `execution`, `verification`, `task_content` and `slot_release` (`attempt_loads.py:111-124`, `factory_schema.py:162`, `admit_rows.py:91-98`) — the history reconstruction AGENTS.md forbids. Running plan and abandoning per setup gives every arm a different plan. Unverified: whether implement's input or verification assumes a plan row. Reverse if the owner accepts per-arm plan variance. |
| 6 | Selection: default is workflow `default` read at the same `source` admission already uses for the profile (`admit.py:167`, the task-branch start). RESCOPED by the owner 2026-11-19: `--workflow NAME` picks another file at the same source commit; there is no `@REF` (an A/B arm is a branch with its own file, or one branch with several files), so nothing reads another commit. Resolved once. | A branch name moves and is forgeable; a sha is a fact. One read point for profile and workflow (the task-branch start, not always origin main). |
| 7 | Pin by value: at the task's first agent attempt the file's bytes (at most 64 KiB) are stored in factory.db keyed by digest, and the attempt row stores the digest and the resolved commit sha separately (the same bytes can sit at two shas). Later steps, repeats and relaunches read the stored bytes, never Git. No re-resolve-and-compare path. After an abandon the task starts fresh and resolves again. | One owner, no spurious holds when a person advances a branch; an agent editing the file mid-task changes nothing. Precedent: input text is stored by value with a verified sha256. Repeats already embed attempt 1's stored input and copy model, effort and harness from the previous row, so only an advance to the next step needs the file again. |
| 8 | DECIDED WITH THE REVIEWER. Digest = sha256 of the file's bytes. Engine identity is one value on the attempt, `engine_digest` (the word is for the owner to confirm; see section 6): sha256 over the sorted `(path, hash)` pairs read through `importlib.metadata` from the installed `RECORD` of every installed distribution, excluding `*.dist-info/` entries and paths starting `..`. It needs no build hook and no `just install` stamp, covers shelf and `any_agent`, and tells dirty builds apart. No `engine_version` (constant 0.1.0 in `pyproject.toml`) and no Git commit. Results from different engine digests are never pooled. | In the installed package `RECORD` carries a sha256 per file (a `taskloop/steps.py` entry matched an independent hash); `direct_url.json` is a `file://` URL and `uv_cache.json` has `commit: null`, so no commit exists to read. A whole-`RECORD` hash is unstable (it lists `uv_cache.json` and the `tl` script), hence the exclusions. `just install` runs inside slots, so a generated stamp would cause `uncommitted` repeats. Stability across two installs follows from content hashing but was not run; reverse if any distribution lacks `RECORD` hashes. |
| 9 | One schema bump per slice that needs columns. Slice A adds `engine_digest`, `admitted_at` and `ended_at` only. Slice B2 adds the stored-file table and the attempt's `workflow_digest` and `workflow_sha` with its own bump. Not added: name (it is the file name), the per-start overrides (the attempt row already stores the resolved model, effort and harness), `from_step` and the harness CLI version (deferred until needed). | Decision 7 stores the file bytes in a table that does not exist yet, so B2 must bump anyway; null workflow columns in A would be speculative. Any bump discards the database; export rows before it. Times exist only scattered (`setup_run`, check results, `verification.observed_at`, `slot_release.released_at`, duration files); wall time is a primary metric, so it becomes a row fact. |
| 10 | Slice C (not slice 1): `attempts = N` on the implement step, only lower than the engine ceiling of 3, and an ordered section list for the failed-check input (`[[step.feedback]]` of `text`; the fenced check output and the plan handoff are appended by code, so there is no renderer for them). | The owner's primary metric is the check-then-fix cycle, so these are the first levers after the file exists. `ATTEMPTS` is compared in about eight modules (`admit_chain`, `repeat`, `attempt_status`, `attempt_reads`, `check_repeat/status`, `show_render`, `step_render`); that is real cost, so it ships separately and after the A/A baseline. |
| 11 | `input_context` stays one renderer (the framed block: source commit, check commands, glossary excerpt, shelf digest, code map), used exactly once per input. Its strategy prose (`ORIENTATION`, `input_context.py:23-34`) moves to a `text` section. Toggling glossary or code map is a later lever. | Orientation is strategy hidden in code; the frame and source commit are contract (plan metadata needs the commit). |
| 12 | No section ids and no per-step digests. Attribution of a change is a diff of two stored files by their digests. | The stored bytes already identify the change; ids and a second digest add columns with no consumer. |
| 13 | The profile keeps all five keys (`setup`, `checks`, `required`, `target`, `land`). The workflow never defines a check; a prose sentence naming `just check` is accepted (repo prose, not engine). `.task-loop/` AND `.task-loop.json` are added to implement's excluded prefixes, shipped as its own small task (a gate fix that stands on its own, not part of the workflow slices). | One owner per fact; `required`, `target` and `land` read from main keep an agent from weakening its gate. Today (`EXCLUDED` is `.beads/` only, `implement_step.py:31`) an implement agent can edit `.task-loop.json` checks; only the land gate catches it. A loader test that compares prose with profile commands would be regex over text across two refs, so it is not built. |
| 14 | Loader refusals in slice B2, all typed and before any render: a file over 64 KiB, not a regular file, not TOML, an unknown key, step kind or renderer (a duplicate, missing or misordered kind cannot be written, because steps are keyed tables, decision 4), the `input_context` renderer not used exactly once, a text containing the factory's static frame markers (`BEGIN FACTORY INPUT CONTEXT`, `TRACKER DISCUSSION DATA`; `EARLIER ATTEMPT DATA` is found by substring, so match substring for it). Not built: nonce-fenced markers (they carry a nonce, so a line cannot forge them), control and bidi character filters, a secret scan, step and section counts, a harness-enabled check at load (admission already refuses a mismatched harness). | The file is owner-authored and reviewed in Git like code; the risk model is mistakes and a landed branch, not a hostile author. Each omitted refusal is cheap to add if a failure shows up. |
| 15 | Failure outcome: `AdmitRefused("workflow")` with a closed reason enum for the refusals above (missing, not_a_file, not_toml, too_large, unknown_key, bad_value, unknown_kind, unknown_renderer, reserved_marker). Git unreadable is `AdmitUnavailable`. A refusal of the default file in a round is a repo-wide wait logged once; a per-task one is a hold with a typed cause. | Same shapes as the existing admission refusals and `no_required`. |
| 16 | RESCOPED 2026-11-17 against main: the `Step` enum already exists (`step.py`) and is the kind name, so no `StepKindName` and no new word; B1 shrank to `steps.KINDS` (a `Step`-keyed mapping, `ORDER` derived), the schema step list and the remaining step literals generated from `Step` (same DDL, no bump). `StepSettings` stays until B2 replaces it with the workflow file's step tables. Original text: The registry replaces the fixed tuple in slice B1, ahead of the loader and with no behaviour change: a `StepKindName` enum in the shared kernel, `steps.py` stays the only importer of step modules and builds the registry; `STEPS`, `ORDER`, `kind()`, the `Step` literal, `AgentStep` and `StepSettings` are deleted. The stored value of `attempt.step` stays the kind, and its schema `CHECK` is generated from the enum. The step-literal sites (14 files found, e.g. `admit_rows.py`, `admit_chain.py`, `attempt_loads.py`, `setup_store.py`, `check_repeat/store.py`, `resume_plan.py`, `cli_step.py`, `agents/config.py`, `dash_board.py`) move to the registry. | One mechanism, no dual path. Kind-only identity (decision 4) removes the earlier clash between a free-string `id` and an enum-generated `CHECK`. |
| 17 | OWNER. Glossary gets `workflow` (a Git-versioned file listing a task's steps in order, each with its agent setting and prompt sections; later edges and caps; it excludes check definitions, `required`/`target`/`land`, the code contract and machine config). The `step kind` row is rewritten ("never configuration" is no longer true), and the GitHub paragraph that reserves `workflow` is edited. `variant`, `section`, `evaluation`, `identity` stay plain English. | Owner chose only `workflow` now. |
| 18 | Agent setting in the file: `harness`, `model`, `effort`, `compaction_token_limit` (absent = unset). Sandbox, access policy and credentials stay in machine config. Defaults to check before the real file is written: implement effort is `medium`, not `high`. A `--model/--effort/--harness` flag still overrides per start; the row stores the resolved values. | Machine-specific safety does not belong in a branch-readable file. |
| 19 | DECIDED by the owner 2026-11-15. The 400-line cap applies to `.py` files; the workflow file is bounded by the 64 KiB loader cap. | It is data, and prose moves into it. |

## 2. File shape for slice B2 (candidate v7; prose abbreviated)

```toml
[step.plan.agent]
harness = "codex"
model = "gpt-6.1-sol"
effort = "high"
[[step.plan.prompt]]
text = """\
First assess depth from the supplied task text alone, before any exploration or reading.
…
State the evidence-gathering budget in model calls: small 6, medium 12, large 20."""
[[step.plan.prompt]]
use = "task"
[[step.plan.prompt]]
use = "input_context"
[[step.plan.prompt]]
text = """\
After the depth assessment permits planning, follow this plan-only reading order.
…"""

[step.implement.agent]
harness = "codex"
model = "gpt-6.1-sol"
effort = "medium"
[[step.implement.prompt]]
use = "task"
[[step.implement.prompt]]
use = "input_context"
[[step.implement.prompt]]
text = """\
Immediately after reading the plan, reassess scope before broad exploration or editing.
…
If the work needs more than about 60 model calls or touches more than 60 files, stop after the first coherent part …"""
[[step.implement.prompt]]
text = """\
The factory ran this repository's `setup` before you started; uv uses the prepared cache offline.
…
Make every file edit with `apply_patch`, never with a Python or sed script."""
# no [step.check]: the check step is the fixed last step with no agent and no prompt
```

Code appends after the file's sections: the plan template and byte caps, the plan reference, the answer schema, Git-write,
saved-work, plan-handoff and plan-metadata sentences, the commit-limits sentence. Numbers enforced by code (byte caps, 96 paths,
1 MiB, the attempt ceiling) are owned by code; numbers that exist only in prose (60 files, 3 behaviours, 100 model calls,
6/12/20 evidence calls) stay in the text, each stated once, and a variant edits them there. Prose formatting rule: one
sentence per line using TOML line-ending backslashes, so a one-sentence A/B edit is a one-line `git diff`.

## 3. How the experimenter uses it (the test of the design)

- **A/A noise test.** N reruns of one task from the same base commit, each as attempt 1 in its own isolated setup (`--db`,
  `--artifacts`, `--root`, `--tracker-root`), `land: manual`. Each setup also needs its OWN clone and its OWN bare origin
  at the base commit (no code needed). Verified in code: sharing one checkout makes a local `task/<id>` the start commit,
  so a rerun resumes the previous arm's commits or refuses `branch_held` (`prepare.py:120-125`); separate clones on one
  origin refuse the second push `diverged` (`publish.py:221, 291`), and an advance needs `published_branch`
  (`admit_chain.py:182`), so the arm stalls after plan.
  Sanity: plan attempt 1 has equal `input_digest` across arms. Interleave arms and price cached tokens separately
  (sequential runs warm the provider cache). Expect about 10 runs per arm before the distribution of cycles (capped at 3,
  censored by holds) means anything.
- **A/B.** Two shas of the file, same base, same engine digest. Expressible in the file: sentence edits, thresholds in prose,
  a paragraph added or removed, model, effort and compaction per step, a size gate in prose. In slice C also the attempt
  count and failed-check feedback. Still engine-only (so not a clean workflow A/B): plan byte caps and template, tail size of
  check output, input-context composition, session resume.
- **Per result** (row facts after slice A and B): workflow digest and stored bytes, engine digest, resolved agent setting,
  base commit, input digest, step, number, repeat reason, disposition, verdict, tokens and turns, per-check conclusions, hold
  cause, admitted and ended time. Report the `needs_owner` and hold rate separately and count cost only for runs that reach
  green (a variant can win on cost by refusing more).
- **Known gaps.** The gate (`checks`, `setup`) is read from the commit under test, so an implement agent can weaken it and
  only the land gate catches that; an evaluation never lands, so the evaluation slice must compute gate facts per attempt
  before trusting a pass rate (the exclusion in decision 13 narrows this, it does not close it). The harness CLI version and
  model snapshot are not recorded. `input_digest` witnesses only the admitted input; `attempt.py` re-reads the context at the
  slot HEAD and rewrites it, and `agents/launch.py` appends the schema text, so the launched prompt has no digest.
  Export rows before any schema bump; never straddle one.

## 4. Deferred, with the direction

Loop edges: `(from step id, on trigger, to step id or hold)` with a closed `Trigger` enum over typed results that exist
(failed check, unsettled, cap exhausted), parameters `session fresh|resume` and named feedback sections, mapped onto today's
repeat, advance and hold, so no second mechanism; the file selects among registered edge shapes rather than being an
interpreter. That is when `id` and `with` arrive. Never routable: `needs_owner`, `incomplete`, `main_moved`, `timed_out`,
`dirty`, `lingering`, `interrupted`, land-time failures. Also deferred: `session: resume` (Codex only; `ClaudeHarness()`
takes no resume; token counts become non-additive), check-to-plan (per-task cap, a rule for implement commits on the branch,
the schema CHECKs at `factory_schema.py:135-138`), per-edge caps, conditions (equality over enum-typed inputs only),
`--until`, section ids, an evaluation command and report. A parser must reject any cycle without a cap.

## 5. Slices (cut where the experimenter needs them)

The A/A test needs no workflow file: an unchanged engine is the same workflow. So:

- **A. Identity.** One schema bump: `engine_digest` (the `RECORD` rule, decision 8), `admitted_at`, `ended_at`. Ships first
  as the workflow program's first child and enables the A/A noise test on today's prompts (rig: one clone and one bare
  origin per arm). B2 must not wait for A/A results. Not merged with B: B is already too large for one bounded task, and
  question 3 of section 6 needs A's rows on the old prompt.
- **B1. Registry cut.** The `StepKindName` enum, `steps.py` builds the registry, the fixed tuple and the step-literal sites
  are replaced (decision 16). No behaviour change, no schema bump.
- **B2. Workflow file.** Loader, models, the stored-file table and the attempt's `workflow_digest` and `workflow_sha` (its
  own bump), digest and pin by value, the split of contract from prose and the repo's own `default.toml` (a new baseline:
  decision 3a), `--workflow NAME` (no `@sha`, decision 6), the two renderers, glossary edits, contract and loader tests, deletion of the prose
  constants and their substring tests.
- **C. Loop levers.** `--from implement` first (decision 5), then `attempts` and `[[step.feedback]]`.
- **Separate small gate fix.** Exclude `.task-loop/` and `.task-loop.json` from implement writes (decision 13); it does
  not depend on any slice.

## 6. Open questions and evidence to gather

1. DECIDED by the owner 2026-11-15: the words `engine_digest`, `kind` and `--from`; the term "section" for one entry of a
   prompt; decision 19 (the workflow file is outside the 400-line cap). The owner asked whether a Git sha could replace the
   engine digest (clean tree, stamped at install). Answer: no, `just install` runs in slots and a stamp would dirty the
   tree, and the installed package carries no commit; decision 8 stands. A clean-tree refusal in `just install` stays an
   optional later guard. The sequence A, B1, B2, C: the owner chose the workflow first.
2. PROVED (proof of concept, 2026-11-15): two fresh installs of one commit (`uv sync --frozen --no-editable
   --reinstall-package`, separate environments) gave the same digest (970 files, every one with a `RECORD` hash, no
   distribution without `RECORD`); a one-line edit to `steps.py` changed it. Rule as in decision 8. Slice A keeps this
   as a test. Not run: an install on another machine or Python build.
3. Contract order: run one A/A arm of today's prompt against the contract-last prompt (slice B2) to learn whether order
   alone moves cost, before comparing any variant to the new baseline.
4. Plan-induced variance: with `--from implement` every arm shares one plan, so only the implement step varies; measure the
   variance of the plan step itself separately if plan variants are wanted.
5. DECIDED 2026-11-15: epic tl-7125 (P0) with children tl-7125.1 (A, P0), .2 (B1), .3 (B2, after B1), .4 (C, after B2)
   and .5 (gate fix). tl-8bh9.14.117 stays as the origin.
7. Unverified by the reviews: whether harness sessions survive a changed cwd; `merge/resolve.py` and conflict agents'
   writable paths (could one resolve a conflict in the workflow file?); whether saved WIP commits honour the excluded paths;
   where answer-repair prompt text is built; whether anything enforces "runtime fixed until restart" (entries spawn from
   `sys.executable`, so a `just install` while rounds run gives later entries new code); whether the profile is read at
   the base commit as decision 6 assumes.

## 7. Facts rechecked in the code (2026-11-15)

- Harness is already a per-step machine choice (`harness_choice.py`, `agents/launch.py`); tl-8bh9.14.117's "hard-codes
  CodexHarness" is stale. Implement effort default is `medium`.
- Step kinds are a fixed tuple (`steps.py`); the step literal appears in 14 files outside it; check is no kind today.
- Nothing records an engine identity per attempt; the attempt row has no start or end time (times live in `setup_run`, check
  results, `verification.observed_at`, `slot_release.released_at` and sealed duration files).
- `settings.apply` already refuses a `--harness` that mismatches the access policy; no harness fallback exists.
- `BEGIN SLOT STATUS` and `BEGIN CHECK OUTPUT` carry a nonce (`step_text.py:31`, `implement_step.py:199`).
