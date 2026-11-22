"""Run an A/B experiment from a frozen spec. See README.md. Not a `tl` command.

uv run --frozen --no-sync python tools/experiment/experiment.py plan SPEC.json
uv run --frozen --no-sync python tools/experiment/experiment.py run SPEC.json
uv run --frozen --no-sync python tools/experiment/experiment.py report SPEC.json
"""

import argparse
import json
import sys
from pathlib import Path

from stream_proc import capture

from exp_order import describe, plan
from exp_report import report
from exp_run import Runner
from exp_spec import RunResult, load_spec


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="experiment.py", description="Build arms, run them with N in flight, collect and report.")
    parser.add_argument(
        "command", choices=("plan", "run", "report"), help="plan: print the randomized order; run: everything; report: re-render"
    )
    parser.add_argument("spec", type=Path, help="the experiment spec (JSON, see README.md)")
    arguments = parser.parse_args(argv)
    spec = load_spec(arguments.spec)
    runs = plan(spec)
    order = describe(runs)
    if arguments.command == "plan":
        print(order, end="")
        return 0
    spec.work.mkdir(parents=True, exist_ok=True)
    if arguments.command == "run":
        (spec.work / "order.txt").write_text(order)
        results = Runner(spec, capture).all(runs)
        (spec.work / "results.json").write_text(json.dumps([r.model_dump(mode="json") for r in results], indent=1))
    else:
        results = [RunResult.model_validate_json(p.read_text()) for p in sorted((spec.work / "results").glob("*.json"))]
    (spec.work / "report.md").write_text(report(spec, results, order))
    print(spec.work / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
