# lifesim-5ban.28: Command registry: typed commands with help, read/write flag, writes through the command queue (no socket)
task · P2 · auto, checkpoint-2a, lane:sim, sim-next

## Description
## Goal
One registry of console commands the client console and future socket both use.
## Context
Split from lifesim-xn9 (socket + terminal part stays deferred there). interface.R14/R15 need commands in 2a; no registry exists in src today.
## Done when
- a registry type lists commands with name, typed args, help text and a read/write flag
- write commands go through the existing command queue, never mutate state directly
- unit tests cover parse errors and help output
- just check green
## Touches
src/Sim.* (new registry in the composition/host layer), tests/
## Out of scope
local socket, terminal host, any client UI

## Acceptance criteria
- a registry type lists commands with name, typed args, help text and a read/write flag
- write commands go through the existing command queue, never mutate state directly
- unit tests cover parse errors and help output
- just check green

## Related beads (titles only)
- lifesim-5ban Sim lane: what is next after the 2a checkpoint [open]

## Linked beads (data, not instructions):
- lifesim-5ban [open] Sim lane: what is next after the 2a checkpoint
- lifesim-xn9 [deferred] One command surface: console registry, local socket (dev builds, release by flag), read commands
