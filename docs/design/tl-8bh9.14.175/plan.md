# Reduce repeated document reads in factory attempts

Task: `tl-8bh9.14.175`. Status: proposed implementation plan.

## Result and scope

Every factory plan and implement input will contain the task's complete specification,
short instructions preventing the known orientation reads, the actual check commands,
and a factory-generated glossary extract of at most 2,000 tokens. Repeats, including
implement repeats after failed checks, must carry that context once.

This task changes factory-owned input generation and its verification. It does not edit
AGENTS.md, install or use a tracker inside an agent attempt, change check execution,
or change claims, scheduling, answer contracts or Git authority. The factory still uses
its tracker adapter; the restriction concerns the agent's environment. AGENTS.md changes
belong to `.185`, shelf information to `.186`, and additional plan-step orientation work
and its savings to `.192`. The common context applies to both agent steps here; do not
attribute the same plan-attempt savings to this task and `.192`.

## Current code

- `admit.task_text` delegates to the pure renderers in `plan_step.py` and
  `implement_step.py` through `steps.StepKind`. Fresh and next-step admissions store
  their rendered input through `EvidenceFiles.put_input`.
- `implement_step.ENVIRONMENT` currently directs the agent to discover commands under
  `checks` in `.task-loop.json`. `tests/steps/test_steps.py` explicitly tests that wording
  and the absence of repository commands; those expectations must change.
- `repeat.Repeats._input` frames the first attempt's stored input. Failed-check feedback
  also embeds the original task instructions. Neither path should independently append
  another extract.
- `profile.py` already validates profiles read from committed Git trees, and
  `git_views.GitProfileFiles` supplies that read. `prepare.branch_refusal` owns selection
  of an existing local task branch, an existing remote-tracking branch, or local main
  for a new branch. Do not create a second branch-selection rule.
- `docs/glossary.md` has several `Term / Meaning / Example / distinction` tables.
  Its large implementation-detail table makes copying every meaning incompatible with
  the requested small prefix. An extract must select complete definitions within a bound.

## Input contract

Use one shared factory instruction block for plan and implement. Keep the supplied title,
requirements and acceptance criteria intact, and retain the existing step-specific
scope, saved-work instructions, answer schema and factory commit rules. The block says:

- AGENTS.md is already supplied in context. Follow it without reading it again. These
  attempt-specific directions replace its general instructions to read orientation files.
- The supplied task text is the complete task specification. The agent has no task
  tracker: do not invoke `bd`, `bd prime`, `bd show`, or load the beads skill/SKILL.md
  to look for more requirements. Do not search Git history with the task id as a grep
  pattern; it supplies no additional task specification in this environment.
- The input lists the check commands directly, so do not read the justfile or
  `.task-loop.json` to discover them. In this repository these are literally
  `just check` and `just test`. Preserve implement's existing instruction to run all
  checks and fix failures, its allowance for focused checks while working, and the
  distinction between agent evidence and subsequent factory checks. Listing commands
  for a plan attempt does not instruct it to run implementation checks.
- Use the included glossary definitions. Read the full glossary only to resolve a term
  absent from the extract, collecting missing terms into at most one targeted read
  command per attempt. Do not start by reading the full document.
- Read the task's own plan as the step already requires. Read an older foundation plan
  only if the task's own plan cites it. Do not put the old foundation plan's path in the
  unconditional factory prefix, including in a warning about reading it.

The history instruction concerns searching for missing task requirements. Preserve
`step_text.SAVED_WORK`: inspecting real unfinished commits and their trailers remains
required, as does ordinary Git inspection needed to understand the code.

## Factory data and rendering

Introduce a small typed input context and a factory-owned reader beside the input
generation. Keep I/O out of the step renderers. Use the existing Git and profile ports;
no shell commands, subprocess calls, tracker reads by the agent, or new dependencies.
Pass validated profile checks and extracted glossary rows to the renderers through
`StepKind` and `admit.task_text`; update both admission paths and their composition.

Resolve the committed source using the existing branch selection for a fresh plan and
the next step's selected task-branch source for implement. Read profile and glossary
from that same source, never from the person's dirty checkout or the factory package's
working directory. Keep the selected commit with the input evidence so the commands
and extract can be audited. Ensure the input describes the tree actually prepared for
the attempt; if the selected ref moves before preparation, refresh the context from B
before launch rather than sending commands from a different tree. Preserve existing
custody, preparation, credential and dispatch ordering guarantees while wiring this.

Render every check's complete argv with shell-safe quoting; ordinary arguments must
produce `just check` and `just test` without an extra discovery instruction. Reuse the
profile validator and its failures. Do not hard-code this repository's commands into
generic factory code or render only the required subset of checks.

Retain input snapshots and the complete launched text through the existing evidence
owner. Repeats must reuse the original task and current attempt context without nesting
earlier feedback or duplicating instructions/extracts. If a repeat starts from a changed
committed tree, regenerate the context for that tree. No factory.db schema change or
new source of workflow state is needed.

## Generated glossary extract

Parse the committed Markdown's term tables using a small native Python reader. Select
only the term and meaning cells, preserving their text, and omit examples, prose,
commit-letter tables, CLI tables and implementation history. Handle escaped pipes and
inline-code pipes so a cell cannot be split into a false definition. Do not maintain a
second dictionary of definitions or summarize definitions with a model.

Use a deterministic order: first `task`, `task tracker`, `plan`, `step`, `attempt`, `session`,
`slot`, `land`, then the remaining core tables in document order. Term-name selection
may be in code; definition text must always come from the source. Prefer the core
work/execution, repository/machine, checks/delivery and conversations/evidence tables
over the implementation-detail table. Admit only whole rows; skip a row that does not
fit and continue with later rows. Never truncate a definition into a misleading fragment.

Use a conservative bound of 2,000 UTF-8 bytes for the entire rendered extract, including
its heading, separators and omission note. This also bounds byte-tokenized model input
to at most 2,000 tokens without introducing a tokenizer dependency. This intentionally
leaves room below the requested token ceiling. Test that the current glossary retains
all eight priority terms. Explicitly say the extract is partial and name the full file
for missing terms. Generate on input construction rather than checking in a cached copy.

A repository with no glossary gets a truthful absence statement, not this repository's
definitions or an instruction to search for a nonexistent file. A Git read failure,
invalid encoding, non-regular file, or malformed present term table must produce an
explained typed input failure before agent dispatch, not a silent empty extract or a
fallback full-document read. Use bounded reads. This repository's acceptance requires
a nonempty generated extract; absent-file handling only preserves generic factory use.

## Verification and delivery evidence

Add focused pytest behavior tests, reached through `steps` for step renderers:

- Both steps include all orientation directions, the supplied spec, the literal current
  check commands, and one bounded extract. No unconditional foundation reference or
  instruction to discover check commands survives.
- A different profile proves commands come from validated argv, including quoting of
  spaces and shell metacharacters. Selected-commit tests distinguish new branches,
  resumed branches, next steps and a ref moving before preparation.
- Editing a glossary fixture changes the rendered definition; example-column changes
  do not. Test complete-row budgeting, all priority terms in the actual glossary,
  escaped pipes, oversized definitions, and explained missing/malformed/read failures.
- Ordinary repeats and failed-check repeats retain the specification, check commands,
  saved-work instruction and exactly one extract, including when their source tree
  changes. Verify the prompt delivered to the semantic fake agent and retained evidence,
  rather than only testing a private formatting helper.

After the repository's declared environment is installed, run focused affected tests
plus required `just check` and `just test` under repository selection rules. The factory
input supplies those commands; this plan adds no document-discovery instruction. Do
not run a whole-suite or live attempt campaign as an agent. This planning change needs
no runtime test execution.

After deployment, collect at least six later attempts using the changed factory inputs.
Record attempt ids, step, factory revision, source commit and transcript references in
`docs/design/tl-8bh9.14.175/measurement.md`. Include both plan and implement and identify
repeats when available. Audit retained structured tool calls, including compound shell
commands and alternate file readers; reading a file with `sed`, Python or `git show`
counts just as `cat` does. This is offline evidence analysis, never workflow control.

For every sampled attempt require zero reads of AGENTS.md, SKILL.md, the justfile and
`.task-loop.json`, zero `bd prime`/`bd show`/other tracker invocations, and at most one
glossary read command. Record any foundation-plan read and whether the task's own plan
cited it. Fail the measurement for a violation; revise the input and sample again.

Use the original weighted method: each model call pays for its full input, including
repeated document output and the new extract. Report old orientation cost, new prefix
size, new orientation reads, call counts and net tokens for comparable attempt kinds.
The prefix/extract addition must cost less than the reads it removes. Report the expected
6–8% per-landed-task reduction as an expectation until matched evidence supports it;
separate plan-step accounting owned by `.192`. Glossary compliance remains a review
check. Unit tests alone do not satisfy the six-attempt acceptance criterion, and the
implementation must not be reported as fully measured before that evidence exists.
