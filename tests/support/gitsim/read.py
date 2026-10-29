"""The commands that only look: rev-parse, log, show, ls-tree, ls-files, grep, config, merge-base and the small ones."""
import re
from pathlib import Path

from . import ignore
from .ctx import Ctx, blob, flags
from .model import Fail, W, is_ancestor, merge_base, snap_of, walk


def cmd_rev_parse(c: Ctx) -> int:
    fl, rest = flags(c.args)
    r = c.r
    if "--git-common-dir" in fl:
        c.say(str(r.common))
    elif "--absolute-git-dir" in fl or "--git-dir" in fl:
        c.say(str(r.git))
    if "--show-toplevel" in fl:
        if r.work is None:
            raise Fail("fatal: this operation must be run in a work tree", 128)
        c.say(str(r.work))
    for name in rest:
        sha = r.resolve(name)
        if sha is None:
            if "--verify" in fl:
                raise Fail("" if "-q" in fl else "fatal: Needed a single revision", 1 if "-q" in fl else 128)
            raise Fail(f"fatal: ambiguous argument '{name}': unknown revision or path not in the working tree.", 128)
        c.say(sha)
    return 0


def cmd_symbolic_ref(c: Ctx) -> int:
    fl, _ = flags(c.args)
    b = c.r.head_ref()
    if not b:
        raise Fail("" if "-q" in fl else "fatal: ref HEAD is not a symbolic ref", 1 if "-q" in fl else 128)
    c.say(b if "--short" in fl else "refs/heads/" + b)
    return 0


def cmd_log(c: Ctx) -> int:
    fl, rest = flags(c.args)
    limit = None
    args = list(c.args)
    for i, a in enumerate(args):
        if a == "-n" and i + 1 < len(args):
            limit = int(args[i + 1])
            rest = [x for x in rest if x != args[i + 1]]
        elif re.fullmatch(r"-\d+", a):
            limit = int(a[1:])
    inc, exc = c.revs(rest or ["HEAD"]) if c.r.head_sha() or rest else ([], [])
    for cm in walk(inc, exc)[:limit]:
        c.say(f"{cm.sha[:7]} {cm.msg}" if "--oneline" in fl else cm.msg.splitlines()[0] if cm.msg else "")
    return 0


def cmd_rev_list(c: Ctx) -> int:
    fl, rest = flags(c.args)
    inc, exc = c.revs(rest)
    found = walk(inc, exc)
    if "--count" in fl:
        c.say(str(len(found)))
    else:
        for cm in found:
            c.say(cm.sha)
    return 0


def cmd_show(c: Ctx) -> int:
    _, rest = flags(c.args)
    rev, _, path = rest[0].partition(":")
    sha = c.r.resolve(rev)
    if sha is None:
        raise Fail(f"fatal: bad revision '{rev}'", 128)
    if ":" in rest[0]:
        snap = snap_of(sha)
        if path not in snap:
            raise Fail(f"fatal: path '{path}' does not exist in '{rev}'", 128)
        c.raw(snap[path])
        return 0
    cm = W.commits[sha]
    before = snap_of(cm.parents[0]) if cm.parents else {}
    after = snap_of(sha)
    for p in sorted(set(before) | set(after)):
        if before.get(p) != after.get(p):
            c.say(p)
    return 0


def cmd_ls_tree(c: Ctx) -> int:
    fl, rest = flags(c.args)
    end = "\0" if "-z" in fl else "\n"
    sha = c.r.resolve(rest[0]) if rest else None
    if sha is None:
        raise Fail("fatal: Not a valid object name", 128)
    snap = snap_of(sha)
    want = rest[1:]
    seen: set[str] = set()
    for p in sorted(snap):
        if want and p not in want:
            continue
        top, slash, _ = p.partition("/")
        if "-r" not in fl and slash:
            if top in seen:
                continue
            seen.add(top)
            c.say(top if "--name-only" in fl else f"040000 tree {'0' * 40}\t{top}", end)
        else:
            c.say(p if "--name-only" in fl else f"100644 blob {blob(snap[p])}\t{p}", end)
    return 0


def cmd_ls_files(c: Ctx) -> int:
    fl, rest = flags(c.args)
    end = "\0" if "-z" in fl else "\n"
    files, rules = c.r.scan()
    idx = c.index()
    spec = rest[rest.index("--") + 1:] if "--" in rest else []
    if "-o" in fl:
        for p in sorted(files):
            if p not in idx and ("-i" in fl) == ignore.ignored(p, rules) and (not spec or ignore.spec_match(p, spec)):
                c.say(p, end)
    else:
        for p in sorted(idx):
            c.say(p, end)
    return 0


def cmd_grep(c: Ctx) -> int:
    fl, rest = flags(c.args)
    pat = rest[0]
    rx = re.compile(re.escape(pat) if "-F" in fl else pat)
    if "-w" in fl:
        rx = re.compile(r"\b(?:" + rx.pattern + r")\b")
    hits = False
    for p in sorted(c.index()):
        data = c.r.read_work(p)
        if data is None or (b"\0" in data and "-I" in fl):
            continue
        lines = [(n, ln) for n, ln in enumerate(data.decode("utf-8", "replace").splitlines(), 1) if rx.search(ln)]
        if lines:
            hits = True
            if "-l" in fl:
                c.say(p)
            else:
                for n, ln in lines:
                    c.say(f"{p}:{n}:{ln}" if "-n" in fl else f"{p}:{ln}")
    return 0 if hits else 1


def cmd_config(c: Ctx) -> int:
    fl, rest = flags(c.args)
    cfg = c.r.config() if c.repo else {}
    if "--get" in fl:
        if rest[0] not in cfg:
            return 1
        c.say(cfg[rest[0]])
    elif "--get-regexp" in fl:
        hit = False
        for k, v in cfg.items():
            if re.search(rest[0], k):
                hit = True
                c.say(f"file:{c.r.git}/config\t{k} {v}" if "--show-origin" in fl else f"{k} {v}")
        return 0 if hit else 1
    elif len(rest) == 2:
        c.r.set_config(rest[0].lower(), rest[1])
    return 0


def cmd_merge_base(c: Ctx) -> int:
    fl, rest = flags(c.args)
    shas = [c.r.resolve(x) for x in rest]
    if None in shas:
        raise Fail("fatal: Not a valid object name", 128)
    a, b = shas[0], shas[1]
    assert a and b
    if "--is-ancestor" in fl:
        return 0 if is_ancestor(a, b) else 1
    base = merge_base(a, b)
    if base is None:
        return 1
    c.say(base)
    return 0


def cmd_remote(c: Ctx) -> int:
    url = c.r.config().get(f"remote.{c.args[-1]}.url")
    if c.args[0] != "get-url" or not url:
        raise Fail(f"error: No such remote '{c.args[-1]}'", 2)
    c.say(url)
    return 0


def cmd_check_ignore(c: Ctx) -> int:
    path = c.opts.get("core.excludesfile")
    rules = ignore.rules_of("", Path(path).read_text(encoding="utf-8")) if path else []
    hits = [p for p in c.stdin.decode().split("\0") if p and ignore.ignored(p, rules)]
    for p in hits:
        c.say(p, "\0")
    return 0 if hits else 1
