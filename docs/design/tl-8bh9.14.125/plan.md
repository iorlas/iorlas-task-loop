# Unexpected or unsafe state: agent handoff

Task: `tl-8bh9.14.125`. Status: proposed; the owner must approve the exact wording
and placement before `AGENTS.md` changes. This plan does not grant that approval.

## Context and current behavior

The owner principle comes from architecture review session `local_16bd6c79`,
2026-11-13, and the related tasks `tl-8bh9.14.114` and `tl-8bh9.14.107`.
The checked-in [review lesson](../architecture-review/architecture-review-playbook.md#appendix-k-lessons-from-rounds-23-24-and-a-ledger)
calls for an AI agent to assess unexpected or unsafe states instead of elaborate
recovery code. The [decision register](../architecture-review/decision-register.md#3-attempt-lifecycle-scheduler-and-recovery)
records contextual repair prompts in L9 and the known-state boundary in L11;
the [accepted review record](../architecture-review/grilling-record.md#round-26-27)
also records that boundary. These support a proposal, not approval of this text.

Read the foundation plan and glossary. Current `AGENTS.md` already requires
preserving worktrees, evidence and user data, keeping proposed decisions proposed,
and using observable, idempotent reconciliation for external actions. It does not
yet state this handoff principle. Current `src/taskloop/slot_release.py` refuses
dirty, redirected, unborn or wrong-branch slots and retains their reservations;
it does not reset work. `slot_state.py` preserves unknown observations as unknown.
The rule must retain these safety boundaries and deterministic handling of known
states; this task adds no runtime behavior.

The three task IDs above were not found by `bd show` in this slot's local tracker.
No task state was changed. Before seeking wording approval, consult their notes
through the owning tracker when available; resolve any conflicting decision with
the owner rather than infer what those notes say.

## Proposed wording and placement

Add one bullet under `## Architecture and design` in root `AGENTS.md`, immediately
after the existing external-actions / transactional-outbox reconciliation bullet.
This puts the boundary beside the deterministic reconciliation rule it qualifies,
while the Ownership section continues to govern authority to change data.

Proposed exact bullet, pending the owner's yes:

> - Keep deterministic reconciliation for known states: the typed state machine names
>   the state and a recorded identity proves the next action is safe. For an unexpected
>   or unsafe state, such as a broken slot or a reset that could lose information, stop
>   the affected operation, preserve existing work and evidence, and hand the state to
>   an AI agent with context instead of adding elaborate recovery code for rare states.
>   Provide a copyable repair prompt with the affected task, attempt and slot where
>   applicable, observed facts, evidence references and why the next action is unsafe.
>   The handoff grants no additional authority to reset or delete data.

The prompt is the means of passing context to an agent; this rule does not require
an automatic repair-agent launch. A known refusal or temporary unavailability
continues through its defined safe handling. An unproven identity never justifies
a destructive reset. No new domain term or stored status is introduced by this text.

## Approval and bounded implementation

1. Present the exact bullet and its placement to the owner. Record the explicit yes
   in the task tracker with a link to this plan. If the owner changes the text or
   placement, update the proposal and obtain approval of that final version.
2. Only after that yes, insert the approved bullet in root `AGENTS.md` in the task's
   managed worktree. Re-read the then-current instructions and preserve adjacent
   edits. If the same rule already exists, assess it against the approved text
   rather than duplicating it.
3. Review the resulting instruction change against the approval and L9/L11. Keep
   runtime recovery, slot reset, agent-launch plumbing, repair schemas, tracker
   state transitions and broader documentation reorganization outside this task.

This planning attempt changes only this file. The later implementation changes
`AGENTS.md` only as approved; it does not treat plan acceptance or a factory commit
as the owner's wording approval.

## Verification and completion

For this documentation-only change, review the diff and run `git diff --check`.
Check that the rule covers both example unsafe states, preserves deterministic
known-state reconciliation, supplies usable context, and does not authorize data
loss or contradict ownership and evidence preservation. Verify that unrelated
instructions and the managed Beads block remain intact. No runtime tests or new
tests are needed for this instruction-only scope; if scope changes to code, stop
and plan it separately under the repository's focused verification rules.

Completion requires the owner's recorded approval of the final wording and
placement, followed by that rule appearing in root `AGENTS.md`. A proposed plan
alone does not complete the task.
