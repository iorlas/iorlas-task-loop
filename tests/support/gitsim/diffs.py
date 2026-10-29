"""diff: the text of the change between two trees, in git's unified format."""
import difflib
import re

from . import ignore
from .ctx import Ctx, blob, flags
from .model import Snap, W, snap_of


def lines_of(data: bytes) -> list[str]:
    out = []
    for ln in data.decode("utf-8", "replace").splitlines(keepends=True):
        out += [ln] if ln.endswith("\n") else [ln + "\n", "\\ No newline at end of file\n"]
    return out


def file_diff(path: str, a: bytes | None, b: bytes | None) -> list[str]:
    head = [f"diff --git a/{path} b/{path}\n"]
    if a is None:
        head.append("new file mode 100644\n")
    elif b is None:
        head.append("deleted file mode 100644\n")
    head.append(f"index {blob(a)[:7] if a is not None else '0000000'}..{blob(b)[:7] if b is not None else '0000000'}"
                f"{' 100644' if a is not None and b is not None else ''}\n")
    body = list(difflib.unified_diff(lines_of(a or b""), lines_of(b or b""), "a/" + path if a is not None else "/dev/null",
                                     "b/" + path if b is not None else "/dev/null", n=3))
    return head + [x if x.endswith("\n") else x + "\n" for x in body]


def changed(a: Snap, b: Snap, spec: list[str]) -> list[str]:
    return [p for p in sorted(set(a) | set(b)) if a.get(p) != b.get(p) and (not spec or ignore.spec_match(p, spec))]


def stat_lines(a: Snap, b: Snap, paths: list[str]) -> list[str]:
    out, plus, minus = [], 0, 0
    for p in paths:
        d = [x for x in file_diff(p, a.get(p), b.get(p)) if x[:1] in "+-" and x[:3] not in ("+++", "---")]
        add, rem = sum(x[0] == "+" for x in d), sum(x[0] == "-" for x in d)
        plus, minus = plus + add, minus + rem
        out.append(f" {p} | {add + rem} {'+' * add}{'-' * rem}")
    n = len(paths)
    tail = f" {n} file{'s' if n != 1 else ''} changed"
    tail += f", {plus} insertion{'s' if plus != 1 else ''}(+)" if plus else ""
    tail += f", {minus} deletion{'s' if minus != 1 else ''}(-)" if minus else ""
    return [*out, tail] if paths else []


MARKER = re.compile(r"^(<<<<<<< |=======$|>>>>>>> )")


def check_lines(path: str, a: bytes | None, b: bytes | None) -> list[str]:
    """`git diff --check` for one file: a hit per added line with a conflict marker or trailing whitespace, git's wording."""
    old, new = lines_of(a or b""), lines_of(b or b"")
    out = []
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            for n in range(j1, j2):
                text = new[n].rstrip("\n")
                if text.startswith("\\ No newline"):
                    continue
                if MARKER.match(text):
                    out.append(f"{path}:{n + 1}: leftover conflict marker")
                elif text != text.rstrip():
                    out += [f"{path}:{n + 1}: trailing whitespace.", "+" + text]
    return out


def say_check(c: Ctx, hits: list[str]) -> int:
    for ln in hits:
        c.say(ln)
    return 2 if hits else 0  # git diff --check: exit 2 when it reports anything


def cmd_diff(c: Ctx) -> int:
    fl, rest = flags(c.args)
    rest, spec = (rest[: rest.index("--")], rest[rest.index("--") + 1:]) if "--" in rest else (rest, [])
    if "--diff-filter=U" in fl:
        for p in sorted(W.conflicts.get(c.r.key, set())):
            c.say(p)
        return 0
    if "--cached" in fl:
        a, b = c.r.head_snap(), c.index()
    else:
        shas = [c.r.resolve(r) for r in rest]
        a, b = (snap_of(s) for s in [*shas, None, None][:2]) if len(shas) == 2 else (snap_of(shas[0]), c.r.scan()[0])
    paths = changed(a, b, spec)
    if "--check" in fl:
        return say_check(c, [x for p in paths for x in check_lines(p, a.get(p), b.get(p))])
    if "--name-only" in fl:
        for p in paths:
            c.say(p)
    elif "--stat" in fl:
        for ln in stat_lines(a, b, paths):
            c.say(ln)
    else:
        for p in paths:
            c.raw("".join(file_diff(p, a.get(p), b.get(p))).encode())
    return 1 if "--quiet" in fl and paths else 0  # --quiet: exit 1 when there is a difference
