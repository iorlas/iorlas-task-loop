"""The flake ledger: which tests the red suite logs name, how often. Standard library only.

    python3 dev/flakes.py [runs-dir [out.jsonl]]      # default: <config>/runs -> <config>/flakes.jsonl

A row per test: `test`, `fails` (red suite logs naming it), `runs` (their run ids). The list a person quarantines from is read off the top
of it; a quarantined test (tests/quarantine.txt) runs apart in dev/runtests.py and cannot block. The list may only shrink (tests/rules/test_quarantine_ratchet.py).
"""
import json
import os
import re
import sys
from pathlib import Path

RED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)
QUARANTINE = Path(__file__).resolve().parent.parent / "tests" / "quarantine.txt"


def failed_tests(text):
    """The test ids a pytest short summary (-rfE) names as failed or errored, once each, in order."""
    return list(dict.fromkeys(RED_LINE.findall(text)))


def build(runs_dir):
    """Rows (most red first) from every `*suite*.log` under <runs_dir>/<run id>/checks/."""
    seen = {}
    for log in sorted(Path(runs_dir).glob("*/checks/*suite*.log")):
        run_id = log.parent.parent.name
        for test in failed_tests(log.read_text(encoding="utf-8", errors="replace")):
            runs = seen.setdefault(test, [])
            if run_id not in runs:
                runs.append(run_id)
    rows = [{"test": test, "fails": len(runs), "runs": runs} for test, runs in seen.items()]
    return sorted(rows, key=lambda r: (-r["fails"], r["test"]))


def write(path, rows):
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def quarantined(path=QUARANTINE):
    """The test ids on the quarantine list (a missing file is an empty list)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [s for s in (line.strip() for line in lines) if s and not s.startswith("#")]


def main(argv):
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "task-loop"
    runs = Path(argv[0]) if argv else config / "runs"
    out = Path(argv[1]) if len(argv) > 1 else config / "flakes.jsonl"
    rows = build(runs)
    write(out, rows)
    print(f"flakes: {len(rows)} tests red in {len({r for row in rows for r in row['runs']})} suite logs -> {out}")
    for row in rows[:10]:
        print(f"  {row['fails']:3d}  {row['test']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
