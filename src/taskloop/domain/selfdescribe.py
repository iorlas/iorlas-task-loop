"""The compact task-loop introduction injected into sessions in profile repositories."""


def text() -> str:
    """Describe task-loop itself; SKILL.md owns the orchestrator procedure."""
    return """task-loop runs a beads backlog through plan, workers, checks, land and close.
Sessions coordinate in worktrees or slots; the loop and dashboard track their work.
`tl` is ~/.config/task-loop/bin/tl, the shim maintained by SessionStart.

Commands (tl --help and tl <verb> --help give arguments):
tl status: loop, asks, slots, versions and recent work.
tl task <bd command>: every bd call, with this session's actor automatically.
tl actor: print that actor (normally tl-<first 8 characters of the session id>).
tl claim ID: claim and record work; tl close ID: close with recorded landing or typed reason.
tl check: run profile checks; tl gate: run them as a recorded gate.
tl slot list|init|take|release|reset|setup|hold: manage reusable work slots.
tl worktree start|sunset; tl worktrees [clean]: manage owned worktrees.
tl dash ensure: start the dashboard; tl dash status|url|stop: inspect or stop it.
tl wait --bead ID|--any: wait for a run to finish or an ask to open.
tl factory start|status|stop|logs: manage the detached loop.
tl run-task ID: run a bead; tl loop: run the queue; tl next: preview; tl stop: stop.
tl register: register a repo; tl queue: manage the owner's queue; tl lint: check beads.
tl ask: inspect the inbox; tl answer: answer an ask.
tl hint, tl hold, tl override, tl park, tl note: typed owner decisions.
tl land: record landing; tl land-lock: serialize delivery; tl land-stack: deliver a stack.
tl block: block a bead; tl trace: inspect runs; tl reflect: digest reflections.
tl report: scorecard; tl lost: find unlanded work; tl green: inspect check evidence.
tl usage: feed usage; tl lanes: refresh lane status; tl handoff: write or show a handoff.
tl doctor, tl selftest, tl cutover: diagnostics.
tl setup --plan|--apply: what this machine and repo still need; make it so.
tl pin, tl rollback: owner overrides for the installed version.
tl prune: reconcile expired leases and remove old owned data.

Standing rules:
Work in a worktree or slot. Never edit the main checkout or a plugin cache directory.
Release only through dev/release.py; never bump a version by hand.
Never kill by pattern (pkill/killall); confirm that a specific PID is yours first.
Every bd call goes through tl task, which supplies the session's actor.
For the orchestrator procedure, read the task-loop skill's SKILL.md."""
