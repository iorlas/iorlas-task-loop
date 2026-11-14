# Depth
Medium: two behaviours—automatic landing exactly once, and matching CLI/dashboard landing status under manual or unknown policy. No missing owner decision or explicitly unlanded dependency; the supplied discussion records the shelf prerequisite as landed. Evidence budget: 12 model calls total.

## Size
Estimate for one implement attempt: 27 changed files including this plan, tests and any test artifacts; two independent behaviours; 65 model calls. This includes selective reuse of unfinished parent work, not its entire 32-file diff. No database schema version change is needed for this part.

- Automatic landing: under auto policy, a released passing checked attempt lands whether labelled or hand-started; subsequent rounds and re-entry produce one delivery and one task completion, without another plan or implement attempt. Acceptance: semantic Git/tracker tests run the application land operation, observe one push and close, then repeat reads and rounds without another delivery.
- Policy and status: manual and unknown policy prevent automatic delivery and give matching CLI human/JSON, dashboard card and task-detail status. Acceptance: a label-by-policy matrix demonstrates identical decisions and explanatory words, zero pushes/closes for manual or unknown, and no false promise of automatic landing when policy cannot be read.

## Scope and evidence
The source is 81e5f3a1. This task has no existing plan or local edits. The supplied glossary definitions suffice; no new vocabulary is proposed.

`round_land._waiting` currently requires a non-null admission label. `round._run_round` supplies a snapshot taken before settling and filters it only by backlog. `land_status.land_next` already distinguishes waiting from completed delivery. The dashboard separately maps unreadable policy to `waiting`, while CLI status has no policy context. These explain the admission-label exclusion and inconsistent presentation.

The parent branch `task/tl-8bh9.14.155` retains unfinished commits, including b65113b8 with a `Task-Loop-Wip:` trailer, followed by merge 64388e4f. Its diff contains useful eligibility, repository identity projection, policy reads and hand-started tests, alongside unrelated conflict/hold/schema changes. Treat all of it as unverified input. Port selected hunks into current source; do not merge or cherry-pick the parent wholesale. Preserve the parent branch and its saved work. The child branch currently contains no earlier WIP of its own.

Conflict execution, merge preservation, persisted resolution attempts and resolved-candidate validation belong to parts 2 and 3. This part uses existing land delivery, locking, close and reconciliation operations. Do not introduce execution state, schema changes, new merge operations or baseline imports.

## Implementation
1. Project the existing stored repository identity through `AttemptRow` and `AttemptView`, keeping SQL and row decoding inside the owning reader. Add explicit policy-read and repository-observation ports using the existing Git shelf. Missing or mismatched repository evidence must yield unknown policy, never auto. Avoid depending on a reusable slot still containing the completed task's checkout.
2. In the round, select land candidates from the requested backlog and repository. Refresh the status snapshot after settling so a released checks attempt can be seen accurately. Admission labels govern ingestion, not delivery eligibility. Require released, passing, non-abandoned checks, and respect held, abandoned, running, release-pending and landed states. Keep oldest-release ordering and at most one task landed or held per round. Preserve graceful stopping, slot reservation and the global capacity calculation; exclude a just-completed task from stale admission capacity. Do not change unrelated hand-started advancement or repeat policy.
3. Continue through `land.land` with the round's existing choices. Its durable candidate/delivery/close observations and locks remain authoritative across repeated calls; do not add an in-memory delivered set or derive control state from round logs. A terminal change refusal must continue through the owning typed hold operation rather than become an endlessly repeated delivery. Retain existing retry behaviour for unavailable observations. Keep the existing hold storage contract; do not import the parent's conflict-specific hold/schema changes.
4. Read policy for status from one resolved, last-known origin main commit through the existing profile reader; never read the working-tree profile. The scheduler continues to fetch before authorizing auto landing. Status reads do not fetch or mutate Git. A missing profile key retains the existing manual default; missing refs, invalid profile or unavailable repository observations remain unknown. Both CLI and dashboard consume the same status policy port, tied to the attempt's repository, rather than the dashboard applying a second independent cached decision.
5. Reuse the existing `LandState` concept, moving its ownership into shared land/status reads and making the touched closed vocabulary an enum. Add an explicit unknown value. Keep `task_status` and its word renderer as the single presentation decision; active observed landing and completed delivery retain precedence. Attach the shared decision to the attempt view/status and expose its explanation in CLI JSON as well as human output. Remove duplicate dashboard inference and unnecessary mode plumbing in board/task composition. No new policy table or persisted policy cache is needed.
6. Update cards, drawer and rail to consume that decision and its server-provided words. Unknown must say that landing policy is unavailable, manual must say it waits for a person, and auto must say it waits for the factory. Remove the drawer's unconditional next-round promise for unknown policy. Messages describe the situation and decision in words, without asking the owner to run a CLI command.

New files: `tests/steps/test_hand_land.py` will integrate the existing land bench, round entry point, status readers and renderers for the acceptance matrix. A small `tests/dash/hand-land.test.js` may exercise the existing UI exports/renderers for unknown/manual/auto wording. No new runtime module is required; existing land/status modules own the added values and decisions.

## Read list
- `src/taskloop/round.py:109-206` — round ports, snapshot, landing call, repository filtering and capacity integration.
- `src/taskloop/round_land.py:19-68` — labelled eligibility, policy authorization, ordering and shared land call.
- `src/taskloop/attempt_reads.py:298-330` — stored repository identity projection and typed row decoding; inspect its row declaration when adding the field.
- `src/taskloop/attempt_status.py:180-240` — checks-view producer and agent identity propagation; update its port/view declarations consistently.
- `src/taskloop/land_mode.py:9-61` — existing fetched and read-only policy readers and cache ownership.
- `src/taskloop/land_status.py:25-79` — shared land read values and terminal/release precedence.
- `src/taskloop/task_status.py:59-145` — shared status, eligibility and explanatory word ownership.
- `src/taskloop/cli_composition.py:114-191` — read-only status and round composition producers.
- `src/taskloop/dash_board.py:22-109` — duplicate land inference and card construction.
- `src/taskloop/dash_model.py:8-38` — existing landing vocabulary and serialized card fields.
- `src/taskloop/dash_composition.py:37-50` — policy cache and board/detail callers to consolidate.
- `src/taskloop/dash_task.py:269-291` — task-detail view and card caller; adjust its mode port declaration consistently.
- `src/taskloop/result_data.py:46-64` — CLI JSON status serialization.
- `src/taskloop/step_render.py:42-123` — CLI show/list callers of shared task status words.
- `src/taskloop/land.py:327-399` — existing close, delivered re-entry and public land operation; consult, retain its ownership.
- `src/taskloop/dash/static/ui.js:27-33` — landing display vocabulary consumed by all dashboard surfaces.
- `src/taskloop/dash/static/app.js:60-72` — land card status display.
- `src/taskloop/dash/static/drawer.js:135-193` — drawer heading and policy explanation.
- `src/taskloop/dash/static/rail.js:196-206` — land rail row consumer.
- `tests/steps/round_bench.py:197-245` — semantic round composition and injectable landing/repository ports.
- `tests/steps/land_bench.py:111-180` — real application land composition with semantic Git and tracker fakes.
- `tests/steps/test_round_land.py:27-154` — round fixture, policy refusals, one-task limit and the fake that currently never completes delivery.
- `tests/steps/test_dash_read.py:198-222` — existing dashboard policy/running-state contracts that need revision.
- `tests/cli/test_step_status_cli.py:128-192` — status CLI fixtures and output contracts.
- `tests/steps/test_task_status.py:19-81` — status precedence and capacity contracts.

These are the bounded implementation edit/consult points. Follow a missed caller or changed source only with a targeted search; keep any resulting work inside the two acceptance behaviours and reassess Size if the estimate grows.

## Verification
Add pytest behaviour tests rather than tests for every helper. Parameterize labelled/unlabelled and auto/manual/unknown. Exercise the actual land operation with semantic fakes, including repeated rounds after completion and re-entry after delivery before recorded close, not only a callable returning `pushed`. Assert no new plan/implement attempts, one remote delivery, one effective task completion and a final landed status. Cover repository/backlog isolation, oldest-first selection and the one-task-per-round bound. Exclude held/abandoned/unreleased/failed checks and preserve observed-running status. Test no automatic side effects under manual/unknown, no Git writes from status reads, and policy read from committed origin main even if the working tree differs. Compare human/JSON/card/detail words and unknown rendering in the UI.

After the declared environment is installed with `just install`, run focused tests for the changed behaviours, then the required `just check` and `just test` gates. Use the repository's gates, not an independently launched whole-suite/live test run. Run `git diff --check`. Preserve 400-line source, 80-line function and 800-line test caps for changes; extract within the owning slice if a touched module needs room. Do not introduce Any, casts, ignores, subprocess escapes or alternate state ownership. Report the actual validation and final changed-file count; saved parent work is not evidence of passing checks.
