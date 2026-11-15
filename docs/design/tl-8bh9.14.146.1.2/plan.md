# Header
Task: tl-8bh9.14.146.1.2
Base: cd64b25ec06d8255e15670a51b0aee06d3889bc9
Depth: medium
Reason: two owning modules; no missing owner decision or unlanded dependency.
Evidence budget: 12 model calls.
Size: 8 changed files, 1 independent behaviour, 40 implement model calls.

## Outcome and non-goals
Land and hold guidance explains the situation and the human decision in prose. Preserve the already command-free pending-hold and terminal-conflict paths. Remaining gaps are command recipes in land tables/restart advice and hold recovery advice, including forwarded cause fixes. Admission, step-guide text, other renderers' own messages, tracker comments, and execution policy belong outside this change.

## Settled decisions
- Keep existing guide lookup keys, function interfaces and rendering precedence.
- Preserve automatic versus manual land, retained work, retry safety, and approval/claim ownership distinctions.
- Terminal conflict holds stay held; ordinary recovery wording must not offer their restart.
- Rewrite advice at these two producers; do not modify sibling-owned producers or filter arbitrary rendered text.
- Source and test edits are followed, last, by one `just check 2>&1 | tail -60` and one `just test 2>&1 | tail -40`; inspect both command exit statuses.

## Open decisions
- None.

## Change map
- `src/taskloop/land_guide.py` — `restart`, `RERUN`, `LAND_NEXT`, `LAND_GUIDE`, `RELEASE_RERUN`, `CANDIDATE_RELEASE`: replace commands and option instructions with situation, retained effects and decision; retain `INTERRUPTED`.
- `src/taskloop/hold_guide.py` — `ON_HOLD`, `hold_guide`: describe answers, approval restoration, manual ownership and closure in words; stop forwarding command-bearing fixes; retain terminal/pending behavior and `hold_lines` facts.
- `tests/steps/test_guide_words.py` (new) — parametrized public-guide coverage using both guide modules and `step_render.human`: exercise static entries and dynamic hold/restart branches, asserting meaningful prose and absence of command instructions.
- `tests/steps/test_conflict_recovery.py` — replace the command-recipe assertion on `restart` with retained-work/restart meaning; keep recovery operation tests.
- `tests/steps/test_hold_status.py` — replace command and flag expectations with cause, ownership and decision expectations through `human`.
- `tests/cli/test_land_cli.py` — revise the target-moved/remote-refusal guide prefix assertion; retain fact/guide separation.
- `src/taskloop/step_render.py` — consult `human`, `_guides`, `_round_lines`: dynamic holds, candidate-release overrides and pending guide placement; no edit.
- `src/taskloop/land_render.py` — consult `failed_lines`: land guide dispatch; its own summary/success text is outside scope.
- `src/taskloop/step_guide.py` — consult `GUIDE`, `refusal_guide`, `guide`: imported constants and lookup precedence; no edit.
- `src/taskloop/show_render.py` — consult `show_lines`: `hold_lines` placement; no edit.
- `src/taskloop/hold_cause.py` — consult `TerminalCause.explanation`, `cause`, `next_step`: terminal policy and command-bearing cause/fix composition; no edit.
- `src/taskloop/round_guide.py` — consult `automatic_guide`: existing pending-hold explanation path; no edit.
- `src/taskloop/cli_step.py` — consult `_land`: `INTERRUPTED` result production; no edit.
- `src/taskloop/exit_codes.py` — consult `exit_code`: interruption identity remains stable; no edit.
- `src/taskloop/operations.py` — consult `Failed`: guide context flags; no edit.
- `src/taskloop/land_push.py` — consult `_moved`: target-moved diagnostic producer; no edit.
- `tests/steps/test_land_status.py` — consult `lines`, land/release presentation assertions for new rendered coverage.
- `tests/steps/test_hold.py` — consult pending-hold rendering coverage; no edit.
- `tests/steps/test_hold_text.py` — consult existing automatic-comment command exclusion; comments remain outside scope.
- `tests/cli/test_refusal_guidance.py` — consult override, forwarded-reason and pending-hold coverage; no edit.
- `docs/design/tl-8bh9.14.146.1.2/plan.md` — bounded implementation contract.
- `docs/design/tl-8bh9.14.146.1.2/plan-metadata.json` (new) — preparation commit and consulted paths.

## Read list
- `src/taskloop/land_guide.py:9-165` — all land advice producers and release overrides.
- `src/taskloop/hold_guide.py:15-90` — constants, facts and dynamic recovery composition.
- `src/taskloop/hold_cause.py:18-33` — terminal holds; also `154-171` for cause/fix composition.
- `src/taskloop/round_guide.py:106-140` — pending-hold delegation.
- `src/taskloop/step_render.py:71-100` — status and refusal dispatch; also `136-143` for pending holds.
- `src/taskloop/land_render.py:62-72` — land failure guide placement and scope boundary.
- `src/taskloop/step_guide.py:189-193` — imported constants; also `246-269` for lookup precedence.
- `src/taskloop/show_render.py:160-170` — hold fact rendering.
- `src/taskloop/cli_step.py:285-294` — interruption producer.
- `src/taskloop/exit_codes.py:51-56` — interruption result consumer.
- `src/taskloop/operations.py:111-120` — failure context.
- `src/taskloop/land_push.py:191-194` — target movement fact.
- `tests/steps/test_conflict_recovery.py:90-103` — obsolete command expectation and recovery distinction.
- `tests/steps/test_hold_status.py:93-109` — terminal invariants; also `210-241` for changed advice assertions.
- `tests/steps/test_land_status.py:75-97` — public land next guidance; also `244-259` for release overrides.
- `tests/steps/test_hold.py:596-603` — public pending-hold coverage.
- `tests/steps/test_hold_text.py:73-78` — existing comment boundary.
- `tests/cli/test_land_cli.py:229-244` — prefix expectation to revise.
- `tests/cli/test_refusal_guidance.py:53-79` — existing dispatch and command-free presentation coverage.

## Contract
Intent: explain the current land/hold situation and the decision needed to proceed. Effect: existing renderers select replacement prose through the same interfaces; no tracker, Git, process, schema or state mutation is added. Result: nonempty, context-specific guidance without runnable commands or CLI option instructions. Keep existing typed results, stored fields, lookup keys and interruption identity. Dynamic advice must avoid importing command instructions through cause fixes; preserve cause attribution and express recovery choices in words. Pending and terminal paths retain their current semantics. Test factory-authored guidance separately from arbitrary diagnostic text supplied by adapters or agents.

## Work packages
1. Rewrite both guide producers and revise stale wording assertions in the three existing test files. Closes A1 through A3 without changing execution behavior.
2. Add `tests/steps/test_guide_words.py` against the public producers and existing rendering integration points. Cover every static entry plus recorded/unrecorded, pending, terminal, missing/closed and foreign-claim hold branches, timeout, moved branch and lost claim. Closes A1 through A3; run the two required gates last.

## Acceptance behaviours
A1. Every land next/refusal/release guide and restart explanation states the situation and decision without a runnable command or CLI option instruction, including when selected through public rendering.
A2. Hold guidance gives the cause and owner choice without command instructions for answers, approval restoration, manual continuation or closure; it respects labels and claim ownership.
A3. Pending holds keep their reason and waiting condition; terminal conflict holds preserve work and remain held without restart advice, while existing dispatch precedence and interrupted results remain intact.
