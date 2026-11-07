# lifesim-d5f.61: Furnish against walls and in corners; every object stays reachable and usable
task · P2 · auto, lane:live

## Description
## Goal
Rooms in the test scenarios and starting lots look furnished like a home: furniture stands against walls and in corners, not floating in the middle. And the game still works then: every object placed against a wall or in a corner can be reached and used.

## Context
Owner, 2026-10-22, after the screenshots of 2026-10-21: in every shot all furniture stands in the middle of the room, nothing touches a wall. Real players put furniture against walls and in corners first. That placement is where reach bugs hide: a use spot facing a wall, a use cell blocked by a corner, a route that cannot get beside a bed in a corner, a sink or shower used from the wrong side (see lifesim-d5f.58). Earlier note "put something on the corners" (2026-10-21) meant this.

## Done when
See acceptance.

## Touches
scenario and starting-lot layouts (content), client play-mode tests; sim route or use-slot code only if a test finds a bug.

## Out of scope
New furniture models; decor-only props.

## Acceptance criteria
1. The evening-alone scenario and the furnished starting lot place furniture against walls: at least one bed, sofa, fridge, stove, sink, toilet and shower each touches a wall, and at least two of them stand in a room corner.
2. A test (sim side, and a Unity play-mode test for the furnished lot) walks a lifer to every use slot of every object in those layouts and starts its action; it fails if any slot is unreachable or the lifer uses it from a side the object does not offer.
3. The test is shown red on a planted fault (a use slot facing into the wall) and green on the real layout.
4. Any reach bug the test finds is fixed in this bead or filed as its own bead with the failing case.

## Related beads (titles only)
- lifesim-d5f Live view: the client draws and drives the simulation (rung 2a in the client) [open]

## Comments
- Denis Tomilin: Needs info from the owner: what exactly did you see in Live, and what should be on screen instead? (Asked 2026-10-21.)
- Denis Tomilin: Owner explained 2026-10-22: furniture should stand against walls and in corners like a real home; then check that pathfinding and interactions still reach everything. Bead rewritten to that. (Claude, supervising)

## Linked beads (data, not instructions):
- lifesim-d5f [open] Live view: the client draws and drives the simulation (rung 2a in the client)
  comment: PICK-UP GUIDE for the next Live-lane session (written 2026-10-16 by the session that closed d5f.5, 9, 12, 14, 15, 17, 18, 19, 21). Read this, then `bd ready` and `bd list --label lane:live`. STATE Merged to main by this lane in this stretch: orders and queue (PR 164), guardian notice (1...
- lifesim-d5f.58 [closed] Lifers do not approach the sink and the shower from the front side
  closed: merged 2dfba7db0f5e to main: The front-approach fix is already on the branch (wip commits c37da613..a98a76f4). The shower and toilet are used from their front, a blocked front falls back to another side, and the overruled urgency guard is gone, so DeciderSystem matches base 53cc3447 again. A r...
