# Hierarchical priority: task first, ancestry breaks ties

Status: **built** for scheduling priority as recorded in [the scheduling slice](../tl-8bh9.4.3.1.13/plan.md).
The historical plan-admission wording below is retained; current commands are in the [README](../../../README.md).

Task: tl-8bh9.3.7. Owner accepted Astra's rule on 2026-11-08. Decision settled; implemented for plan admission in
[.4.3.1.13](../tl-8bh9.4.3.1.13/plan.md) (`selection.py`); approval is the tracker label `auto`.
A less urgent task never beats an urgent task because of its ancestors. When own priorities tie, compare ancestor
priorities from nearest parent to root, including every containment level.

## Required ordering contract

The most specific priority wins. Compare own task priority first, then nearest parent, then its parent, continuing
to the root. Use a stable task ID for an otherwise exact tie. There is no special epic type in this comparison.
Missing priority is P2, matching the current own-priority default. Missing ancestor levels also compare as P2.
For an otherwise exact tie, retain natural task-ID ordering used by the current selector (numeric runs compare as
numbers). Selection within one repository needs no additional identity. A cross-repository pool qualifies the tie-break
with repository identity so distinct tasks cannot share a key.

```text
own task priority
  -> direct parent's priority
    -> grandparent's priority
      -> continue outward
        -> stable task ID
```

All comparisons prefer P0 over P1, through P4. Ancestors never change the task's own priority or eligibility.
No multiplier, inherited-priority writes, second queue, configured epic order or group exclusion is needed.
This refines the owner's priority-only model; it does not revive manual ordering or area admission.

## Scenarios discussed with Astra

| Equal or competing candidates | Result | Why |
|---|---|---|
| P0 fix under P2 parent; P3 cleanup under P0 parent | P0 fix | Own priority dominates every ancestor. |
| Two P1 tasks under P0 and P2 parents | Task under P0 parent | Direct parent breaks an own-priority tie. |
| Two P1 tasks with P2 parents, P0 versus P3 grandparents | Task with P0 grandparent | Compare outward only while nearer priorities tie. |
| P1 A: root P0 -> parent P4; P1 B: root P2 -> parent P0 | B | The specific urgent subgroup outranks the broad urgent portfolio. Root-first would choose A instead. |
| Standalone P1; P1 task with only P2 ancestors | Stable ID decides | No parent is not automatically highest or lowest urgency. |
| Standalone P1; P1 under P0 parent | Child of P0 parent | Known urgent parent wins a tie with default context. |
| Standalone P1; P1 under P4 parent | Standalone task | Explicit deferred context loses to default context. |
| Missing task priority under P0 parent versus explicit P0 task | Explicit P0 task | Missing own priority remains P2, not inherited P0. |
| Same-priority siblings with identical ancestry | Stable ID decides | No discovery-time, age, queue-position or network-recovery ordering. |
| Important task blocked by dependency | Does not enter ordering | Readiness and authorization are separate from priority. |
| New urgent work while an attempt is active | Chosen at next applicable admission | No automatic preemption or abandonment of the active step/session. |

Owner chose specificity over portfolio: nearest parent before root gives a subgroup's explicit priority precedence
over a broader initiative when own priorities tie. This is required behavior, not an implementation option.

## Adversarial checks and limitations

Multipliers treat ordinal priorities as quantities and introduce arbitrary weights. With unbounded hierarchy depth,
ancestor accumulation can outweigh task urgency unless additional normalization/caps are invented. Keep lexicographic
ordering instead: no quantity of ancestor urgency can make P3 beat P0.

Ordinary variable-length tuple ordering rewards a shorter ancestry just because it ends first. Comparing only common
levels and switching to ID when one ends can be non-transitive: A (parent P0, ID 3) precedes C (parent P4, ID 1),
C precedes standalone B (ID 2), and B precedes A. Do not implement that comparator.

For a selection snapshot, pad every nearest-to-root ancestor vector to the maximum candidate depth using P2, then
compare (own priority, padded ancestor vector, stable ID). Adding another depth of P2 to every existing vector cannot
change their relative order. This establishes a total order; P2 is a documented default, not a mathematical truth.

Padding is not full structural neutrality. A task A under P0 beats equal-priority B under P1. Insert a P2 grouping
task between A and its P0 ancestor and B now wins: A's nearest context became P2. Reparenting or adding meaningful
hierarchy can therefore change ordering. Ignoring neutral levels or selecting the best ancestor would reduce some
structural sensitivity, but changes the meaning and can erase an explicit deferred subgroup. Do not claim this
rule eliminates all effects of hierarchy depth. This structural effect is part of the accepted contract, not an
invitation to substitute another comparator during implementation.

Lower-priority work can starve while higher-priority eligible work keeps arriving. That follows from explicit priority;
do not add hidden age/round-robin boosts in this change. If priority changes are needed, change source task priority.

## Small implementation boundary

One shared selector for factory/CLI and dashboard projection. Task service owns priority and canonical containment
parent; the factory derives ancestry transiently once per candidate snapshot. No persisted inherited score or child
rewrites. Fetch each unique parent once per snapshot, preferably from already available task rows, with no IO inside
the comparator. No full repository file scan, shell operation or model call is needed for selection.

Current task port has one parent. Future task adapters must expose a canonical containment parent; blockers/related
links are not ancestry. Multiple parents must not become choose-whichever-is-most-urgent behavior. Detect cycles and
distinguish no parent from failed/missing parent reads. Report and skip a candidate with an invalid/unreadable chain
for that selection pass; other valid candidates remain selectable. Do not fabricate a root or grant eligibility
because a read failed. A missing priority value defaults to P2; an unavailable task record is a read failure.

Priority edits and reparenting affect the next selection; already acquired ownership and active attempts retain their
lifecycle protections. Manual scope filters eligibility but adds no order. Explicit direct execution remains a separate
selection intent subject to its applicable safety checks. Any cross-repository pool needs a stable repository-qualified
tie-break, not an assumption that task IDs are globally unique.

## Evidence and status

Read current QueueRule missing-priority handling, Areas parent traversal, task record and task-service port. Existing
ancestor lookup is required by the accepted contract; move the minimal retained lookup to its
actual task-selection owner while deleting areas, not to another area framework.
Astra provided an initial recommendation, self-attack over unequal paths/transitivity, and a follow-up challenge on
P2 wrapper insertion. These are reasoned scenarios; since .4.3.1.13 each scenario row, the padding, the
non-transitive trap and natural ids are focused fake tests (`tests/plan/test_selection.py`). No source, task priorities or task
hierarchy changed. Eventual focused fake tests should assert the retained ordering contract, with normal repo gates.
