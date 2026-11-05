"""Rank what dev/testtimes.py recorded: top tests, top fixtures, totals per directory (CPU seconds; wall is 3x CPU on a loaded host).

`python3 dev/testtimes_report.py times.json [--tests 50] [--fixtures 20]`"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def total(row: dict[str, float]) -> float:
    return sum(row.get(f"{phase}_cpu", 0.0) for phase in ("setup", "call", "teardown"))


def report(data: dict, tests: int, fixtures: int) -> str:
    rows = sorted(data["tests"].items(), key=lambda kv: -total(kv[1]))
    out = [f"## Top {tests} tests (CPU s: setup+call+teardown | call | setup+teardown)"]
    for node, row in rows[:tests]:
        out.append(f"{total(row):8.2f} | {row.get('call_cpu', 0):8.2f} | {total(row) - row.get('call_cpu', 0):8.2f}  {node}")
    out.append(f"\n## Top {fixtures} fixtures (own setup CPU s, summed over uses | uses)")
    fx = sorted(data["fixtures"].items(), key=lambda kv: -kv[1].get("setup_cpu", 0))
    out += [f"{row.get('setup_cpu', 0):8.2f} | {int(row['n']):5d}  {key}" for key, row in fx[:fixtures]]
    per: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    for node, row in rows:
        parts = Path(node.split("::")[0]).parts
        key = "/".join(parts[:2]) if len(parts) > 2 else parts[0]
        per[key][0] += 1
        per[key][1] += total(row)
        per[key][2] += row.get("call_wall", 0) + row.get("setup_wall", 0) + row.get("teardown_wall", 0)
    grand = sum(v[1] for v in per.values()) or 1.0
    out.append(f"\n## Per directory (tests | CPU s | share | wall s); all tests {grand:.0f} CPU s")
    out += [f"{v[0]:6d} | {v[1]:9.1f} | {100 * v[1] / grand:5.1f}% | {v[2]:9.1f}  {k}" for k, v in sorted(per.items(), key=lambda kv: -kv[1][1])]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--tests", type=int, default=50)
    parser.add_argument("--fixtures", type=int, default=20)
    args = parser.parse_args()
    print(report(json.loads(Path(args.file).read_text(encoding="utf-8")), args.tests, args.fixtures))


if __name__ == "__main__":
    main()
