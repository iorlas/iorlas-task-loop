#!/usr/bin/env python3
"""Record one real exchange from a run folder into tests/fixtures/exchanges/<role>/<case>/ (format: tests/support/exchanges.py).

    python3 dev/record_exchange.py RUN_DIR ROLE CASE --bead BEAD.json [--n N] [--prompt FILE --wt PATH] [--source TEXT]

RUN_DIR is a run's folder (<config>/task-loop/runs/<bead>-<stamp>/): it holds the node answers the lane returned (plan.json,
plan-N.json, write-N.json, review-N.json) and, for a writer or reviewer, the plan the run went by. ROLE is planner, writer or reviewer;
the answer taken is the last one of its node, or the one numbered --n. BEAD.json is the bead as `bd show ID --json` prints it (the
first element, or the object). The engine does not keep the prompt it sent (a run folder has only the brief): pass --prompt (a copy of
the delegate brief file of that call) with --wt (the worktree path in it, which becomes <WT>) to record the exact input; without it,
input.txt is what the engine builds today for this bead, written by `UPDATE_GOLDEN=1 uv run pytest tests/run/test_exchanges.py`, and
the case says input "synthetic". Edit meta.json's calls to the roles the engine makes with it. Stdlib only."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCHANGES = ROOT / "tests" / "fixtures" / "exchanges"
NODES = {"planner": "plan", "writer": "write", "reviewer": "review"}
CALLS = {"planner": ["planner", "worker"], "writer": ["planner", "worker", "reviewer"], "reviewer": ["planner", "worker", "reviewer"]}


def numbered(run: Path, node: str, n: int | None) -> Path:
    """The node's answer file: `<node>-<n>.json`, the highest n when none is asked for."""
    if n is not None:
        return run / f"{node}-{n}.json"
    found = sorted((int(m.group(1)), p) for p in run.glob(f"{node}-*.json") if (m := re.fullmatch(rf"{node}-(\d+)\.json", p.name)))
    if not found:
        raise SystemExit(f"{run}: no {node}-N.json answer")
    return found[-1][1]


def write(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("role", choices=sorted(NODES))
    ap.add_argument("case")
    ap.add_argument("--bead", type=Path, required=True)
    ap.add_argument("--n", type=int)
    ap.add_argument("--prompt", type=Path)
    ap.add_argument("--wt", default="")
    ap.add_argument("--source", default="")
    a = ap.parse_args(argv)
    node = NODES[a.role]
    answer = json.loads(numbered(a.run_dir, node, a.n).read_text(encoding="utf-8"))
    bead = json.loads(a.bead.read_text(encoding="utf-8"))
    bead = bead[0] if isinstance(bead, list) else bead
    out = EXCHANGES / a.role / a.case
    out.mkdir(parents=True, exist_ok=True)
    write(out / "answer.json", answer)
    write(out / "bead.json", bead)
    if a.role != "planner":
        plan = a.run_dir / "plan.json"
        if not plan.is_file():
            raise SystemExit(f"{plan}: a {a.role} exchange needs the run's plan")
        write(out / "plan.json", json.loads(plan.read_text(encoding="utf-8")))
    if a.prompt:
        text = a.prompt.read_text(encoding="utf-8")
        (out / "input.txt").write_text(text.replace(a.wt, "<WT>") if a.wt else text, encoding="utf-8")
    write(out / "meta.json", {"node": node, "answer": "real", "input": "real" if a.prompt else "synthetic",
                              "source": a.source or f"run folder {a.run_dir.name}", "calls": CALLS[a.role]})
    print(f"recorded {out}" + ("" if a.prompt else ": now run UPDATE_GOLDEN=1 uv run pytest tests/run/test_exchanges.py"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
