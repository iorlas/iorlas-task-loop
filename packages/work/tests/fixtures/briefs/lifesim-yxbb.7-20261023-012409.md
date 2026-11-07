# lifesim-yxbb.7: A shipped catalogue that can furnish a home: table and chairs, sink, a second bed, counter
task · P2 · auto, lane:build

## Description
## Goal
Buy mode offers enough objects that a player can furnish a home that supports eating, washing, sleeping and fun.

## Context
content/objects today: bed (single), fridge, stove, toaster, toilet, shower, sofa, TV, door, window. No table or chairs (lifesim-fld.6 eating at a table runs now), no sink, no double bed, no plates or dirty dishes though content/actions/eat-leftovers-off-plates.yaml exists. Owner question: which of these are 'enough' for the shareable build (is a sink a must; do plates exist)? Models come from the licensed packs in design/runbooks/asset-sources.md.

## Done when
- Owner answers the question in a comment; then the beads for the chosen objects are filed (object yaml with adverts, model, footprint, a use case each).

## Touches
nothing (decision; follow-up beads touch content/objects/)

## Out of scope
Art creation.

## Acceptance criteria
A comment from the owner names the must-have list; follow-up beads exist for each object.
• New rule (owner 2026-10-22): the shipped catalogue contains at least table, chairs, sink, plates and a second bed.

## Related beads (titles only)
- lifesim-yxbb Shareable local build: the core loop works and holds up [open]

## Comments
- Denis Tomilin: Owner decided 2026-10-22: A) must-have objects for the shareable build: table, chairs, sink, plates, second bed. (Claude, recording owner answers 2026-10-22)
- tl-2be89f88-7ca51c: Verify (engine): what the workers could not check, self-verified read-only before land: open: Follow-up beads for table, chairs, sink, plates and second bed: the engine files them from the plan's leftovers; this stage may not run bd., The beads for table, chairs, sink, plates and second bed don't exist yet. The engine files them after this stage. Whoever lands the task should run `bd list` after filing to confirm there is one bead per object (five in all). Each bead should name an object yaml with adverts, a model, a footprint and a use case.

## Last engine run
Blocked: needs a human: delegate stopped the write step (bad_request): codex rejected the request: {"type":"error","error":{"message":"Invalid schema for response_format 'codex_output_schema': 'schema.properties.unchecked.items.required' is required to include every key in properties. Missing 'source'.","type":"invalid_request_error","param":"text.format.schema","code":"invalid_json_schema"},"sta

## Linked beads (data, not instructions):
- lifesim-yxbb [open] Shareable local build: the core loop works and holds up
  comment: Its 40 links to existing beads changed from 'blocks' to 'related' 2026-10-22: blocking the epic also blocked its own children, so none could run. (Claude, supervising)
- lifesim-fld.6 [closed] Eating at a table: hand IK per slot or an authored eat clip
  closed: merged e9ac663ff526 to main: The earlier run's WIP commit (84065a91) already holds the hand-IK work. It adds LifeEat (an IK component), EatLines and EatSettings, wires an eat step on a sit slot in HouseholdView, adds an `eat` block to config/renderer.yaml, and adds edit-mode EatTests plus a play-mode ...
