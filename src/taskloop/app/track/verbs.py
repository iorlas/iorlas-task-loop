"""`tl claim|land|close|block`: the bead's life as the person or the engine drives it, each recorded as an event and in bd's provenance."""
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from taskloop.adapters.bd import BdStore
from taskloop.adapters.beadtools import attempt, peek
from taskloop.adapters.gitrepo import repo_root
from taskloop.adapters.ident import config_dir
from taskloop.adapters.opencode import transcript_of
from taskloop.app.track.trail import event, provenance, prune_events, register_repo
from taskloop.contracts import fence
from taskloop.contracts.bead import Bead
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadPatch, Beads, Git


def claim(who: Identity, bead: BeadId, store: Beads, git: Git, worktree: str | None = None, slot: str | None = None) -> int:
    st = store
    if not st.claim(bead):
        print("TAKEN")
        return 1
    b = peek(st, bead) or Bead(id=bead, title="", status="")
    if b.assignee not in ("", who.actor):
        print("TAKEN by " + b.assignee)
        return 1
    wt = str(Path(worktree).resolve()) if worktree else git.toplevel(".")
    branch = b.metadata.get("branch") or "task/" + bead
    attempt(st.update, bead, BeadPatch(set_metadata=dict({"branch": branch}, **({"slot": slot} if slot else {}))))
    event(who, "claim", bead, worktree=wt, branch=branch, title=b.title, slot=slot)
    provenance(st, bead, "claim", who.session or who.actor, "transcript" if who.session else "work-id",
               {"worktree": wt, "actor": who.actor, "slot": slot})
    print("CLAIMED " + bead + " branch=" + branch)
    return 0


def land(who: Identity, bead: BeadId, sha: str, store: Beads, git: Git, worktree: str | None = None, base: str | None = None,
         claim: fence.Claim | None = None) -> int:
    """Record a land. With `base`, provenance gets the sha only once it is an ancestor of that base: a sha that never reached it
    is no land (the event stays, as what was claimed). An engine run passes its claim and a stale one is refused; `tl land` by hand
    passes none."""
    st = store
    if claim is not None and (why := fence.stale(st, claim)):
        sys.stderr.write(f"fenced: land of {bead} not recorded: {why}\n")
        return 1
    where = worktree or "."
    full = git.rev_parse(where, sha + "^{commit}") or sha
    event(who, "land", bead, sha=full)
    if base and not git.is_ancestor(where, full, base):
        sys.stderr.write(f"{bead}: {full[:12]} is not on {base}: no land recorded in provenance\n")
        return 1
    provenance(st, bead, "land", full, "git-sha")
    return 0


def close(who: Identity, bead: BeadId, store: Beads, reason: str | None = None) -> int:
    """`tl close`: a person's close, under the claim they hold on the bead now."""
    return close_as(who, fence.hand(store, bead, who.actor), reason, store)


def close_as(who: Identity, claim: fence.Claim, reason: str | None, store: Beads) -> int:
    """Close the bead the claim is for; a stale claim (its bead or slot was taken again) is refused, and so is a bead whose assignee is
    no longer the claim's actor (bd checks that atomically)."""
    bead = claim.bead
    try:
        fence.check(store, claim)
        store.close(bead, reason or "done", fence.guard(claim))
    except fence.Fenced as f:
        sys.stderr.write(f"fenced: {bead} not closed: {f.why}\n")
        return 1
    except BdFailure as e:
        sys.stderr.write(e.error.text + "\n")
        return 1
    event(who, "close", bead, reason=reason)
    prune_events(who.config)
    return 0


def block(who: Identity, bead: BeadId, why: str, store: Beads, say: Callable[[str], None] | None = None) -> int:
    """`tl block`: a person's block, under the claim they hold on the bead now."""
    return block_as(who, fence.hand(store, bead, who.actor), why, store, say)


def block_as(who: Identity, claim: fence.Claim, why: str, st: Beads, say: Callable[[str], None] | None = None) -> int:
    """The bead blocked on the owner; `say` posts its comment (an engine run passes its own poster, Engine.comment). A stale claim is
    refused."""
    # tl-159: a parked bead lets go of its claim; the actor that held it stays live (a loop holds other beads), and a claim nobody works on
    # refused --fresh as 'taken: live claim'. A claim by an engine's actor ends with the run; a person's own claim stays theirs.
    bead = claim.bead
    held = (peek(st, bead) or Bead(id=bead, title="", status="")).assignee
    try:
        fence.check(st, claim)
        st.update(bead, BeadPatch(status="blocked", if_assignee=fence.guard(claim), assignee="" if held.startswith("tl-") else None))
    except fence.Fenced as f:
        sys.stderr.write(f"fenced: {bead} not blocked: {f.why}\n")
        return 1
    except BdFailure as e:
        sys.stderr.write(e.error.text + "\n")
        return 1
    if say is not None:
        say("Blocked: " + why)
    else:
        attempt(st.add_comment, bead, "Blocked: " + why)
    event(who, "block", bead, why=why)
    provenance(st, bead, "suspend", who.session or who.actor, "transcript", {"why": why})
    return 0


def passthrough(store: BdStore, rest: list[str]) -> int:
    """`tl bd ...`: bd with this session's actor and --json, through the adapter."""
    r = store.passthrough(rest)
    sys.stdout.write(r.out)
    sys.stderr.write(r.err)
    return r.code


def register(git: Git, directory: str, who: Identity) -> int:
    """`tl register [DIR]`: add the repo of a working directory to the dashboard."""
    try:
        path = repo_root(directory) if git.toplevel(directory) else None
    except (OSError, ValueError):
        path = None
    if path is None:
        print("tl: not a Git working directory: " + repr(directory), file=sys.stderr)
        return 1
    register_repo(path, who.config)
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
    landed = f"  landed {str(r['sha'])[:12]}" if r.get("outcome") == "landed" and r.get("sha") else ""
    return f"{head}{landed}{tok}  coordinator={r.get('coordinator_session') or '-'}"


def trace(bead: BeadId, last: int, as_json: bool, env: Env) -> int:
    """`tl trace [ID] [--last N] [--json]`: engine runs and every worker session of each, with where its transcript lives."""
    path = ConfigDir(config_dir(env)).traces()
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
            s["transcript"] = s.get("transcript") or transcript_of(env, s.get("family"), s.get("ref"))
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
