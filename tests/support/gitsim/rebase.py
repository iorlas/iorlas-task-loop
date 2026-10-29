"""rebase onto a ref, a file at a time: a path changed on both sides to different contents is a conflict (markers in the file, the path
unmerged until it is added), anything else replays clean. `--continue` commits what was added, `--abort` puts everything back."""
import shutil
from typing import Any

from .ctx import Ctx, flags
from .model import Fail, Snap, W, atomic_write, is_ancestor, merge_base, put_commit, snap_of, walk
from .status import rows
from .write import force_tree


def marks(ours: bytes, theirs: bytes, label: str) -> bytes:
    return b"<<<<<<< HEAD\n" + ours + b"=======\n" + theirs + b">>>>>>> " + label.encode() + b"\n"


def replay(c: Ctx, st: dict[str, Any]) -> int:
    r = c.r
    while st["todo"]:
        cm = st["todo"].pop(0)
        before = snap_of(cm.parents[0]) if cm.parents else {}
        after, tip = snap_of(cm.sha), snap_of(st["tip"])
        new, bad = dict(tip), []
        for p in sorted(set(before) | set(after)):
            b, a, t = before.get(p), after.get(p), tip.get(p)
            if a in (b, t):
                continue
            if t != b:
                bad.append(p)
            elif a is None:
                new.pop(p, None)
            else:
                new[p] = a
        if bad:
            r.switch_tree(tip, new)
            for p in bad:
                if tip.get(p) is not None and after.get(p) is not None:
                    assert r.work
                    (r.work / p).write_bytes(marks(tip[p], after[p], f"{cm.sha[:7]} ({cm.msg})"))
            st["cur"] = cm
            W.conflicts[r.key] = set(bad)
            c.set_index(new)
            c.err += [f"CONFLICT (content): Merge conflict in {p}" for p in bad] + [f"error: could not apply {cm.sha[:7]}... {cm.msg}"]
            return 1
        if new != tip:
            r.switch_tree(tip, new)
            st["tip"] = put_commit(new, (st["tip"],), cm.msg)
    finish(c, st)
    return 0


def finish(c: Ctx, st: dict[str, Any]) -> None:
    r = c.r
    r.set_ref("refs/heads/" + st["branch"], st["tip"])
    r.set_head_branch(st["branch"])
    c.set_index(snap_of(st["tip"]))
    shutil.rmtree(r.git / "rebase-merge", ignore_errors=True)
    W.rebases.pop(r.key, None)
    W.conflicts.pop(r.key, None)


def start(c: Ctx, upstream: str) -> int:
    r = c.r
    onto, head, branch = r.resolve(upstream), r.head_sha(), r.head_ref()
    if onto is None or head is None:
        raise Fail(f"fatal: invalid upstream '{upstream}'", 128)
    if any(x != "?" for _, x, _ in rows(c)):
        raise Fail("error: cannot rebase: You have unstaged changes.", 1)
    if is_ancestor(onto, head):
        return 0
    old = snap_of(head)
    if merge_base(head, onto) == head:
        r.switch_tree(old, snap_of(onto))
        r.move_head(onto)
        c.set_index(snap_of(onto))
        return 0
    st = {"branch": branch, "orig": head, "onto": onto, "tip": onto, "cur": None, "todo": list(reversed(walk([head], [onto])))}
    r.switch_tree(old, snap_of(onto))
    atomic_write(r.git / "HEAD", onto + "\n")
    (r.git / "rebase-merge").mkdir(exist_ok=True)
    W.rebases[r.key] = st
    c.set_index(snap_of(onto))
    return replay(c, st)


def cont(c: Ctx) -> int:
    st = W.rebases.get(c.r.key)
    if st is None:
        raise Fail("fatal: No rebase in progress?", 128)
    if W.conflicts.get(c.r.key):
        raise Fail("error: Committing is not possible because you have unmerged files.", 1)
    idx: Snap = c.index()
    if idx != snap_of(st["tip"]):
        st["tip"] = put_commit(idx, (st["tip"],), st["cur"].msg)
    return replay(c, st)


def abort(c: Ctx) -> int:
    r = c.r
    st = W.rebases.get(r.key)
    if st is None:
        raise Fail("fatal: No rebase in progress?", 128)
    mine = c.index()
    here = {**snap_of(st["tip"]), **{p: v for p, v in r.scan()[0].items() if p in mine}}
    force_tree(c, here, snap_of(st["orig"]))
    r.set_head_branch(st["branch"])
    c.set_index(snap_of(st["orig"]))
    shutil.rmtree(r.git / "rebase-merge", ignore_errors=True)
    W.rebases.pop(r.key, None)
    W.conflicts.pop(r.key, None)
    return 0


def cmd_rebase(c: Ctx) -> int:
    fl, rest = flags(c.args)
    if "--continue" in fl:
        return cont(c)
    if "--abort" in fl:
        return abort(c)
    return start(c, rest[0])
