# Brief (for a bd brainstorming task): the review model, and the name that replaces `held`

Status: **design**. Owner intake for a future review model; the proposed modes below are not implemented.
Current holds and explicit land are described in the [README](../../../README.md).

Origin: owner's words in the architecture-review grilling, 2026-11-13. Not yet a design.

## Problem
Today one concept, `hold` (tracker label `held`), covers every time the factory stops a task for a person: an agent that failed 3 times, a moved branch, `main` moved 3 times, an unanswered question. The owner finds the name wrong ("it does not feel like the ticket is on hold") and wants it split by what the person is asked to do.

## Owner's model (verbatim in meaning)
- **Why a task needs a human is not one thing.** During planning the agent may find the task hard and raise **questions** (the glossary's `ask`). After the work, a **human review** is needed. A failure is a **blocker**, not a review.
- **Two modes**, with the same user experience and different mechanics:
  1. **Automatic**: tasks run and land; every landed task still goes to a brief **post-factum review** (optional, default on). Rejection creates a **new task** (bug or change request) under or beside the closed one. Approval: nothing happens; it disappears from the dashboard.
  2. **Approval before landing**: nothing merges before a human approves. Approval lets the task continue to land and close, and it disappears from the UI. Rejection sends the human's prompt **back to an earlier step, probably planning**. Later the rejection may be classified (change request, bug, code-review comment).
  If approval is configured before landing there is **no second review at the end**.
- **Kinds of review differ**: code review, acceptance-criteria review, feature review (show screenshots and artifacts), and AI review (optional, e.g. by ticket severity). Human and AI reviews can both exist; the human one has its own shape. QA is out of scope for now (it happens after deployment, in Jira).
- **Pickup:** the label `auto` matters less than **who assigns and who approves** (the owner). The factory is limited by assignee as well as, optionally, a label.

## Naming questions
Should a status be an act ("needs review"), an instruction ("review") or a statement ("awaiting review")? Candidate: three states derived from the model, e.g. awaiting answer, awaiting review, blocked. Owner suggested asking Opus for naming once the model is settled.

## Rule to apply while naming
Every glossary addition is challenged first: is it needed, is the name right, does it fit the rest of the domain (owner's proposed constitution rule).

## Related
Glossary already has: `step` (plan, implement, check, review, land), `ask`, `hold`, `PR`, `label`, `claim`. The `held` marker is tracker configuration; its concept name should follow this model.
