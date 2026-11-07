# lifesim-5ban.14: Tool: generate the simulation state map (modules, state, events) from code
task · P2 · auto, checkpoint-2a, lane:sim

## Description
## Goal
A tool that dumps the module/event/state graph of the simulation into one self-contained HTML file so the owner's state-map page never drifts.
## Context
lifesim-1xki (owner 2026-10-13): a page to inspect what the simulation holds and how changes travel: modules, their state, events, per-character state machines, handoff, saves. Sources: SimulationHost.Modules (order), event types with [SentUpward]/[ReadByTheView], save sections, snapshot parts, FrameWriters.
## Done when
- `just state-map` writes one HTML file listing modules in order with their components, save section, snapshot part, events emitted and read.
- A test or the gate fails if the tool breaks on the current code.
## Touches
tools/state-map/ (new), justfile
## Out of scope
publishing the page (owner session), per-character state machines beyond what code declares.
## Output
the HTML file path printed by the tool.

## Acceptance criteria
- `just state-map` writes one HTML file listing modules in order with their components, save section, snapshot part, events emitted and read.
- A test or the gate fails if the tool breaks on the current code.

## Related beads (titles only)
- lifesim-5ban Sim lane: what is next after the 2a checkpoint [open]

## Last engine run
Blocked: needs a human: delegate stopped the write step (bad_request): codex rejected the request: {"type":"error","error":{"message":"Invalid schema for response_format 'codex_output_schema': 'schema.properties.unchecked.items.required' is required to include every key in properties. Missing 'source'.","type":"invalid_request_error","param":"text.format.schema","code":"invalid_json_schema"},"sta

## Linked beads (data, not instructions):
- lifesim-5ban [open] Sim lane: what is next after the 2a checkpoint
- lifesim-1xki [open] Simulation state map: a page showing what the simulation holds and how changes travel
