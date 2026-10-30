"""The commands that list refs and compare histories: for-each-ref, ls-remote, cherry, tag, and branch --merged."""
import difflib
import fnmatch

from .ctx import Ctx, flags
from .diffs import lines_of
from .model import Fail, Repo, W, is_ancestor, snap_of, walk
from .remote import remote_of


def all_refs(r: Repo) -> dict[str, str]:
    """Every loose ref of the repo, by full refname."""
    out: dict[str, str] = {}
    root = r.common / "refs"
    for p in sorted(root.rglob("*")) if root.is_dir() else []:
        if p.is_file():
            out[p.relative_to(r.common).as_posix()] = p.read_text(encoding="utf-8").strip()
    return out


def short(name: str) -> str:
    for pre in ("refs/heads/", "refs/remotes/", "refs/tags/"):
        if name.startswith(pre):
            return name[len(pre):]
    return name


def render(fmt: str, name: str, oid: str) -> str:
    """A for-each-ref / branch --format string with the three fields the port uses."""
    return (fmt.replace("%(refname:short)", short(name)).replace("%(refname)", name).replace("%(objectname)", oid)
            .replace("%x00", "\0"))


def format_of(fl: list[str], default: str) -> str:
    return next((f[len("--format="):] for f in fl if f.startswith("--format=")), default)


def cmd_for_each_ref(c: Ctx) -> int:
    fl, rest = flags(c.args)
    fmt = format_of(fl, "%(objectname) %(refname)")
    for name, oid in all_refs(c.r).items():
        if not rest or any(name.startswith(p) if p.endswith("/") else name == p or name.startswith(p + "/") for p in rest):
            c.say(render(fmt, name, oid))
    return 0


def cmd_ls_remote(c: Ctx) -> int:
    _, rest = flags(c.args)
    remote = remote_of(c, rest[0])
    for name, oid in all_refs(remote).items():
        wanted = len(rest) == 1 or any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(name, "*/" + p) for p in rest[1:])
        if name.startswith(("refs/heads/", "refs/tags/")) and wanted:
            c.say(f"{oid}\t{name}")
    return 0


def patch_of(sha: str) -> frozenset[tuple[str, tuple[str, ...]]]:
    """What a commit changes, as the lines it removes and adds per file (patch-id: where in the file does not count)."""
    cm = W.commits[sha]
    before = snap_of(cm.parents[0]) if cm.parents else {}
    after = snap_of(sha)
    out = set()
    for p in set(before) | set(after):
        if before.get(p) != after.get(p):
            d = difflib.unified_diff(lines_of(before.get(p, b"")), lines_of(after.get(p, b"")), n=0)
            out.add((p, tuple(x for x in d if x[:1] in "+-" and x[:3] not in ("+++", "---"))))
    return frozenset(out)


def cmd_cherry(c: Ctx) -> int:
    _, rest = flags(c.args)
    up, head = c.r.resolve(rest[0]), c.r.resolve(rest[1] if len(rest) > 1 else "HEAD")
    if up is None or head is None:
        raise Fail(f"fatal: unknown commit {rest[0] if up is None else rest[1]}", 128)
    there = {patch_of(cm.sha) for cm in walk([up], [head])}
    for cm in reversed(walk([head], [up])):
        c.say(("- " if patch_of(cm.sha) in there else "+ ") + cm.sha)
    return 0


def cmd_tag(c: Ctx) -> int:
    fl, rest = flags(c.args)
    r = c.r
    if "-d" in fl:
        for name in rest:
            (r.common / "refs" / "tags" / name).unlink(missing_ok=True)
        return 0
    if not rest:
        for name in sorted(n for n in all_refs(r) if n.startswith("refs/tags/")):
            c.say(short(name))
        return 0
    sha = r.resolve(rest[1] if len(rest) > 1 else "HEAD")
    if sha is None:
        raise Fail(f"fatal: Failed to resolve '{rest[1] if len(rest) > 1 else 'HEAD'}' as a valid ref.", 128)
    if r.ref("refs/tags/" + rest[0]):
        raise Fail(f"fatal: tag '{rest[0]}' already exists", 128)
    r.set_ref("refs/tags/" + rest[0], sha)
    return 0


def list_merged(c: Ctx, into: str, fl: list[str]) -> int:
    """branch --merged <into> [--format=...]: the local branches whose tip is an ancestor of `into`."""
    r = c.r
    tip = r.resolve(into)
    if tip is None:
        raise Fail(f"error: malformed object name {into}", 129)
    fmt = format_of(fl, "  %(refname:short)")
    for name, oid in r.heads().items():
        if is_ancestor(oid, tip):
            c.say(render(fmt, "refs/heads/" + name, oid))
    return 0


