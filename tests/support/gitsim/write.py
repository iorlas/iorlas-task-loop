"""The commands that change a checkout: add, commit, checkout, reset, read-tree, write-tree."""
import fnmatch

from . import ignore
from .ctx import Ctx, flags
from .model import HEX40, Fail, W, atomic_write, put_commit, put_tree, snap_of
from .trees import pin


def cmd_add(c: Ctx) -> int:
    fl, rest = flags(c.args)
    spec: list[str] | None = None
    if any(f.startswith("--pathspec-from-file") for f in fl):
        spec = [p for p in c.stdin.decode().split("\0" if "--pathspec-file-nul" in fl else "\n") if p]
    elif rest:
        spec = [p for p in rest if p not in ("--", ".")] or None
    files, rules = c.r.scan()
    idx = c.index()
    mine = lambda p: spec is None or any(p == s or p.startswith(s.rstrip("/") + "/") for s in spec)  # noqa: E731
    universe = {p for p in set(idx) | set(files) if p in idx or not ignore.ignored(p, rules)}
    for s in spec or []:
        if not any(p == s or p.startswith(s.rstrip("/") + "/") for p in set(idx) | set(files)):
            raise Fail(f"fatal: pathspec '{s}' did not match any files", 128)
        if s in files and s not in idx and ignore.ignored(s, rules):
            raise Fail(f"The following paths are ignored by one of your .gitignore files:\n{s}", 1)
    for p in sorted(universe):
        if mine(p):
            if p in files:
                idx[p] = files[p]
            else:
                idx.pop(p, None)
            W.conflicts.get(c.r.key, set()).discard(p)
    c.set_index(idx)
    return 0


def cmd_commit(c: Ctx) -> int:
    msg, args = "", c.args
    for i, a in enumerate(args):
        if a == "-m" or (a.startswith("-") and not a.startswith("--") and a.endswith("m")):
            msg = args[i + 1]
    r = c.r
    if W.conflicts.get(r.key):
        raise Fail("error: Committing is not possible because you have unmerged files.", 128)
    if "-a" in args:  # stage what tracked files changed or lost
        files, idx = r.scan()[0], c.index()
        c.set_index({p: files[p] for p in idx if p in files})
    head, idx = r.head_sha(), c.index()
    if "--amend" in args and head:
        parents, msg = W.commits[head].parents, msg or W.commits[head].msg
    elif idx == r.head_snap() and "--allow-empty" not in args and (head or idx):
        raise Fail("nothing to commit, working tree clean", 1)
    else:
        parents = (head,) if head else ()
    r.move_head(put_commit(idx, parents, msg))
    c.set_index(idx)
    return 0


def force_tree(c: Ctx, old: dict, new: dict) -> None:
    """The working tree as `new` says, over any change of its own (reset --hard)."""
    work = c.r.work
    assert work
    for p in sorted(set(old) | set(new)):
        f = work / p
        if p in new:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(new[p])
        elif f.exists():
            f.unlink()


def cmd_checkout(c: Ctx) -> int:
    r = c.r
    here = r.head_ref() or r.head_sha() or ""
    if "-" in c.args:
        back = W.prev.get(r.key)
        if back is None:
            raise Fail("error: pathspec '-' did not match any file(s) known to git", 1)
        c.args = [back if a == "-" else a for a in c.args]
        if HEX40.fullmatch(back):
            c.args.insert(c.args.index(back), "--detach")
    rc = checkout(c)
    W.prev[r.key] = here
    return rc


def checkout(c: Ctx) -> int:
    args, r = c.args, c.r
    old = r.head_snap()
    for flag in ("-b", "-B"):
        if flag in args:
            i = args.index(flag)
            name, start = args[i + 1], (args[i + 2] if len(args) > i + 2 else "HEAD")
            sha = r.resolve(start)
            if sha is None:
                raise Fail(f"fatal: '{start}' is not a commit and a branch '{name}' cannot be created from it", 128)
            if flag == "-b" and r.ref("refs/heads/" + name):
                raise Fail(f"fatal: a branch named '{name}' already exists", 128)
            pin(r, name)
            r.switch_tree(old, snap_of(sha))
            r.set_ref("refs/heads/" + name, sha)
            r.set_head_branch(name)
            c.set_index(snap_of(sha))
            return 0
    if "--detach" in args:
        after = args[args.index("--detach") + 1:]
        sha = r.resolve(after[0] if after else "HEAD")
        if sha is None:
            raise Fail("fatal: invalid reference", 128)
        r.switch_tree(old, snap_of(sha))
        atomic_write(r.git / "HEAD", sha + "\n")
        c.set_index(snap_of(sha))
        return 0
    name = next(a for a in args if not a.startswith("-"))
    sha = r.ref("refs/heads/" + name)
    if sha is None and (tracked := r.ref("refs/remotes/origin/" + name)):
        sha = tracked
        r.set_ref("refs/heads/" + name, sha)
    if sha is None:
        raise Fail(f"error: pathspec '{name}' did not match any file(s) known to git", 1)
    pin(r, name)
    r.switch_tree(old, snap_of(sha))
    r.set_head_branch(name)
    c.set_index(snap_of(sha))
    return 0


def cmd_reset(c: Ctx) -> int:
    fl, rest = flags(c.args)
    r = c.r
    sha = r.resolve(rest[0] if rest else "HEAD")
    if sha is None:
        raise Fail(f"fatal: ambiguous argument '{rest[0]}': unknown revision or path not in the working tree.", 128)
    old_idx, old_head = c.index(), r.head_snap()
    r.move_head(sha)
    if "--soft" in fl:
        c.set_index(old_idx)
        return 0
    c.set_index(snap_of(sha))
    W.conflicts.pop(r.key, None)
    if "--hard" in fl:
        force_tree(c, old_head, snap_of(sha))
    return 0


def cmd_branch(c: Ctx) -> int:
    fl, rest = flags(c.args)
    r = c.r
    if "-m" in fl or "-M" in fl:
        old, new = (rest if len(rest) == 2 else [r.head_ref(), rest[0]])
        sha = r.ref("refs/heads/" + old)
        if sha is None:
            raise Fail(f"error: refname refs/heads/{old} not found", 1)
        r.set_ref("refs/heads/" + new, sha)
        (r.git / "refs" / "heads" / old).unlink()
        if r.head_ref() == old:
            r.set_head_branch(new)
    elif "-D" in fl or "-d" in fl:
        for name in rest:
            (r.git / "refs" / "heads" / name).unlink(missing_ok=True)
    elif rest and "--list" not in fl:
        sha = r.resolve(rest[1] if len(rest) > 1 else "HEAD")
        if sha is None or r.ref("refs/heads/" + rest[0]):
            raise Fail(f"fatal: a branch named '{rest[0]}' already exists" if sha else "fatal: not a valid object name", 128)
        r.set_ref("refs/heads/" + rest[0], sha)
    else:
        for name in r.heads():
            if rest and not fnmatch.fnmatch(name, rest[0]):
                continue
            c.say(("* " if name == r.head_ref() else "  ") + name)
    return 0


def cmd_update_ref(c: Ctx) -> int:
    _, rest = flags(c.args)
    sha = c.r.resolve(rest[1])
    if sha is None:
        raise Fail(f"fatal: {rest[1]}: not a valid SHA1", 128)
    c.r.set_ref(rest[0], sha)
    return 0


def cmd_read_tree(c: Ctx) -> int:
    _, rest = flags(c.args)
    sha = c.r.resolve(rest[0])
    if sha is None:
        raise Fail(f"fatal: failed to unpack tree object {rest[0]}", 128)
    c.set_index(snap_of(sha))
    return 0


def cmd_write_tree(c: Ctx) -> int:
    c.say(put_tree(c.index()))
    return 0
