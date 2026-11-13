# Dissect the factory's prompts

Task: `tl-8bh9.14.77`. Status: proposed study plan, 2026-11-13.

Produce a written inventory of the plan, implement and repeat-feedback prompts: what each part asks for, why it is
there, what it costs, and what real transcripts show it earns. The owner chooses any cuts. This task changes study
documents only; it does not change prompts, schemas, runtime code, instructions, dependencies or factory behavior.
Do not launch fresh agent attempts or prompt experiments as part of this study.

## Current basis

Source checked at `2e785034`:

- `src/taskloop/plan_step.py`: `input_text` places title, requirements and acceptance before `_closing_words`.
  Those words govern reading/reusing the plan, its directory, Git authority, listed commit paths and owner decisions.
- `src/taskloop/implement_step.py`: the same task prefix precedes the plan reference, implementation rules, file
  restrictions, dependency restriction, `ENVIRONMENT`, answer fields and completion/owner-decision instructions.
- Both modules own `ANSWER_SCHEMA`, decoding rules, reason-specific `OPENING` text and `repeat_instructions`, including
  the distinction between files not yet committed and cleanup after a commit.
- `src/taskloop/step_text.py` supplies the shared Git sentence and feedback frame: failure opening, delimited status
  listing as data, cleanup instructions, then attempt 1's complete input. Later repeats do not nest earlier feedback.
  `repeat.py`, `admit.py`, `admit_chain.py` and `attempt.py` connect this text to admission and launch.
- `evidence_files.py` owns stored `input.txt`, schema, answer, activity and diagnostic files. Activity and display reads
  have caps; the dashboard's prompt preview is not evidence that the complete input was read.
- [Real run 1](../self-hosting-real-run-1.md) identifies `tl-8bh9.14.13`, its plan/implement timings and the owner's
  observation that task text repeats by design; long paths and repeated reads are questions to measure, not findings
  already quantified. [Real run 2](../self-hosting-real-run-2.md) supplies additional cases involving environment
  friction, infeasible plans, answer rules and missing check feedback. Its historical behavior must be dated separately.

No existing plan was present. The slot's `bd show` found neither this task nor `tl-8bh9.14.58`; do not infer the latter's
requirements from its ID. The supplied owner request is sufficient to plan the study. Recover `.58` from the owning
tracker during evidence collection and cite its actual description, acceptance and linked discussion before claiming
that its weakness has been analyzed.

## Evidence collection

1. Recheck the above source at the study's checkout revision. Record both the present prompt and each sampled attempt's
   actual `input.txt`; use Git history to identify template changes rather than applying today's text retrospectively.
2. Read task details and linked owner discussion through the owning task tracker. Include `.58` explicitly. Use the
   configured tracker root; do not initialize a tracker or treat a passive export as current requirements.
3. Locate real run 1's plan and implement artifacts and their harness transcripts through the configured evidence and
   session readers. Use the report's task/date as the starting point. Inspect existing supported readers before choosing
   a read path; no new runtime reader or factory.db query layer belongs to this task. If session linkage is absent, a
   manually verified task/slot/time/input match may identify an existing transcript; document how it was verified.
4. Include every available attempt of that task. Add existing real repeat cases for uncommitted, unsafe and ignored
   files, and both committed/unrecorded cleanup branches where available. Use run 2's documented failures as targeted
   supplementary cases. List missing cases; do not create failures to fill the sample or imply run 1 exercised repeats.
5. In the report, record each sample's task, step, attempt, session when known, date, source revision, model/effort when
   recorded, input location, transcript location and stable line/event references, answer and verified result. Mark
   missing, truncated or unmatched evidence. Keep original artifacts intact and reference them rather than copying
   complete transcripts. Quote only the small excerpts needed to support findings; exclude credentials and unrelated data.

Factory state remains with its owning readers. Transcript analysis here is offline evidence for a person, never a way
to reconstruct execution state or drive workflow control. Missing evidence limits a conclusion; it is not a zero count.
If `.58` or required transcripts cannot be accessed, name the exact missing source and the access/location needed in the
report and handoff; do not present the study as fully evidenced until those gaps are resolved.

## Inventory to complete

Write `docs/design/tl-8bh9.14.77/report.md`. Give each independently actionable instruction or data section a row; split
the groups below further where their purpose or evidence differs. Include the exact text or source span, its origin,
steps/branches where it appears, purpose, size/repetition, observed response, evidence reference, limitations and a
proposed owner choice. Every row needs evidence or an explicit statement that its benefit is unobserved.

| Prompt part to inspect | Intended purpose to test against the transcript |
| --- | --- |
| Task title, requirements and acceptance, separately | Preserve task identity, scope and completion conditions across steps |
| Plan path and read-first instruction | Reuse a valid plan and carry its decisions into implementation |
| Plan reuse/rewrite and `needs_owner` conditions | Avoid unnecessary rewrites and surface work that cannot be planned |
| Implement/reuse, behavioral tests and plan updates | Turn the plan into a complete, verified change |
| Allowed files, forbidden paths, sizes and deletions | Keep edits inside what the factory can accept |
| Shared Git-write prohibition and factory commit ownership | Prevent rejected Git operations and establish who commits |
| Dependency, setup, network, temporary-file and check instructions | Make work feasible in the actual environment |
| `paths`, message, explanation and disposition instructions | Produce an answer the factory can decode and record |
| Removal of unlisted files and leftover warning | Leave a recordable slot without unrelated changes |
| Repeat opening for each reason | Tell the agent which failure to repair |
| Status listing, nonce markers and data warning | Name offending files while keeping filenames separate from instructions |
| Repeat restore/remove guidance and committed/unrecorded branches | Preserve intended work and select the correct next answer |
| Original task/prompt appended to repeats | Preserve scope without accumulating earlier feedback |

Inventory the structured answer schema and decoder constraints beside the prose, noting what the harness receives
separately and what the prose fails to convey. Record repository `AGENTS.md`, harness instructions, tool results and
session reuse as separate context sources where visible. Do not attribute their effects or costs to `input.txt`.
Checks run commands, not an agent prompt; inspect check output only where it informs the feedback analysis.

## Measurement and interpretation

- Count characters and UTF-8 bytes per part and whole stored input, plus how often each part is supplied across the
  sampled steps/attempts. Totals must reconcile. Distinguish repeated task data from added repeat instructions.
- Report recorded token usage, cache usage and elapsed times only at the granularity the artifacts provide. If an
  available tokenizer permits part-level estimates, name it and label those counts estimates. Do not equate characters,
  tokens, cached tokens, elapsed time or money, or assign an attempt's full cost to a single sentence.
- Mine tool calls for repeated reads of instructions, task plans and source files, repeated searches, long absolute paths,
  redundant displayed content, rejected operations and unsuccessful repair loops. For each candidate, cite the calls,
  count occurrences and returned bytes where available, and connect it to a specific prompt part or mark the link unknown.
- For repeated reads, distinguish the same unchanged content from changed files, different ranges, a new session, a
  truncated earlier response and a read needed for verification. Group by file/content and range when evidence permits;
  report unknowns. A repeated filename alone does not prove waste.
- Count repeated path occurrences and their characters/bytes separately in input, tool arguments and tool output. Show
  a few cited examples and a hypothetical shorter equivalent for owner review. Such savings are text-size estimates;
  they do not establish faster or more reliable execution.
- For benefit, trace an instruction to a visible action and result: a plan actually reused, an acceptance condition
  addressed, a forbidden operation avoided or attempted, a corrected listing, or a repeat repaired. Include failures and
  counterexamples. Compliance supports a purpose but does not prove the sentence caused it; silence proves neither
  usefulness nor uselessness. No controlled deletion experiment is authorized.

Analyze `.58` in a dedicated passage: quote its actual reported weakness, trace the relevant plan instructions to the
plan artifact and subsequent implementation behavior, and distinguish missing task information, weak planning guidance,
environment mismatch and downstream execution limits. Examine whether plans identify acceptance evidence, feasible
commands and protected resources, and whether long rediscovery substitutes for decisions the plan should have recorded.
Treat these as investigation questions until supported. Keep run 2's reported infeasible plans and absent check feedback
separate from `.58` unless its tracker record establishes the connection. Current feedback handles Git leftovers; do not
describe it as already providing failed-check repair instructions.

## Owner review and completion

End the report with a compact table of proposed choices: retain, shorten, remove, or supply at a different point. For
each, identify the affected part, observed benefit/waste, estimated text savings, risk to an enforced contract, supporting
references and confidence. Include unresolved evidence and questions. Leave an explicit blank owner-decision column;
none of the recommendations is authorization to change behavior. Future implementation belongs in separately approved
bounded tasks after the owner selects cuts, not in this study.

Completion requires coverage of all three prompt forms, every current repeat reason and cleanup branch (observed or
explicitly unavailable), per-part measurements, real transcript citations for findings, long-path and repeated-read
analysis, and the `.58` passage grounded in its actual record. The report must distinguish observed facts, report-only
leads and hypotheses. Review its arithmetic and spot-check every finding against the cited artifact, including contrary
evidence. No production tests, live runs or whole-suite gates are needed for these documentation-only changes; `justfile`
was read, and `just check`/`just test` remain the gates for a later approved code change.

Only this plan is produced by the planning step. The later study produces the report in this same task directory, with
any necessary small evidence tables there. Check the final diff and paths for scope and preserve all unrelated edits.
