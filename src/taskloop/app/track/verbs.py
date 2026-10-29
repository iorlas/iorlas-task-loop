"""`tl claim|land|close|block`: the bead's life as the person or the engine drives it, each recorded as an event and in bd's provenance."""
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from taskloop.adapters.beadtools import attempt, bd_store, peek
from taskloop.adapters.gitrepo import git, repo_root
from taskloop.adapters.ident import actor, config_dir, session_id
from taskloop.adapters.opencode import transcript_of
from taskloop.app.track.trail import event, provenance, prune_events, register_repo
from taskloop.contracts.bead import Bead
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadPatch, Beads


def claim(bead: str, worktree: str | None = None, slot: str | None = None, store: Beads | None = None) -> int:
    st = store or bd_store()
    if not st.claim(bead):
        print("TAKEN")
        return 1
    b = peek(st, bead) or Bead(id=bead, title="", status="")
    if b.assignee not in ("", actor()):
        print("TAKEN by " + b.assignee)
        return 1
    wt = str(Path(worktree).resolve()) if worktree else git("rev-parse", "--show-toplevel")
    branch = b.metadata.get("branch") or "task/" + bead
    attempt(st.update, bead, BeadPatch(set_metadata=dict({"branch": branch}, **({"slot": slot} if slot else {}))))
    event("claim", bead, worktree=wt, branch=branch, title=b.title, slot=slot)
    provenance(bead, "claim", session_id() or actor(), "transcript" if session_id() else "work-id",
               {"worktree": wt, "actor": actor(), "slot": slot}, store=st)
    print("CLAIMED " + bead + " branch=" + branch)
    return 0


def land(bead: str, sha: str, worktree: str | None = None, store: Beads | None = None) -> int:
    full = git("rev-parse", "--verify", "-q", sha + "^{commit}", cwd=worktree) or sha
    event("land", bead, sha=full)
    provenance(bead, "land", full, "git-sha", store=store)
    return 0


def close(bead: str, reason: str | None = None, store: Beads | None = None) -> int:
    try:
        (store or bd_store()).close(bead, reason or "done")
    except BdFailure as e:
        sys.stderr.write(e.error.text + "\n")
        return 1
    event("close", bead, reason=reason)
    prune_events()
    return 0


def block(bead: str, why: str, store: Beads | None = None, say: Callable[[str], None] | None = None) -> int:
    """The bead blocked on the owner; `say` posts its comment (an engine run passes its own poster, Engine.comment)."""
    # tl-159: a parked bead lets go of its claim; the actor that held it stays live (a loop holds other beads), and a claim nobody works on
    # refused --fresh as 'taken: live claim'. A claim by an engine's actor ends with the run; a person's own claim stays theirs.
    st = store or bd_store()
    held = (peek(st, bead) or Bead(id=bead, title="", status="")).assignee
    try:
        st.update(bead, BeadPatch(status="blocked", assignee="" if held.startswith("tl-") else None))
    except BdFailure as e:
        sys.stderr.write(e.error.text + "\n")
        return 1
    if say is not None:
        say("Blocked: " + why)
    else:
        attempt(st.add_comment, bead, "Blocked: " + why)
    event("block", bead, why=why)
    provenance(bead, "suspend", session_id() or actor(), "transcript", {"why": why}, store=st)
    return 0


def passthrough(rest: list[str]) -> int:
    """`tl bd ...`: bd with this session's actor and --json, through the adapter."""
    r = bd_store().passthrough(rest)
    sys.stdout.write(r.out)
    sys.stderr.write(r.err)
    return int(r.code)


def register(directory: str) -> int:
    """`tl register [DIR]`: add the repo of a working directory to the dashboard."""
    try:
        path = repo_root(directory) if git("rev-parse", "--is-inside-work-tree", cwd=directory) == "true" else None
    except (OSError, ValueError):
        path = None
    if path is None:
        print("tl: not a Git working directory: " + repr(directory), file=sys.stderr)
        return 1
    register_repo(path)
    print("REGISTERED " + path)
    return 0


def trace_line(r: dict[str, Any]) -> str:
    mins = (r.get("ended", 0) - r.get("started", 0)) / 60
    st = r.get("stats") or {}
    cached, out = st.get("tokens_cached", 0) / 1e6, st.get("tokens_out", 0) // 1000
    tok = f"  tokens in {st['tokens_in'] / 1e6:.2f}M ({cached:.2f}M cached) out {out}k" if st.get("tokens_in") else ""
    cost = r.get("cost")
    usd = (cost or {}).get("usd", 0) if isinstance(cost, dict) else (cost or 0)
    head = f"{r.get('run')}  {r.get('bead')}  {r.get('outcome')}  {int(mins)} min  ${usd:.2f}"
    return f"{head}{tok}  coordinator={r.get('coordinator_session') or '-'}"


def trace(bead: str, last: int, as_json: bool) -> int:
    """`tl trace [ID] [--last N] [--json]`: engine runs and every worker session of each, with where its transcript lives."""
    path = ConfigDir(config_dir()).traces()
    runs: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not bead or r.get("bead") == bead:
                runs.append(r)
    if last:
        runs = runs[-last:]
    for r in runs:
        for s in r.get("sessions", []):
            s["transcript"] = s.get("transcript") or transcript_of(s.get("family"), s.get("ref"))
    if as_json:
        print(json.dumps(runs, indent=1, ensure_ascii=False))
        return 0
    if not runs:
        print(f"no traces{' for ' + bead if bead else ''} yet ({path})")
        return 0
    for r in runs:
        print(trace_line(r))
        for s in r.get("sessions", []):
            print("  {:<7} {:<8} {:<6} {:<9} {}  {}".format(s.get("node"), s.get("role"), s.get("family") or "?", s.get("status"),
                                                           s.get("ref") or "-", s.get("transcript") or ""))
    return 0
