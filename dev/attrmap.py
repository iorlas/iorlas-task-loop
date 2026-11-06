"""Who reads and who writes each attribute of the Engine (the run host), by stage: the measurement behind docs/design/stage-isolation.md
(bead ATTR-MAP). An attribute is written by the engine's own classes in app/run (self.X = ...), then read or written from anywhere through
a receiver named e / eng / engine / host / h (or self.host, self.e, self.engine). Standard library only.

    python3 dev/attrmap.py [--root DIR] [--json]      prints the classes below; --json dumps every attribute

Classes: run-fact (written only in the run slice, read by 2+ stages), private (touched by one stage), hand-off (written by one
stage, read by another), shared (written by 2+ stages)."""
import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reach import stage_of

RECEIVERS = {"e", "eng", "engine", "host", "h"}
OWN = {"self.host", "self.e", "self.engine", "self.eng"}


def _recv(node):
    if isinstance(node, ast.Name):
        return node.id in RECEIVERS
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}" in OWN
    return False


def engine_attrs(root):
    """Names the run slice's classes assign on self."""
    names = set()
    for p in (root / "src/taskloop/app/run").glob("*.py"):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name) and n.value.id == "self":
                names.add(n.attr)
    return names


def scan(root):
    attrs = engine_attrs(root)
    reads, writes = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    for p in sorted((root / "src").rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        stage = stage_of(rel)
        in_run = rel.startswith("src/taskloop/app/run/")
        for n in ast.walk(ast.parse(p.read_text())):
            if not isinstance(n, ast.Attribute) or n.attr not in attrs:
                continue
            if _recv(n.value) or (in_run and isinstance(n.value, ast.Name) and n.value.id == "self"):
                (writes if isinstance(n.ctx, ast.Store) else reads)[n.attr][stage] += 1
    return attrs, reads, writes


def classify(r, w):
    ws, rs = set(w), set(r)
    outside = (ws | rs) - {"shell"}
    if len(ws | rs) <= 1:
        return "private"
    if len(ws - {"shell"}) >= 2:
        return "shared"
    if len(ws - {"shell"}) == 1 and len(rs - ws) >= 1:
        return "hand-off"
    if len(outside | {"shell"}) >= 2 and not (ws - {"shell"}):
        return "run-fact"
    return "private"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    attrs, reads, writes = scan(Path(a.root))
    rows = {k: {"class": classify(reads[k], writes[k]), "reads": dict(reads[k]), "writes": dict(writes[k])}
            for k in sorted(attrs)}
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    by = defaultdict(list)
    for k, v in rows.items():
        by[v["class"]].append(k)
    print(f"{len(rows)} engine attributes")
    for c in ("run-fact", "private", "hand-off", "shared"):
        print(f"\n{c}: {len(by[c])}")
        for k in by[c]:
            v = rows[k]
            print(f"  {k:28} w={','.join(f'{s}:{n}' for s, n in v['writes'].items()) or '-':28} r={','.join(f'{s}:{n}' for s, n in v['reads'].items())}")


if __name__ == "__main__":
    main()
