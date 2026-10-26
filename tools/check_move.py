#!/usr/bin/env python3
"""Check that a change only moved code: `check_move.py BASE HEAD [--rename self=eng]`.

Parses every changed .py at both revs. Each function/class removed from a
file must exist with an identical ast.dump (decorators, docstring included)
as a definition newly added in another file of the change. With
`--rename OLD=NEW`, that one name rename is also accepted (old side).
Definitions changed in place are printed as "not a move" and do not fail;
a removed definition with no identical destination does. Stdlib only.
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
    """{qualname: node} for every def/class, nested included."""
    found = {}

    def walk(body, prefix):
        for node in body:
            if isinstance(node, DEFS):
                q = prefix + node.name
                found[q] = node
                walk(node.body, q + ".")
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for field in ("body", "orelse", "finalbody", "handlers"):
                    sub = getattr(node, field, None) or []
                    for s in sub:
                        walk(getattr(s, "body", [s]) if field == "handlers" else [s], prefix)

    try:
        walk(ast.parse(src, path).body, "")
    except SyntaxError as e:
        raise SystemExit("cannot parse %s: %s" % (path, e))
    return found


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
    return ast.dump(node)


def renamed_dump(node, old, new):
    import copy
    return ast.dump(Renamer(old, new).visit(copy.deepcopy(node)))


def check(base, head, rename=None):
    """Return (ok, lines)."""
    old_defs, new_defs = {}, {}
    for p in changed_py(base, head):
        for q, n in collect(show(base, p), p).items():
            old_defs[(p, q)] = n
        for q, n in collect(show(head, p), p).items():
            new_defs[(p, q)] = n
    added = {}  # dump -> list of (path, qualname) newly added defs
    for k, n in new_defs.items():
        if k not in old_defs:
            added.setdefault(dump(n), []).append(k)
    removed = [k for k in old_defs if k not in new_defs]
    # only outermost removed defs: skip members of a removed class
    top = [k for k in removed
           if not any(k[0] == r[0] and k[1].startswith(r[1] + ".") for r in removed)]
    lines, ok = [], True
    for path, q in sorted(top):
        node = old_defs[(path, q)]
        cands = added.get(dump(node), [])
        how = "identical"
        if not cands and rename:
            cands = added.get(renamed_dump(node, *rename), [])
            how = "renamed %s->%s" % rename
        cands = [c for c in cands if c[0] != path]
        if cands:
            lines.append("moved: %s:%s -> %s:%s (%s)" % (path, q, cands[0][0], cands[0][1], how))
        else:
            ok = False
            lines.append("FAIL: %s:%s removed with no identical destination" % (path, q))
    for k in sorted(set(old_defs) & set(new_defs)):
        if dump(old_defs[k]) != dump(new_defs[k]) and not isinstance(old_defs[k], ast.ClassDef):
            lines.append("not a move: %s:%s changed in place" % k)
    return ok, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("base")
    ap.add_argument("head")
    ap.add_argument("--rename", metavar="OLD=NEW", help="allow one name rename, e.g. self=eng")
    a = ap.parse_args(argv)
    rename = None
    if a.rename:
        if a.rename.count("=") != 1:
            ap.error("--rename wants OLD=NEW")
        rename = tuple(a.rename.split("="))
    ok, lines = check(a.base, a.head, rename)
    print("\n".join(lines) if lines else "no definitions removed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
