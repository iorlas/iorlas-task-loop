import ast, json, sys
from pathlib import Path
root = Path("/home/iorlas/Workspaces/iorlas-task-loop-b83c5d9a3f13cb9d/sleepy-nobel-d00460/src/taskloop")
mods = {}
for p in sorted(root.rglob("*.py")):
    name = "taskloop." + ".".join(p.relative_to(root).with_suffix("").parts)
    name = name.removesuffix(".__init__")
    mods[name] = p
internal, external, lines = {}, {}, {}
for name, p in mods.items():
    src = p.read_text()
    lines[name] = src.count("\n") + 1
    tree = ast.parse(src)
    i, e = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            targets = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            targets = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
        else:
            continue
        for t in targets:
            if t.startswith("taskloop"):
                if t in mods: i.add(t)
            else:
                e.add(t.split(".")[0])
    i.discard(name)
    internal[name] = sorted(i); external[name] = sorted(e)
fan_in = {m: 0 for m in mods}
for m, ts in internal.items():
    for t in ts: fan_in[t] += 1
# SCC (tarjan)
idx, low, st, on, out, c = {}, {}, [], set(), [], [0]
sys.setrecursionlimit(10000)
def sc(v):
    idx[v] = low[v] = c[0]; c[0] += 1; st.append(v); on.add(v)
    for w in internal[v]:
        if w not in idx: sc(w); low[v] = min(low[v], low[w])
        elif w in on: low[v] = min(low[v], idx[w])
    if low[v] == idx[v]:
        comp = []
        while True:
            w = st.pop(); on.discard(w); comp.append(w)
            if w == v: break
        if len(comp) > 1: out.append(sorted(comp))
for v in mods:
    if v not in idx: sc(v)
json.dump({"internal": internal, "external": external, "fan_in": fan_in, "lines": lines, "cycles": out}, open("graph.json", "w"))
print("modules", len(mods), "edges", sum(len(v) for v in internal.values()), "cycles", [len(x) for x in out])
print("top fan-out:", sorted(((len(v), k.removeprefix('taskloop.')) for k, v in internal.items()), reverse=True)[:12])
print("top fan-in:", sorted(((v, k.removeprefix('taskloop.')) for k, v in fan_in.items()), reverse=True)[:12])
sq = sorted(k.removeprefix('taskloop.') for k, v in external.items() if "sqlite3" in v or "sqlite_store" in v)
print("sqlite importers", len(sq), sq)
