"""git worktree: linked checkouts of one repo, each with its own HEAD and index and the refs of the common dir."""
import shutil
from pathlib import Path

from .ctx import Ctx, flags
from .model import Fail, Repo, W, atomic_write, snap_of
from .status import rows


def linked(r: Repo) -> list[tuple[Path, Path]]:
    """(git dir, working folder) of every linked worktree of the repo."""
    out = []
    for d in sorted((r.common / "worktrees").glob("*")) if (r.common / "worktrees").is_dir() else []:
        try:
            out.append((d, Path((d / "gitdir").read_text(encoding="utf-8").strip()).parent))
        except OSError:
            continue
    return out


def checked_out(r: Repo, branch: str) -> str:
    """The folder that has `branch` checked out, other than r's own ('' when none)."""
    for git, work in [(r.common, r.common.parent), *linked(r)]:
        if git != r.git and Repo(git, work).head_ref() == branch:
            return str(work)
    return ""


def pin(r: Repo, branch: str) -> None:
    where = checked_out(r, branch)
    if where:
        raise Fail(f"fatal: '{branch}' is already used by worktree at '{where}'", 128)


def listing(c: Ctx) -> int:
    r = c.r
    for git, work in [(r.common, r.common.parent), *linked(r)]:
        wr = Repo(git, work)
        c.say(f"worktree {work}")
        c.say(f"HEAD {wr.head_sha() or '0' * 40}")
        c.say(f"branch refs/heads/{wr.head_ref()}" if wr.head_ref() else "detached")
        c.say()
    return 0


def add(c: Ctx) -> int:
    fl, rest = flags(c.args)
    args = c.args
    r = c.r
    new = args[args.index("-b") + 1] if "-b" in args else ""
    pos = [a for a in rest if a != new]
    dest = (Path(c.cwd) / pos[0]).resolve()
    ref = pos[1] if len(pos) > 1 else ""
    sha = r.resolve(ref or ("HEAD" if new or "--detach" in fl else dest.name))
    if sha is None:
        raise Fail(f"fatal: invalid reference: {ref}", 128)
    branch = new or ("" if "--detach" in fl else ref or dest.name)
    if branch and not new:
        pin(r, branch)
    if new:
        if r.ref("refs/heads/" + new):
            raise Fail(f"fatal: a branch named '{new}' already exists", 128)
        r.set_ref("refs/heads/" + new, sha)
    name = dest.name
    gd = r.common / "worktrees" / name
    atomic_write(gd / "HEAD", f"ref: refs/heads/{branch}\n" if branch else sha + "\n")
    atomic_write(gd / "commondir", "../..\n")
    atomic_write(gd / "gitdir", str(dest / ".git") + "\n")
    atomic_write(dest / ".git", f"gitdir: {gd}\n")
    Repo(gd, dest).switch_tree({}, snap_of(sha))
    W.index[str(gd / "index")] = dict(snap_of(sha))
    return 0


def remove(c: Ctx) -> int:
    fl, rest = flags(c.args)
    dest = (Path(c.cwd) / rest[0]).resolve()
    for git, work in linked(c.r):
        if work.resolve() == dest:
            changed = any(x != " " or y != " " for _, x, y in rows(Ctx(Repo(git, work), [], c.env, c.cwd)))
            if changed and "--force" not in fl and "-f" not in fl:
                raise Fail(f"fatal: '{dest}' contains modified or untracked files, use --force to delete it", 128)
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(git, ignore_errors=True)
            return 0
    raise Fail(f"fatal: '{rest[0]}' is not a working tree", 128)


def prune(c: Ctx) -> int:
    for git, work in linked(c.r):
        if not work.exists():
            shutil.rmtree(git, ignore_errors=True)
    return 0


def cmd_worktree(c: Ctx) -> int:
    sub = {"list": listing, "add": add, "remove": remove, "prune": prune}.get(c.args[0] if c.args else "")
    if sub is None:
        raise Fail("fatal: unknown worktree subcommand", 129)
    c.args = c.args[1:]
    return sub(c)
