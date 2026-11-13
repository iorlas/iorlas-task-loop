# Reduce agent friction in factory steps

Task: tl-8bh9.14.135. Planned 2026-11-13 against this successor checkout.

Implement items 1, 2, 5 and 7 from the supplied assessment, then record their effect on the next real attempts:
focused tests inside the agent sandbox, complete task and command orientation, no tracker commands from step agents,
and an unsafe-path explanation that identifies both the path and its cause. This plan is an implementation input;
neither the reported assessment nor this plan is fresh measurement evidence.

## Current behavior and scope

- `justfile` installs the successor package before both gates. `just test` selects all of `tests/cli`, `tests/steps`
  and `tests/rules`, including dashboard HTTP tests; it is not an appropriate focused agent command.
- `.task-loop.json` requires `just check` and `just test`. Its setup is already `just bootstrap`, which installs the
  package and warms the pinned ruff, pyrefly and import-linter tools. Preserve these factory checks and setup.
- `implement_step.ENVIRONMENT` expressly tells the agent to run every profile check, contradicting the repository's
  prohibition on agent whole-suite tests. The generic template must stop requiring that.
- Both step inputs already contain the task title, requirements and acceptance. Implement already names
  `docs/design/<task-id>/plan.md` and says it is committed on the branch. Preserve and test these behaviors.
- Root `AGENTS.md` calls both recipes focused gates, while the beads skill unconditionally starts with `bd prime`.
  A step-specific exception must resolve both sources of misleading guidance.
- `factory_commit.refusal` already puts the unsafe path first in its bounded listing. Its safety check discards the
  particular cause, and both step kinds print a list of possible causes. Extend this behavior rather than replace it.
- Dashboard tests in `tests/cli/test_dash_server.py` and `test_dash_composition.py` create loopback servers without a
  capability fixture. Several tests in those files need no socket and should continue running when sockets are denied.

The task owns these prompt, instruction and test changes and a small measurement record. It does not own the broader
prompt/agent configuration design of tl-8bh9.14.117 or a new plan format. No `.117` plan is present in this checkout;
preserve the existing plan and answer format. Do not introduce a prompt registry, profile keys, another instruction
file, database schema, telemetry service, scheduler behavior or new runtime dependency. Tool warming already exists: no wheel search or second
installation mechanism is needed. Items about file maps, the long outlier, missing setup logs and token counts are not
additional acceptance requirements for this change.

## 1. Put actionable orientation in the supplied prompt

Keep factory rules in the generic step text and repository commands in root `AGENTS.md`.

For every fresh plan and implement input, put a short shared orientation before the task prose:

- The factory supplies the task text and owns tracker access and task-state operations. The tracker is unavailable
  inside this step; use the supplied requirements, and report a missing requirement through the existing answer.
- Run focused behavior/contract tests only. The factory runs the complete configured checks outside the agent
  sandbox. An agent's checks are feedback for its work, not factory passes.
- Respect the step's write scope: a plan-only or unchanged attempt need not install or run code merely to report it.
  An implement attempt verifies its changed behavior and runs the repository's lint/type/import check command.

Remove the implement requirement to run every profile check. Preserve the offline/setup explanation, Git-write
prohibition, dependency restriction, answer contract, task prose and explicit committed plan reference. The plan
prompt must explicitly name its expected plan path too. A repeat must retain the original orientation once, without
nesting old feedback. Do not duplicate or truncate requirements to make room for guidance.

Add one short section between these exact HTML comments in root `AGENTS.md`:

```text
<!-- BEGIN FACTORY STEP INSTRUCTIONS -->
<!-- END FACTORY STEP INSTRUCTIONS -->
```

Its actual contents must state:

- In a factory agent step, do not run `bd`, including `bd prime`, `bd show` or task mutations, or invoke the beads
  workflow. The complete task is supplied; the factory manages the tracker. This exception precedes the general
  Beads workflow. Also add that exception before the first-step instruction in `.agents/skills/beads/SKILL.md`.
- Before running successor code or checks, run `just install`. Use `just check` for lint, types and import rules;
  the factory already prepared its pinned tools. No network is available. If preparation is missing, report the
  failing command rather than installing dependencies or searching caches for wheels.
- For focused tests use `uv run --frozen --no-sync python -I -m pytest -q <selected test paths>` with concrete paths
  selected from the changed behavior. Do not paste the placeholder literally. Run no whole-suite or live tests.
- The factory runs `just test` outside the sandbox. Dashboard HTTP tests need loopback sockets, which the agent
  sandbox can deny. Socket permission errors are not a reason to rerun the full suite.

Rewrite the existing Build and verification paragraph to agree with this split. Preserve the same required factory
checks; this change does not weaken `.task-loop.json` or make an agent's focused tests sufficient for delivery.

To meet literal command inlining, copy that section into the existing admitted input artifact. Use a small bounded
reader/parser, not a second prompt system:

1. Read only committed root `AGENTS.md` from local `refs/heads/main` through the existing Git committed-file port
   (`ProfileFiles.blob` / its adapter). This is repository policy, like required checks, not code under test. State
   this source in the reader's contract. Never inspect a dirty checkout, fetch, or follow a symlink for instructions.
2. Missing local `main`, missing `AGENTS.md`, or no section means no optional repository section. Generic step rules
   still apply. Do not substitute a different ref or instruction file.
3. Accept one UTF-8 section, with a 64 KiB file cap and an 8 KiB section cap. Reject duplicate, reversed or unmatched
   delimiters, invalid encoding, oversize content and a nonregular Git entry as an input refusal with an explanation.
   Git read failures stay unavailable Git reads, not absence. Use existing admission result categories.
4. Snapshot once for each fresh plan/implement admission, before `put_input` and before any claim/reservation write.
   Wire the read port at the existing composition root. On advance, snapshot the current policy anew. Repeats use
   attempt one's stored input and never reload or append the section again. Its text is covered by the existing
   input digest and artifact; no new factory state or launch-time prompt rewrite is needed.

The section is an optional part of the sole instruction file, not a general template language. Generic step modules
remain free of hardcoded `just`/`pytest` recipes. Align the glossary's existing profile/setup description with the new
agent-versus-factory verification responsibility; do not add vocabulary or rewrite historical plans.

## 2. Skip only socket tests when loopback capability is denied

Introduce a fixture local to the CLI tests that attempts to create and bind an IPv4 TCP socket on `127.0.0.1:0`, then
closes it before the tested server is started. Skip with a concise socket-denied explanation only for `EACCES` or
`EPERM` from that capability probe. No sandbox-name detection, broad exception catching, retries, global test skip
or production dashboard fallback.

Require the fixture for `served` and for the composition tests that bind sockets directly. Keep the markup/static,
Hub-only and no-dashboard tests active without sockets. Unexpected probe errors and failures from the actual server
after a successful probe must fail normally. A permitted host still executes the HTTP and occupied-port behavior.
The factory's full test command and production dashboard error handling stay unchanged.

Use focused pytest coverage to show the denied capability selects a skip, permitted capability executes the tests,
and a different socket error is not suppressed. Exercise the real dashboard tests where the current environment
allows them; do not launch live factory work to prove this fixture.

## 3. Explain the exact unsafe path in repeat feedback

Carry a typed diagnostic from the existing safety decision: the listed path, the offending ancestor/component when
different and known, and the specific cause. Closed causes are a stdlib enum with one prose rendering; they must
cover the actual current policy branches (Git path, nonregular entry/ancestor, symlink, executable, size, disallowed
deletion, unreadable content and sensitive content as applicable). Keep the existing `unsafe` repeat category and
the safety policy. Do not accept a path previously refused or expose credential bytes in an explanation.

Return the diagnostic from the same checks that identify the refusal in `factory_commit.py`; do not re-probe a path,
parse a status listing, inspect display logs or infer a cause from exception text. Add it to the typed unsettled
result and pass it to both plan and implement feedback. A child beneath a symlink must name the child and the
obstructing ancestor rather than leave the agent to run `namei`.

Render path data using the existing escaping and nonce-marker protections in `step_text.feedback`. Keep the complete
bounded leftover listing and cleanup/relisting instructions. Clearly distinguish the specific refused path from the
other leftovers. Account for the current frame's claim that all enclosed names came from `git status`: the safety
diagnostic can name an ancestor not present in status, so that description must remain truthful. Preserve bounds
and prevent filenames containing controls or marker text from becoming instructions. No database change is needed:
the repeat already obtains fresh verification data and stores its complete input through the evidence owner.

## Implementation and focused validation

Deliver the orientation/fixture changes first, then the diagnostic change. Use the existing module boundaries; split
small pure parsing/rendering code only where necessary to preserve the 400/80/800 caps. New edge models use pydantic
v2 where needed; internal values stay typed. No subprocess, signal, `Any`, cast or ignore escape is introduced.

Relevant paths, so implementation can start without guessing filenames:

| Concern | Source / instructions | Focused contracts |
| --- | --- | --- |
| Generic prompts | `src/taskloop/step_text.py`, `plan_step.py`, `implement_step.py`, `steps.py` | `tests/steps/test_steps.py` |
| Admitted prompt snapshot | `src/taskloop/admit.py`, `admit_chain.py`, `composition.py`, committed-file adapter in `git_views.py` | `tests/steps/test_admit.py`, `test_admit_chain.py`, `test_advance.py`; a small parser contract test if needed |
| Repeated prompts | `src/taskloop/repeat.py`, step feedback functions | `tests/steps/test_repeat.py`, `test_repeat_dispatch.py` |
| Safety explanation | `src/taskloop/factory_commit.py`, `attempt_types.py`, `slot_state.py` | `tests/steps/test_verifier.py`, the repeat tests above |
| Socket capability | `tests/cli/test_dash_server.py`, `test_dash_composition.py`, local CLI fixture | Those tests plus focused capability-denial coverage |
| Repository guidance | `AGENTS.md`, `.agents/skills/beads/SKILL.md`, `docs/glossary.md` | Prompt admission assertions and instruction consistency review |
| Existing environment | `justfile`, `.task-loop.json`, `src/taskloop/environment.py` | Existing `tests/steps/test_environment.py`, `test_attempt.py` contracts as affected |

Meaningful assertions must cover exact commands in stored input, complete task text and committed plan path, removal
of the every-check instruction, neutral generic templates, committed-policy selection despite dirty worktree edits,
optional absent section, malformed section refusal before claims/reservations, advance without a new claim, and a
repeat retaining its original section after policy changes. Verify both step kinds' concrete unsafe explanation,
an obstructing symlink ancestor, safe hostile-name rendering, and cleanup followed by successful verification.

After implementation run `just install`, `just check`, and selected tests through
`uv run --frozen --no-sync python -I -m pytest -q <concrete affected test files>`. Include the prompt/admission,
repeat/verifier and dashboard contracts above and any new parser/capability contracts. Run the environment tests
only if their wiring changes. Do not run `just test` or `tests/steps/real` as an agent. The factory runs the unchanged
required `just check` and `just test` checks on the resulting code outside the sandbox; its host run must execute
the dashboard HTTP cases with sockets permitted. Record any skipped host cases rather than calling them coverage.

## Next-real-attempt measurements and completion

Once the change is active, observe the next five completed plan/implement agent attempts, including repeats, without
starting artificial factory work or changing task scheduling. Record each attempt's task ID, attempt ID, step,
sequence/number, code revision, retained input reference and evidence references in
`docs/design/tl-8bh9.14.135/measurements.md`. Keep every observed attempt, including failures and outliers.

Use existing typed activity readers (`EvidenceFiles.activity_after` from the initial cursor, paging to the end) and
owning attempt/evidence readers. Count unique command activity IDs across start/finish records and pages, not the
dashboard's last 20 events. Record commands per attempt, nonzero command exits, elapsed agent minutes, all `bd`
invocations, full-suite invocations, and failed tracker/test calls with their reasons. Use actual retained start/end
evidence for elapsed time and state the endpoints; separate setup/check-step time and any release delay.
`EvidenceFiles.started_at` is input-file admission time, not agent launch time; do not label that interval agent time.
Missing, unfinished or capped evidence is unknown or a lower bound, never zero. Command classification is read-only analysis
of typed activity, not workflow control from log text. No new telemetry or factory tables are required.

Summarize totals, median and range separately for plan, implement and repeats. The supplied 15-attempt assessment is
an unverified historical comparison; recompute comparable baseline values only if the retained evidence is available.
Do not claim verified token savings or fabricate missing baseline values. Include the host check results and socket
skip/execute counts. For any naturally occurring unsafe repeat, show its stored prompt names the path and precise
cause; if none occurs, say so and cite focused tests for that behavior.

Completion requires the focused contracts and factory checks to pass, the new prompts to contain the guidance, and
the next-attempt record to demonstrate no step-agent tracker calls or whole-suite calls and no socket-permission
test failures. Explain any violation and correct it before claiming the task complete. Report command/minute changes
without inventing a performance threshold for differing tasks. If real attempts have not happened yet, implementation
can be reviewed, but measurement and task completion remain pending; do not simulate a result or claim this plan fixed
the observed friction. Preserve existing attempts, worktrees, claims and evidence throughout.
