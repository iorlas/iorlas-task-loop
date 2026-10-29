# Operator model, views, asks (draft, 2026-10-29)
Sources: Fable (roles, ask lifecycle, views), Sonnet research on print/CNC farm software (research-farms.md). Not yet decided by the owner.

## Roles: one person, two hats, split by cadence
| hat | job | cadence | console |
|---|---|---|---|
| operator | feed: beads with acceptance + references, queue order | daily | Beads |
| operator | run: slots, quotas, answer asks, approve looks, land | continuous | Home (Cutting Room), Decisions, Lanes |
| operator | fix: looping/silent bead, tool failure, lane lock | few/day to few/week | bead/slot drawer |
| engineer | improve: ask clusters into ADRs, config, prompts, env fixes | weekly sitting | Decisions ledger, morning report |
Two people only when a second requirements owner or a second fleet appears.
Analogy breaks: an ask is a drawing fault (goes to the designer = operator), reruns are not deterministic, a prompt change acts on every job.

## Views: one per question
| view | question | data |
|---|---|---|
| Home: Cutting Room | what is the line doing, where is it stuck | time x slots |
| Beads: Kanban (tree as toggle) | where is each bead, what is next | bead state |
| Decisions | what needs me, is the factory learning | ask ledger |
| Lanes | do we have capacity | quota |
Kanban columns: backlog, working, asking, AI review, your review, PR, done.
No verbosity slider; no per-role views until two humans.

## Ask lifecycle
Answer path unchanged. After send, optional one tap "make it stick": decision (ADR prefilled from the card), factory bead, fix bead, demote to non-blocking with default, reject.
- Agent self-declares cause in `tl ask` (requirement / decision / env / process / unknown); human corrects only.
- Repeat detection before the ask leaves: tl ask searches past asks + ADRs, agent must cite or explain.
- Plan stage loads decisions/; citations = reuse count; 0 reuse after 30 d = prune.
- Measures: asks per landed bead, parked minutes, repeat rate, cause Pareto, % with durable outcome, send-back rate (Goodhart guard: fewer asks may mean more wrong assumptions).

## Farm patterns
1. Confirm gate (SimplyPrint "clear bed"): human approve, then next job auto-starts = look/land approve.
2. Resource-matched dispatch (Printago): job waits for material = bead waits for a lane with quota and the right model.
3. Auto-pause then ask with one-click retry/resume (Obico).
4. Queue timeline Gantt (SimplyPrint): slots on y, jobs as bars = Cutting Room.
5. Zero-input telemetry, every utilization number drills to its events (Datanomix, MachineMetrics).
6. Glanceable tiles + TV/andon mode.
