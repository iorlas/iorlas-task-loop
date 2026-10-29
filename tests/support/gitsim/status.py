"""status, and the pieces of it that add, commit and diff share: what differs between HEAD, the index and the working tree."""
from . import ignore
from .ctx import Ctx, blob, flags
from .model import W


def rows(c: Ctx) -> list[tuple[str, str, str]]:
    """(path, X, Y) of every path that differs from HEAD or the index, '??' for an untracked one."""
    repo = c.r
    head, idx = repo.head_snap(), c.index()
    files, rules = repo.scan()
    bad = W.conflicts.get(repo.key, set())
    out = []
    for p in sorted(set(head) | set(idx) | set(files)):
        h, i, w = head.get(p), idx.get(p), files.get(p)
        if p in bad:
            out.append((p, "U", "U"))
        elif i is None and h is None:
            if w is not None and not ignore.ignored(p, rules):
                out.append((p, "?", "?"))
        else:
            x = " " if h == i else "A" if h is None else "D" if i is None else "M"
            y = " " if i is None or w == i else "D" if w is None else "M"
            if (x, y) != (" ", " "):
                out.append((p, x, y))
    return out


def collapse(paths: list[str], tracked: set[str]) -> list[str]:
    """Untracked paths as `git status` shows them without --untracked-files=all: a folder with nothing tracked in it is one line."""
    out: list[str] = []
    for p in paths:
        parts = p.split("/")
        shown = p
        for n in range(1, len(parts)):
            d = "/".join(parts[:n]) + "/"
            if not any(t.startswith(d) for t in tracked):
                shown = d
                break
        if shown not in out:
            out.append(shown)
    return out


def cmd_status(c: Ctx) -> int:
    fl, _ = flags(c.args)
    rs = rows(c)
    repo = c.r
    if "--porcelain=v2" in fl:
        head = repo.head_sha()
        c.say("# branch.oid " + (head or "(initial)"), "\0")
        c.say("# branch.head " + (repo.head_ref() or "(detached)"), "\0")
        h, idx = repo.head_snap(), c.index()
        for p, x, y in rs:
            if x == "?":
                c.say(f"? {p}", "\0")
            else:
                hh, ii = blob(h[p]) if p in h else "0" * 40, blob(idx[p]) if p in idx else "0" * 40
                c.say(f"1 {x.replace(' ', '.')}{y.replace(' ', '.')} N... 100644 100644 100644 {hh} {ii} {p}", "\0")
        return 0
    end = "\0" if "-z" in fl else "\n"
    untracked = [p for p, x, _ in rs if x == "?"]
    if "--untracked-files=all" not in fl:
        untracked = collapse(untracked, set(c.index()) | set(repo.head_snap()))
    for p, x, y in rs:
        if x != "?":
            c.say(f"{x}{y} {p}", end)
    for p in untracked:
        c.say(f"?? {p}", end)
    return 0
