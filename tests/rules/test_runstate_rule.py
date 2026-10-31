"""RUNSTATE (tl-9un.48): a run's liveness is RECORDED (runs/<run>/manifest.json, RunState), never inferred by a reader from a gap in a log.
Over src, as an AST scan:
 - no module reads the engine log's Beat records to decide life: `Beat` is named only where the stuck rule's tick and the event filters are
   (ALLOWS_BEAT), so a reader cannot compare a log's newest record with the clock;
 - STALE_AFTER (the age at which a heartbeat is looked at) and `pid_alive` are named only by the one reconciler (contracts/runlife,
   contracts/locator) and the loop files' own pid probe;
 - a run is SET `lost` (a `state=RunState.LOST` argument) only by the reconciler in contracts/locator.py; any module may read it;
 - the old inference vocabulary (CRASHED_AFTER, Liveness.CRASHED) is gone."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

ALLOWS_BEAT = {
    "src/taskloop/contracts/log.py",  # the record's definition
    "src/taskloop/domain/stuck.py",  # the stuck rule: a Beat is the tick, not activity
    "src/taskloop/app/run/run_once.py",  # the engine writes it
    "src/taskloop_dash/jsonl.py", "src/taskloop_dash/api/live.py", "src/taskloop_dash/views/runfacts.py",  # a Beat is no event
}
ALLOWS_STALE = {"src/taskloop/contracts/runlife.py"}
ALLOWS_PID_ALIVE = {  # the lock table's and the loop's own pid probes, and the reconciler
    "src/taskloop/contracts/locks.py", "src/taskloop/contracts/runlife.py", "src/taskloop/stores/memory.py",
    "src/taskloop/app/launch/loop.py", "src/taskloop/app/wire/brief.py", "src/taskloop/app/loop/env.py", "src/taskloop/app/loop/files.py"}
ALLOWS_LOST = {"src/taskloop/contracts/locator.py"}
GONE = {"CRASHED_AFTER"}


def names(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, name) of every Name and Attribute attribute mentioned, and of every imported name."""
    out: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.append((n.lineno, n.id))
        elif isinstance(n, ast.Attribute):
            out.append((n.lineno, n.attr))
        elif isinstance(n, ast.ImportFrom):
            out += [(n.lineno, a.name) for a in n.names]
    return out


def lost_sets(tree: ast.AST) -> list[int]:
    """Lines of `state=RunState.LOST` arguments (a manifest made or replaced as lost)."""
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "state" and isinstance(n.value, ast.Attribute)
            and n.value.attr == "LOST"]


def crashed_uses(tree: ast.AST) -> list[int]:
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "CRASHED" and ast.unparse(n.value) == "Liveness"]


def scan() -> list[str]:
    bad: list[str] = []
    for f in sorted(SRC.rglob("*.py")):
        rel = str(f.relative_to(ROOT))
        if "_vendor" in rel:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for line, name in names(tree):
            if name == "Beat" and rel not in ALLOWS_BEAT:
                bad.append(f"{rel}:{line}: names Beat: liveness is the manifest's recorded state, not a gap in the log")
            if name == "STALE_AFTER" and rel not in ALLOWS_STALE:
                bad.append(f"{rel}:{line}: names STALE_AFTER: only the reconciler looks at a heartbeat's age")
            if name == "pid_alive" and rel not in ALLOWS_PID_ALIVE:
                bad.append(f"{rel}:{line}: probes a pid: only the reconciler decides a run's process is gone")
            if name in GONE:
                bad.append(f"{rel}:{line}: {name} is the retired log-gap inference")
        if rel not in ALLOWS_LOST:
            bad += [f"{rel}:{n}: sets a run lost: only the reconciler (contracts/locator.py) does" for n in lost_sets(tree)]
        bad += [f"{rel}:{n}: Liveness.CRASHED is retired: a run is LOST when its recorded state says so" for n in crashed_uses(tree)]
    return bad


class LivenessIsRecorded(unittest.TestCase):
    def test_no_reader_derives_liveness_from_a_log_gap(self):
        self.assertEqual(scan(), [])

    def test_the_scan_sees_planted_inference(self):
        src = ("from taskloop.contracts.log import Beat\nx = now - CRASHED_AFTER\nif life is Liveness.CRASHED: pass\n"
               "m.replace(state=RunState.LOST)\nok = RunState.LOST\n")
        tree = ast.parse(src)
        self.assertIn((1, "Beat"), names(tree))
        self.assertIn((2, "CRASHED_AFTER"), names(tree))
        self.assertEqual(crashed_uses(tree), [3])
        self.assertEqual(lost_sets(tree), [4])

    def test_the_allow_lists_name_files_that_exist(self):
        for rel in ALLOWS_BEAT | ALLOWS_STALE | ALLOWS_PID_ALIVE | ALLOWS_LOST:
            self.assertTrue((ROOT / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
