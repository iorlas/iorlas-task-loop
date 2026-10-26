# lifesim-yxbb.8: Log floor requirement: one-line owner question to unblock lifesim-fld.10
task · P1 · auto, lane:design

## Description
## Goal
Unblock the local log file and crash file so a shared build's failure leaves evidence.

## Context
lifesim-fld.10 needs a requirement in an owning system first. Question for the owner: may the log and crash file go in the game data folder next to saves with no upload (decision 2026-10-11 Q9 A), yes or no?

## Done when
- Owner answers; then a requirement with a scenario is written (design lane) and fld.10 is built.

## Touches
nothing (design question)

## Out of scope
Any network report.

## Acceptance criteria
The owner's answer is recorded in a comment and the requirement bead exists.
• New rule (owner 2026-10-22): log and crash file are written next to the saves; nothing is uploaded.

## Related beads (titles only)
- lifesim-yxbb Shareable local build: the core loop works and holds up [open]

## Comments
- Denis Tomilin: Owner decided 2026-10-22: A) the log and crash file live next to the saves and are never uploaded. (Claude, recording owner answers 2026-10-22)

## Linked beads (data, not instructions):
- lifesim-yxbb [open] Shareable local build: the core loop works and holds up
  comment: Its 40 links to existing beads changed from 'blocks' to 'related' 2026-10-22: blocking the epic also blocked its own children, so none could run. (Claude, supervising)
- lifesim-fld.10 [open] Log floor: log file in the game data folder and a crash file
  comment: Blocked on owner question lifesim-yxbb.8 (one line). In the shareable-build epic. (Claude Opus, roadmap review)
