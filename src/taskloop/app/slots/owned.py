"""Worktrees tl owns: the one function that makes a worktree (`create`, which records who made it), the survey that tells owned from
foreign from orphaned, and `clean`, which removes only an owned worktree that is merged and clean and says what a refusal would lose."""
import contextlib
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Git, SlotGit
from taskloop.contracts.slots import SlotGitError
from taskloop.contracts.worktrees import Owned
from taskloop.stores.files import FileDocSet

SHOWN = 8  # lines of a loss printed per worktree


def loop_path(repo: str, name: str) -> str:
    """A loop session's worktree (slots off): the one place such a worktree is named."""
    return str(Path(repo) / ".worktrees" / ("loop-" + name))


def docs(cfg: ConfigDir, repo_key: str) -> FileDocSet[Owned]:
    return FileDocSet(lambda key: cfg.worktree_record(repo_key, key), Owned)


def key_of(path: str) -> str:
    rp = os.path.realpath(path)
    return f"{Path(rp).name}-{hashlib.sha1(rp.encode()).hexdigest()[:8]}"


def create(git: SlotGit, cfg: ConfigDir, repo_key: str, repo: str, path: str, ref: str, *, kind: str, run: str, bead: str, host: str,
           now: float, exclude: Callable[[], None]) -> None:
    """Make the worktree at `path` from `ref` (when it is not there) and record its owner. Every worktree the engine uses comes from here;
    raises SlotGitError when git cannot make it."""
    exclude()
    if not Path(path).is_dir():
        with contextlib.suppress(SlotGitError):
            git.fetch(repo)
        git.add_worktree(repo, path, ref)
    store = docs(cfg, repo_key).of(key_of(path))
    if store.get() is None:
        store.write(Owned(path=os.path.realpath(path), repo=repo, kind=kind, run=run, bead=bead, host=host, created=now))


@dataclass(frozen=True)
class Row:
    path: str
    branch: str
    state: str  # owned | foreign | orphaned
    note: str
    rec: Owned | None = None


def survey(git: Git, cfg: ConfigDir, repo_key: str, repo: str, slots_dir: str) -> list[Row]:
    """Every worktree of the repo besides the main one, and every record whose worktree is gone. owned: tl made it (it has a record).
    orphaned: a record with no worktree, or a worktree in tl's own folders (.worktrees, the slot dir) with no record: nothing proves
    it is ours. foreign: anything else (Claude Code's .claude/worktrees, other tools): listed, never touched."""
    store = docs(cfg, repo_key)
    names = store.keys()
    recs = {os.path.realpath(r.path): r for k in names if (r := store.of(k).get()) is not None}
    ours = {os.path.realpath(Path(repo) / ".worktrees"), os.path.realpath(slots_dir)}
    rows: list[Row] = []
    seen: set[str] = set()
    for c in git.checkouts(repo):
        rp = os.path.realpath(c.path)
        if c.main or not os.path.isdir(c.path):  # a folder deleted by hand: git still lists it until it prunes
            continue
        seen.add(rp)
        if (rec := recs.get(rp)) is not None:
            rows.append(Row(c.path, c.branch, "owned", f"{rec.kind} run {rec.run} bead {rec.bead or '-'} host {rec.host}", rec))
        elif os.path.dirname(rp) in ours:
            rows.append(Row(c.path, c.branch, "orphaned", "no ownership record"))
        else:
            rows.append(Row(c.path, c.branch, "foreign", "not made by tl"))
    rows += [Row(rp, "", "orphaned", "worktree gone", rec) for rp, rec in recs.items() if rp not in seen]
    return sorted(rows, key=lambda r: (r.state, r.path))


def losses(git: Git, wt: str, base: str) -> list[str]:
    """What removing the worktree `wt` would lose: its commits not on `base` (a patch already there counts as merged), then the changed
    and untracked files. Empty: it is merged and clean."""
    out: list[str] = []
    try:
        if not git.rev_parse(wt, base):
            return [f"{base} does not resolve here: cannot tell what is merged"]
        mine = {p.oid for p in git.cherry(wt, base, "HEAD") if not p.upstream}
        if mine:
            out.append(f"{len(mine)} commit(s) not on {base}:")
            out += [f"  {r.oid[:8]} {r.subject}" for r in git.log(wt, ["HEAD"], [base]) if r.oid in mine]
        out += [("  untracked " if r.untracked else "  changed ") + r.path for r in git.status(wt, all_untracked=True)]
    except SlotGitError as e:
        return [f"git cannot say: {e.tail}"]
    return out


def clean(git: Git, cfg: ConfigDir, repo_key: str, repo: str, slots_dir: str, base: str, count: int, busy: Callable[[str], str],
          say: Callable[[str], None] = print) -> int:
    """Remove the owned worktrees that are merged and clean; 1 when one stayed. A slot within slots.count stays (it is in use, not
    stale), so does one an engine runs in. A record whose worktree is gone is dropped. Foreign and unrecorded worktrees are not touched."""
    store, refused = docs(cfg, repo_key), 0
    for row in survey(git, cfg, repo_key, repo, slots_dir):
        rec = row.rec
        if rec is None:
            continue
        if row.note == "worktree gone":
            store.of(key_of(row.path)).delete()
            say(f"DROPPED record of {row.path} (worktree gone)")
            continue
        name = Path(row.path).name
        if rec.kind == "slot" and (not count or name in {f"s{i}" for i in range(1, count + 1)}):
            say(f"KEPT {row.path}: slot {name} is within slots.count")
            continue
        if why := busy(row.path):
            say(f"REFUSED {row.path}: busy: {why}")
            refused += 1
            continue
        if lost := losses(git, row.path, base):
            say(f"REFUSED {row.path}: removing it would lose")
            for line in lost[:SHOWN]:
                say("  " + line)
            if len(lost) > SHOWN:
                say(f"  ... and {len(lost) - SHOWN} more")
            refused += 1
        elif git.remove_worktree(repo, row.path):
            store.of(key_of(row.path)).delete()
            say(f"REMOVED {row.path}")
        else:
            say(f"REFUSED {row.path}: git would not remove it")
            refused += 1
    git.prune_worktrees(repo)
    return 1 if refused else 0
