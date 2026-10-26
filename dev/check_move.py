#!/usr/bin/env python3
"""Check that a change only moved code: `python3 dev/check_move.py BASE HEAD [--rename self=eng]`.

Parses every changed .py at both revs. Each function/class removed from a
file must exist with an identical ast.dump (decorators, docstring included)
as a definition newly added in another file of the change. With
`--rename OLD=NEW`, that one name rename is also accepted (old side).
Exit 0 only for a pure move: any def changed in place, added but not a
moved def, removed without destination, or changed top-level statement
fails and is named (module level as PATH:<module>). Import lines, blank lines and comments may change.
`--allow-edit PATH:QUALNAME` (repeatable) permits a named edited/added def (PATH:<module> for top-level statements).
Stdlib only.
"""
import argparse
import ast
import subprocess
import sys

DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def git(*args):
    r = subprocess.run(("git",) + args, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True)
    if r.returncode:
        raise SystemExit("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


def changed_py(base, head):
    out = git("diff", "--name-only", "--no-renames", base, head, "--")
    return [p for p in out.splitlines() if p.endswith(".py")]


def show(rev, path):
    r = subprocess.run(["git", "show", "%s:%s" % (rev, path)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    return r.stdout if r.returncode == 0 else ""


def collect(src, path):
    """({qualname: node}, [dump of non-def, non-import top-level statements]).

    Recurses into classes only; a function's nested defs belong to its dump.
    """
    found, rest = {}, []

    def walk(body, prefix, top):
        for node in body:
            if isinstance(node, DEFS):
                q = prefix + node.name
                found[q] = node
                if isinstance(node, ast.ClassDef):
                    walk(node.body, q + ".", False)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            elif top:
                rest.append(ast.dump(node))

    try:
        walk(ast.parse(src, path).body, "", True)
    except SyntaxError as e:
        raise SystemExit("cannot parse %s: %s" % (path, e))
    return found, rest


class Renamer(ast.NodeTransformer):
    def __init__(self, old, new):
        self.old, self.new = old, new

    def visit_Name(self, n):
        if n.id == self.old:
            n.id = self.new
        return n

    def visit_arg(self, n):
        if n.arg == self.old:
            n.arg = self.new
        self.generic_visit(n)
        return n


def dump(node):
    """ast.dump; a class is dumped as its shell, members are checked one by one."""
    if isinstance(node, ast.ClassDef):
        import copy
        node = copy.copy(node)
        node.body = [n for n in node.body
                     if not isinstance(n, DEFS + (ast.Import, ast.ImportFrom))]
    return ast.dump(node)


def renamed_dump(node, old, new):
    import copy
    return dump(Renamer(old, new).visit(copy.deepcopy(node)))


def check(base, head, rename=None, allow=()):
    """Return (ok, lines). ok only if the change is a pure move."""
    allow = set(allow)
    old_defs, new_defs, lines, ok = {}, {}, [], True
    for p in changed_py(base, head):
        od, orest = collect(show(base, p), p)
        nd, nrest = collect(show(head, p), p)
        old_defs.update(((p, q), n) for q, n in od.items())
        new_defs.update(((p, q), n) for q, n in nd.items())
        if sorted(orest) != sorted(nrest):
            if p + ":<module>" in allow:
                lines.append("allowed: %s:<module> top-level statements edited" % p)
            else:
                ok = False
                lines.append("FAIL: %s:<module> top-level statements changed (not a move)" % p)
    added = {}  # dump -> newly added defs
    for k, n in new_defs.items():
        if k not in old_defs:
            added.setdefault(dump(n), []).append(k)

    def outer(keys, other):
        return sorted(k for k in keys if k not in other and not any(
            k[0] == r[0] and k[1].startswith(r[1] + ".") for r in keys if r not in other))

    accounted = set()
    for path, q in outer(old_defs, new_defs):
        node = old_defs[(path, q)]
        cands, how = added.get(dump(node), []), "identical"
        if not cands and rename:
            cands, how = added.get(renamed_dump(node, *rename), []), "renamed %s->%s" % rename
        cands = [c for c in cands if c[0] != path and c not in accounted]
        if cands:
            accounted.add(cands[0])
            lines.append("moved: %s:%s -> %s:%s (%s)" % (path, q, cands[0][0], cands[0][1], how))
        else:
            ok = False
            lines.append("FAIL: %s:%s removed with no identical destination" % (path, q))
    for k in outer(new_defs, old_defs):
        if k in accounted:
            continue
        if "%s:%s" % k in allow:
            lines.append("allowed: %s:%s added" % k)
        else:
            ok = False
            lines.append("FAIL: %s:%s added but not a moved definition" % k)
    for k in sorted(set(old_defs) & set(new_defs)):
        if dump(old_defs[k]) != dump(new_defs[k]):
            if "%s:%s" % k in allow:
                lines.append("allowed: %s:%s edited" % k)
            else:
                ok = False
                lines.append("FAIL: %s:%s changed in place (not a move)" % k)
    return ok, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("base")
    ap.add_argument("head")
    ap.add_argument("--rename", metavar="OLD=NEW", help="allow one name rename, e.g. self=eng")
    ap.add_argument("--allow-edit", action="append", default=[], metavar="PATH:QUALNAME",
                    help="name a def edited or added on purpose (repeatable)")
    a = ap.parse_args(argv)
    rename = None
    if a.rename:
        if a.rename.count("=") != 1:
            ap.error("--rename wants OLD=NEW")
        rename = tuple(a.rename.split("="))
    ok, lines = check(a.base, a.head, rename, a.allow_edit)
    print("\n".join(lines) if lines else "no definitions removed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
