# Two hosts, one bd database

Status: finding recorded, no fix.

Z06 says bd claims are exclusive per machine, not per factory.
The live characterization in `tests/live/test_two_hosts_one_bd.py` records
the observed collision with real bd 1.3.1 and a file remote.

Host A initializes a repository and bead, then pushes its database.
Host C bootstraps that database into a separate repository.
Each host uses a distinct value of the bd actor variable.
Without any intervening pull, both hosts successfully claim the same bead.
The test spaces the claims so C has a later merge timestamp.
A commits and pushes; C commits and pulls.
The merge resolves the assignee by last-write-wins, retaining C's actor
and the `in_progress` status on C.
Only the pull side reports the last-write-wins notice.
A's successful claim has been superseded without an exclusive shared claim.

For task-loop, a second machine running a loop on the same repository can
double-run a bead. The fence and claim protect one machine, not the factory.

Option A of tl-sqd3.23: a repo-owner record in bd metadata containing host,
loop id and heartbeat, with opt-in shared claims.
Option C: one factory; the Mac only files beads.

The owner must decide before option A is built. The test pins today's
behaviour so a bd upgrade that changes it becomes visible.
