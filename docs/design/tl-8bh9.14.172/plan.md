# Stop for an answer only after the agent turn ends

## Root cause and evidence

The harness events support reading **(a): the supervisor stopped executions without evidence that their turns had
ended**. They do not support reading (b), a completed turn with a prose answer. Both last messages are explicitly
`phase: commentary` in the Codex transcripts, and neither retained stdout stream contains `turn.completed` or
`turn.failed`. The first transcript's silence does not prove that a model call was still active; it also does not
prove completion. The second transcript records a reasoning item immediately after the commentary. Completion
must be established by the harness protocol, never inferred from silence or a message's prose.

The concrete defect is in the released **any-agent 0.9.0 Codex adapter and its interaction with the supervisor**:

1. `any_agent/harnesses/codex.py:CodexHarness._item` translates every completed `agent_message` into
   `events.Msg(text=...)`. `Msg.final` defaults to `True`. The retained `codex exec --json` messages contain
   `id`, `type` and `text`, with no phase, so this translation loses the distinction visible in the transcript.
2. `watch.Turn.apply` starts `done_t` on a final `Msg`. A subsequent parsed line without a final message or
   `TurnDone` calls `more()`, clearing that timer. Consequently earlier messages did not stop these executions:
   tools followed before the 120-second `ANSWER_GRACE_S` elapsed.
3. The fourth message in the first attempt was followed by no stdout event. Its incorrectly armed answer timer
   survived for 120 seconds. `Supervisor.poll` returned the `answer` stop verdict and stopped the owned worker
   tree. The same sequence occurred after the third message in the second attempt. The reasoning item present
   in that transcript was absent from stdout, so the supervisor never received it to clear the timer.
4. `CodexHarness.summary` then treats `e.last` plus `stop == "answer"` as proof of a final answer, even with zero
   completed turns. That promotes the commentary into `answer.txt` (`answered=1`, `stands=1`). The factory's
   strict decoder records `json_invalid`; the negative exit code is independently classified as `killed`, whose
   higher-priority execution failure produces `run:killed` and hold cause `failed:run:killed`.

Read-only inspection on 2026-11-14 used `factory.db` and the owning artifacts under
`~/.local/state/task-loop/artifacts/attempts/`:

| Attempt / task | Artifact directory | Messages and following activity (UTC) |
| --- | --- | --- |
| `750de0ec3e7b4d3e81d6f63e174eaf41` / `tl-8bh9.14.145` | `5f4377c14bb6abf508d78d431a6f0c8384016caf55652ce1dcb8493848e04ee3` | `events.jsonl` indices 0, 13, 42 have following activity after 2.174, 1.668, 0.658 seconds. Index 75 is commentary at 07:07:09.632 with nothing following; reported kill is 07:09:11. |
| `aaba892b2b234c01beef71f76fbc36de` / `tl-8bh9.14.165` | `c57b97d76af131f6ec6603c61c38d2c0f56c70a0365c1119c41a7ed66b124759` | Indices 0 and 29 have following activity after 3.354 and 0.411 seconds. Index 54 is commentary at 08:05:56.767 with nothing following on stdout; reported kill is 08:07:59. |

The stdout files have 78 and 57 lines respectively; both have `turn.started` and no completion event. Their last
messages match `answer.txt`. Both execution rows confirm `rc=-9`, `stop=answer`, `reason=killed`,
`answer_kind=json_invalid`, with no turn usage. Both entry logs report
`collected run:killed verify=not_applicable claim=held release=released`.

Transcript references are the supplied `rollout-2026-11-14T07-02-53-01a1d8dd-bd15-7543-a19c-59edbc2c5371.jsonl`
and `rollout-2026-11-14T08-02-42-01a1d914-7f4a-7871-83dc-29454ee2823c.jsonl`, under
`~/.codex/sessions/2026/11/14/`. The last message of the first has commentary phase at 07:07:09.631; the second
has commentary at 08:05:56.766 followed by reasoning at 08:05:56.769. Neither has a task/turn completion record.

A process-free replay against the installed release reproduced the mechanism: a raw completed `agent_message`
parses as `Msg(final=True)`; advancing an injected clock to 121 seconds produces `Turn.verdict == "answer"`
and summary `answered=True` without `TurnDone`. Replaying a following tool event clears the verdict. This is
evidence of the current defect, not verification of the proposed fix. An activity record's `s: finished` means
that the message was emitted; it does not mean that the agent turn finished.

The measured cost remains **2.53M input tokens, 2 of 10 plan attempts, 4.9% of the 51.4M-token window**, using
the owner's measurements (1.79M and 0.74M). The known redo `4ba6f6f69511425298185507b3f2c5f9` added 0.81M.
The first attempt had no written plan and remained held at measurement time. This is the estimated avoidable
cost, including the separately stated redo cost; future savings must be measured rather than guaranteed.

## Required behavior

Only the final answer of a completed agent execution may trigger an answer stop or become its answer. A
commentary message remains activity even across a gap longer than the answer grace. Tool calls need not follow
within 120 seconds to keep a turn alive. Existing execution deadlines and stall/silence protections still apply.
A final prose answer remains `json_invalid`; valid JSON that violates the step contract remains `schema_invalid`.
Answer completion and answer validity are separate decisions.

Every newly constructed plan input must begin with this exact sentence, before the task title or repeat feedback:

> Your final message must be the JSON answer only; write plan.md before you answer; a message without a tool call ends the step.

Retain those owner-requested words verbatim as guidance to the agent. The last clause is not a rule for the
supervisor: commentary without a tool call does not itself establish completion. The existing `unchanged` and
`needs_owner` instructions retain their meanings; the warning does not require rewriting a valid plan or writing
one for an unplannable task.

## Implementation

### 1. Correct completion in the owning agent library

Implement and test a bounded fix in shelf's `packages/any-agent`, then consume its released version here.
`taskloop.composition._run` delegates execution to this library; the factory must not copy the parser,
read Codex rollout files for control, monkeypatch the installed dependency or implement another process owner.
An upstream release containing this behavior is an implementation prerequisite, not something this plan claims
already exists. Its publication follows the shelf owner's workflow and authority.

- In the Codex parser, emit completed message items as non-final activity and retain the most recent candidate
  answer for the current turn. The phase-less stdout format in these failures must work; optional phase metadata
  must never be required to recognize commentary safely.
- Confirm completion from `turn.completed`. Emit the existing typed `TurnDone` even if usage is absent, with
  optional usage rather than suppressing completion. At that point the last message is eligible as the final
  answer. Keep terminal confirmation and candidate text distinct so a later tool/turn cannot reuse stale text.
- In the Codex summary, remove the circular inference that `stop == "answer"` proves `e.last` was final.
  Select answer text only from confirmed completion or the current execution's successfully written terminal answer file.
  A partial/error exit with only commentary must not expose that commentary as an answer or set `answered` or
  `stands`. Preserve genuine process failures and the normal missing-answer result.
- The existing supervisor may apply its answer grace after confirmed turn completion. No longer grace interval,
  JSON sniffing, phrase matching or prompt-only mitigation can substitute for this fix. Do not require valid JSON
  to recognize a completed turn: a completed prose answer must still reach the strict decoder.
- Keep backend event details inside the adapter. Reuse existing typed events and injected clocks; add no factory
  vocabulary, schema, signals, subprocess calls or state inferred from logs. Leave other harness protocols with
  their existing completion semantics and run their relevant library contract tests.

Update `pyproject.toml`'s dependency/source pin and `uv.lock` to the released fix. Preserve the documented
any-agent/stream-proc source-commit alignment, updating the companion pin if required by the release. Record
the actual release version and commit during implementation; do not invent a future tag or use a local override.
No unrelated shelf upgrades belong in this change.

### 2. Put the warning first in plan inputs

In `src/taskloop/plan_step.py`, own the exact warning in one constant. Prefix both `input_text` and `feedback`
with it so first admissions, newly constructed held-task admissions and all ordinary plan repeats start with
the warning. The shared `step_text.feedback` frame must not move it behind the repeat opening. Keep task prose,
status markers, Git instructions, answer schema and commit-path rules intact. The launcher already appends the
schema after the prompt, so adding the warning only there would miss the retained admitted input.

Use existing admission and repeat paths: `StepRepeat._input` wraps the first attempt's retained input via
`plan_step.feedback`, and each repeat needs its own leading warning. Preserve stored input digests on restart;
do not rewrite evidence or reconstruct past attempts to inject new text. Newly generated inputs get the warning;
already admitted inputs remain their original immutable evidence. Runtime versions remain fixed until restart.

### 3. Verify through the production boundaries

Add focused pytest behavior tests in the owning library and the factory. Use public parser/supervisor entry
points with an injected clock, plus the released semantic execution fake where appropriate. Do not create a
fake that simply returns the desired answer and call that proof that commentary is safe.

1. Replay a minimal structured stdout sequence matching the failures: start, tool completion, commentary,
   **more than 120 seconds of quiet**, then another tool, another message and a confirmed final JSON answer.
   Poll through the quiet interval below the existing stall/silence limits. No answer stop occurs there; work
   continues in the same execution. After `turn.completed`, only the final JSON becomes the answer and the
   existing answer grace can stop a worker that fails to exit. Include several commentary messages followed
   promptly by tools to explain the original earlier-message behavior.
2. Cover commentary followed by reasoning, and commentary with no further stdout for the same quiet interval.
   Both must remain unfinished. Include the phase-less wire format, rather than testing only an explicit
   `Msg(final=False)` constructed by a test. Assert partial/error exit without terminal confirmation does not
   promote commentary to an answer. Keep existing timeout/stall tests passing so unfinished work remains bounded.
3. Complete a turn with prose, finish normally with `rc=0`, and send its real harness summary through the
   factory's existing strict answer path. Assert `answer.kind == json_invalid` and `answer:json_invalid`, without
   an automatic repeat from commentary. Also retain valid JSON acceptance and schema-invalid rejection. Existing
   `tests/steps/test_agent_launch.py` decoder coverage across all harnesses remains relevant.
4. In factory tests, replay the released parser/supervisor behavior through the existing execution boundary and
   verify one attempt/session persists until the final answer, with no early capture/hold. Keep source control
   and process effects behind the existing semantic fakes. A small regression file such as
   `tests/steps/test_agent_completion.py` can hold this contract without broadening unrelated test imports.
5. Extend `tests/steps/test_admit.py` and `tests/steps/test_repeat.py` to check the exact warning at byte zero in
   retained fresh and repeat input and in the launched prompt. Update `TrackingTaskAdapter.claim`'s current
   `startswith(bead.title)` assumption to check the warning followed by the title. Preserve existing assertions
   for task content, safe status blocks, repeat semantics and unchanged implementation-step prompts.

Before implementation gates, read the current justfile and run `just install`. Run the owning library's focused
parser/supervisor tests, then `just check` and `just test` in the successor worktree (the current `just test`
explicitly selects `tests/cli tests/steps tests/rules`). Use the installed environment and frozen isolated Python
for additional selected tests: `uv run --frozen --no-sync python -I -m pytest ...`. Run no whole-suite/live agent
tests, baseline imports, editable overrides or real model calls. Maintain the existing file/function/test size
caps, import contracts and typing policy.

## Completion and rollout

Completion requires the root-cause regression to fail against 0.9.0 and pass with the released fix, factory
completion/decoder tests passing, and both fresh and repeated plan inputs beginning with the exact warning.
Prompt text alone does not complete this task. This change needs no database migration and no historical
execution reclassification. Restart the factory to adopt the new installed runtime; retain existing evidence,
claims and explicitly held tasks. Do not restart the two held tasks automatically or spend tokens retrying them
as validation. Assess subsequent token savings separately from this task's deterministic acceptance tests.

Planning baseline: `99655d38c09be07198ad0f5c0876d3d25a559a65` on the assigned task worktree. No existing plan or
task-local WIP commit was found; the ancestor WIP trailer inspected belongs to `tl-8bh9.14.160`, not this task.
This planning change contains only this document; code changes and their gates belong to implementation.
