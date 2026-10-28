"""What a node's answer says in a few lines: the facts behind the step (verbose mode) and the one line the trace keeps."""
from typing import Any

from taskloop.contracts.answers import VERDICTS


def asked(d: Any) -> list[str]:
    q = [f"question: {d['question']}"] if d["question"].strip() else []
    return q + ([f"decided by: {d['decided']}"] if d["decided"].strip() else [])


def details(node: str, d: Any) -> list[str]:
    if node == "plan":
        stages = [f"{n + 1}. {s['goal']}{' (hard)' if s['hard'] else ''} → checks: {'; '.join(s['checks'])}"
                  for n, s in enumerate(d["stages"])]
        return stages + [f"risk: {r['what']} → {r['check']}" for r in d["risks"]]
    if node == "write":
        return [f"ran `{c['cmd']}` exit {c['exit']}" for c in d["checks_run"]] + asked(d)
    if node == "review":
        return ([f"{f['severity']} {f['file']}:{f['line']} {f['fix']}" for f in d["findings"]] + ["unmet: " + u for u in d["unmet"]]
                + ["leftover: " + lo["title"] for lo in d["leftovers"]] + asked(d))
    if node == "verify":
        return [f"{a['n']} {a['verdict']}: {a['evidence'] or a['why']}" for a in d["items"]]
    if node == "look":
        return [f"{f['verdict']} {f['item']}{(' (' + f['where'] + ')') if f['where'] else ''}: {f['why']}" for f in d["findings"]]
    return []


def summarize(node: str, d: Any) -> str:
    if node == "plan":
        return f"{len(d['stages'])} stages, {len(d['risks'])} risks: {d['summary'][:200]}"
    if node == "write":
        return str(d["summary"][:300])
    if node == "review":
        return f"{len(d['findings'])} findings, {len(d['unmet'])} unmet"
    if node == "verify":
        return ", ".join(f"{sum(a['verdict'] == k for a in d['items'])} {k}" for k in VERDICTS)
    if node == "look":
        defects = sum(f["verdict"] == "defect" for f in d["findings"])
        return f"{defects} defects, {sum(f['verdict'] == 'pass' for f in d['findings'])} pass: {d['summary'][:200]}"
    return ""
