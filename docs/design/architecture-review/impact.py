import ast, json, statistics
from pathlib import Path
T = Path("/home/iorlas/Workspaces/iorlas-task-loop-b83c5d9a3f13cb9d/sleepy-nobel-d00460/tests")
g = json.load(open("graph.json"))["internal"]
# transitive src closure
memo = {}
def clo(m):
    if m in memo: return memo[m]
    memo[m] = set(); s = {m}
    for t in g.get(m, []): s |= clo(t)
    memo[m] = s; return s
files = {p.stem: p for p in T.rglob("*.py")}
def direct(p):
    src, tl = set(), set()
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n, ast.Import): names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module: names = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
        else: continue
        for x in names:
            if x.startswith("taskloop") and x in g: src.add(x)
            else:
                last = x.split(".")[-1]
                if last in files and files[last] != p: tl.add(last)
    return src, tl
cache = {}
def tclo(stem, seen=()):
    if stem in cache: return cache[stem]
    s, tl = direct(files[stem]); out = set(s)
    for h in tl:
        if h not in seen: out |= tclo(h, seen + (stem,))
    cache[stem] = out; return out
tests = [s for s in files if s.startswith("test_")]
conf = {d: tclo("conftest") for d in [0]}
cf = tclo("conftest") if "conftest" in files else set()
tcl = {}
for t in tests:
    base = tclo(t)
    full = set()
    for m in base | (cf if files[t].parent.name == 'steps' else set()): full |= clo(m)
    tcl[t] = full
print("test files", len(tests), "conftest src imports", len(cf))
rows = []
for m in g:
    n = sum(1 for t in tests if m in tcl[t]); rev = sum(1 for k in g if m in clo(k) and k != m)
    rows.append((n, rev, m.removeprefix("taskloop.")))
rows.sort(reverse=True)
ns = [r[0] for r in rows]
print("median tests hit when one module changes:", statistics.median(ns), "of", len(tests), "; modules hitting >50% of tests:", sum(1 for x in ns if x > len(tests)/2))
print("top:", rows[:12]); print("lowest:", rows[-8:])
json.dump(rows, open("impact.json", "w"))
