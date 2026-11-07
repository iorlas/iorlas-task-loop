"""RUNSTATE (tl-9un.48): a run's liveness is RECORDED (factory.db, RunState), never inferred by a reader from a gap in a log.
Over src, as an AST scan:
 - no module reads the engine log's Beat records to decide life: `Beat` is named only where the stuck rule's tick and the event filters are
   (ALLOWS_BEAT), so a reader cannot compare a log's newest record with the clock;
 - STALE_AFTER (the age at which a heartbeat is looked at) and `pid_alive` are named only by the one reconciler (contracts/runlife,
   contracts/locator) and the loop files' own pid probe;
 - a run is SET `lost` (a `state=RunState.LOST` argument) only by the reconciler in contracts/locator.py; any module may read it;
 - the old inference vocabulary (CRASHED_AFTER, Liveness.CRASHED) is gone."""
import ast
import sys
from pathlib import Path

from rules.gate_rules import parsed
from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

ALLOWS_BEAT = {
    "packages/kernel/src/tlkernel/log.py",  # the record's definition
    "packages/pipeline/src/tlpipeline/stuck_rule.py",  # the stuck rule: a Beat is the tick, not activity
    "packages/pipeline/src/tlpipeline/lifecycle.py",  # the engine writes it
    "src/taskloop_dash/jsonl.py", "src/taskloop_dash/readers/logs.py", "src/taskloop_dash/views/runfacts.py",  # a Beat is no event
    "src/taskloop_dash/index/facts.py",  # only the indexer compacts engine Beats
}
ALLOWS_STALE = {"packages/kernel/src/tlkernel/runlife.py"}
ALLOWS_PID_ALIVE = {  # the lock table's and the loop's own pid probes, and the reconciler
    "packages/kernel/src/tlkernel/locks.py", "packages/kernel/src/tlkernel/runlife.py",
    "src/taskloop/app/launch/loop.py", "src/taskloop/app/wire/brief.py", "src/taskloop/app/loop/env.py", "src/taskloop/app/loop/files.py"}
ALLOWS_LOST = {"packages/kernel/src/tlkernel/locator.py"}
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
        tree = parsed(f)[1]
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


DASH = SRC / "taskloop_dash"
WRITERS = {"reconcile", "mark_lost", "take_up"}  # names the dashboard must not import or call
WRITER_CALLS = {"create", "end", "beat"}  # on a locator


def dash_writer_uses(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            out += [(n.lineno, a.name) for a in n.names if a.name in WRITERS]
        elif isinstance(n, ast.Attribute) and (n.attr in WRITERS or (n.attr in WRITER_CALLS and "locator" in ast.unparse(n.value).lower())):
            out.append((n.lineno, n.attr))
    return out


class DashWritesNothing(Case):
    def test_nothing_under_the_dashboard_names_a_run_state_writer(self):
        bad = [f"{f.relative_to(ROOT)}:{line}: {name}" for f in sorted(DASH.rglob("*.py"))
               for line, name in dash_writer_uses(parsed(f)[1])]
        assert bad == [], "the dashboard only reads: it displays runlife.shown, only tl processes call reconcile"

    def test_the_scan_sees_planted_writers(self):
        tree = ast.parse("from tlkernel.runlife import reconcile\nself.locator.end(r)\nrunlife.reconcile(c, 1)\nx.shown()\n")
        assert [n for _, n in dash_writer_uses(tree)] == ["reconcile", "end", "reconcile"]


class LivenessIsRecorded(Case):
    def test_no_reader_derives_liveness_from_a_log_gap(self):
        assert scan() == []

    def test_the_scan_sees_planted_inference(self):
        src = ("from tlkernel.log import Beat\nx = now - CRASHED_AFTER\nif life is Liveness.CRASHED: pass\n"
               "m.replace(state=RunState.LOST)\nok = RunState.LOST\n")
        tree = ast.parse(src)
        assert (1, "Beat") in names(tree)
        assert (2, "CRASHED_AFTER") in names(tree)
        assert crashed_uses(tree) == [3]
        assert lost_sets(tree) == [4]

    def test_the_allow_lists_name_files_that_exist(self):
        for rel in ALLOWS_BEAT | ALLOWS_STALE | ALLOWS_PID_ALIVE | ALLOWS_LOST:
            assert (ROOT / rel).is_file(), rel


def test_read_verbs_do_not_reconcile():
    roots = [SRC / "taskloop" / part for part in ("app/asks", "app/report", "cli")]
    bad = [f"{f.relative_to(ROOT)}:{line}" for root in roots for f in sorted(root.rglob("*.py"))
           for line, name in names(parsed(f)[1]) if name == "reconcile"]
    assert bad == [], "read verbs use runlife.shown; only the loop and doctor reconcile"
