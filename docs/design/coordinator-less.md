# task-loop as our own AI factory: attended now, unattended later (design, 2026-10-18)

> Changed 2026-10-19 (task-loop 0.6.0, epic tl-bxk.8): there is no verify node and no judge node. Six lifesim runs
> showed the light verifier adding false gaps and the judge deciding from JSON with no tools; acceptance is now a rule
> (engine checks green, nothing blocking in a cross-family review that also lists unmet requirements). The tables
> below keep the original design for the record.

Status: proposal, not built. Inputs: the lifesim AI factory (docs/ai-factory on lifesim origin/main: dispatcher,
task and merge workflows, pilot and friction logs), today's task-loop, and a Fable review.

## Goal (owner)

We build our own AI factory; no Archon, nothing third-party. One engine, two modes:

| mode | who starts the engine | who watches | for |
|---|---|---|---|
| **attended** (now) | a coordinator session running the task-loop skill | that session: it reads the runner's decisions and the dashboard, spots strange things, corrects the profile or the scripts, files friction beads, says when no ready bead is left | evolving the factory fast, and people who want a skill, not a factory |
| **unattended** (later) | one command (`tl run`), no Claude session | the dashboard and questions on the beads | full autonomy |

The coordinator stops doing the work (pick, claim, plan, write, verify, land): the engine does it. Like watching the
AI factory and fixing its configuration when it misbehaves. Design happens elsewhere: a bead that is fully described
gets the ready label and the engine takes it (lifesim's `auto` and grooming rules).

## The finding

Today's coordinator session does two jobs:

1. **Dispatch**: reclaim, pick, claim, take a slot, start work, reap the dead, land, close. Pure rules. The factory
   does this in code (factory.py `one_pass`): event-driven, idempotent, safe to run N times at once.
2. **Per-task judgement**: read a verifier report, decide it is wrong, re-plan after a surprise, do small related work
   now. The factory never had this: its AI nodes were read-only, one call, `done|blocked|failed`.

Dispatch moves to code. Judgement does not vanish; it moves to two places: **grooming** (a bead with `Done when`,
`Touches`, about one agent-hour is what makes a dumb runner work) and a **judge node** (a cheap model that routes
ambiguous results). Neither system has yet run write → verify → review without a judge; the first step proves it.

## Design

### Coordinator (attended mode)
Starts `tl run` (or `tl run-task <id>` while step 1 is being proven) in the background, then loops: read new decision
lines and finished nodes, check what looks wrong (a node retried twice, a judge `replan`, a gate red twice, a slot
dirty, a task over budget), fix the cause in the profile or the scripts, or file a bead. It never does a node's work.

### Runner
`tl run [--slots N]`: one supervisor process, no Claude session. Each slot runs one task workflow at a time; at the
end of every task the dispatch pass runs again (event-driven, no timer). `tl stop` reaps every live run (kill switch).
Python stdlib, macOS and Linux first.

### Dispatch pass (port of factory.py `one_pass`)
- Atomic claim: `bd update --claim` (per-runner actor); lost → next.
- Free slot = no live run on it, tree clean, no project lock (profile hook, e.g. Unity's lockfile).
- Order: spikes first, then priority, then Touches overlap (task-loop's rule).
- Reaper: a run older than `task_max_min` → abandoned, its process tree killed, the bead `failed` with the last trace
  lines. A claim with no live run older than `stale_min` → reopened.
- Every decision is one JSONL line (`decisions.jsonl`, same action names as the factory): the dashboard's source.
- End state: `drained`, `waiting`, or `deadlock`.

### Task workflow (hardcoded first; data later, maybe never)

| node | kind | output |
|---|---|---|
| reset | script | slot on `task/<id>`; brief and every engine file in `<config dir>/task-loop/runs/<run>/` (no worker can write there); `.task/<id>/evidence/` is the writer's |
| plan | AI (strong) | `{stages[{goal, files, checks, writer|hard}], risks[{what, check}], question?}` |
| write | AI, one **resumed thread per task** | free text (counts as nothing) |
| verify | AI, fresh | `{checks[{cmd, exit, tail}], stats, outside_touches[], risk_flags[], verdict: accept|gaps, gaps[]}` |
| review | AI, fresh, other model family; only on a risk flag, a named risk, a hard stage or a third round | `{findings[{file, line, severity, fix}]}` |
| judge | AI, cheap | `{decision: accept|rework|replan|block, why, question?}` |
| gate | script | the profile's gate on the rebased tree |
| land | script, one lock per repo | rebase, push (or merge ff-only), with a resolve AI node on conflict |
| close | script, **always runs** | bd status, notes, leftovers filed, events, fires the next dispatch |

Rules route structured outputs; they never decide an ambiguous one: `gaps` → write again (max 2) → `hard`;
`rework` → write; `replan` → plan with the findings; question → `blocked`. Every output is validated against its
schema; invalid → one retry with the error appended; still invalid → `failed`. The close node never depends on the
failing node (factory lesson #21).

### Workers
Headless agents: `claude -p --output-format json --json-schema ... --bare --settings <curated> --strict-mcp-config`,
`codex exec --output-schema F -o F`, resume by id. Children get an env allow-list (strip `CLAUDE_*`, `ANTHROPIC_*`),
no repo SessionStart hooks, their own process group. Lane and model per node: delegate's `route.py run`, required
(worker-run v1, decided 2026-10-18).

### Human in the loop (the factory's protocol)
`blocked` with the question in notes (phone-decidable format: location, doing, found, decision, options with costs,
recommendation); the owner reopens with the answer appended; the next attempt restates the answer in one line.
The dashboard lists open questions. A push channel (Telegram) is a later bead.

### Budgets
Per task: dollars and wall-clock, node inputs. Over budget → `blocked` with what was spent. A lane out (limits) pauses
the dispatch pass; it never fails a task. Start generous (owner, 2026-10-18): $15 and 3 hours per task, every task's
real spend and time recorded, limits tuned from those numbers.

### bd store
The repo's real, shared bd store: it is the hub every session, runner, worker and the dashboard read and write
(claims, leases, notes, provenance). The factory pilot used a sandboxed copy only because its tasks were synthetic and
Dolt auto-push reached the real GitHub store (friction #17).

### Landing
Default: as today. Each task rebases and pushes; the repo's pre-push gate runs; a push that loses the race rebases and
gates again. The runner records the minutes spent on gates that lost a race; if that waste gets large, switch to a
landing queue (one push at a time, no wasted gates, lower throughput).

### What stays from today
`tl.py` bead lifecycle and actor, slots, the dashboard (it reads the runner's events and decisions instead of
coordinator sessions), the agent-runs contract.

### The skill afterwards
(a) start, stop, status of the runner; (b) a grooming helper for the design stream (make beads auto-ready);
(c) the per-node agent instructions. Nothing else.

## Verdicts

| idea | verdict | why |
|---|---|---|
| No coordinator session | ✅ | dispatch is rules; the coordinator's context already had to live in the bead |
| Judgement as fixed rules only | ❌ | ambiguous reports need a reader: judge node |
| Tiny engine | ✅ | sequence, `when`, bounded loop, always-run close; nothing more |
| Archon on macOS/Linux | ❌ | bus factor 1, tree-kill bug, refuses interactive; factory.py rebuilt most of it anyway |
| One workflow file run by both Archon and `tl` | ❌ | Archon keys make it a lowest common denominator; share a node schema with two loaders |
| Prefect, Temporal, Actions YAML | ❌ | heavier than the engine, none knows slots or bd |
| Fresh agent per node everywhere | ❌ | writer keeps one resumed thread per task; verify and review stay fresh (no self-grading) |
| Planning as an AI node | ✅ | "never delegated" protected the coordinator's context; with no coordinator the plan lives in the bead |
| Serialized land with the full gate inside the lock, from day one | ❌ | 12-minute gate → about 5 landings an hour whatever the slots; start with today's race and measure the wasted gates |
| Slot reset wipes (factory reaper) | ❌ | commit leftover work, as `tl slot reset` does: reversible |

## Gaps neither system closes yet
- No code-writing task has run end to end in either (the factory's AI nodes were read-only; task-loop never ran).
- No per-task cost cap anywhere (the factory has cost rows and reads none).
- A merge retry reruns the whole task (factory §7).
- No push channel for questions.

## Steps
1. `tl run-task <id>`: one real bead through the hardcoded sequence above, headless, on macOS, started and watched by
   a coordinator session. Proves the coordinator no longer does the work.
2. `tl run`: the dispatch pass and slots, several tasks at once; dashboard on the runner's decisions.
3. Budgets, reaper, kill switch, questions on the dashboard.
4. Maybe: workflow as data, and the factory moves to the same node schema.
