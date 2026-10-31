"""EFFECTS2: a run killed (SIGKILL, by its pid) inside its close is finished by the next process on that bead, which finds the dead run's
id and the outcome in the checkpoint and applies only the effects whose keys are not there: the bead is closed once."""
import json
import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support.waits import until

from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir

CHILD = Path(te.ROOT, "tests", "support", "close_child.py")
WAIT = 120


class CloseKill(te.EngineTest):
    def child(self, *args: str, journal: Path) -> subprocess.Popen:
        env = {**os.environ, "CLOSE_WT": str(self.wt), "PYTHONPATH": os.pathsep.join([str(te.ROOT / "tests"), str(te.ROOT / "src")])}
        return subprocess.Popen([sys.executable, str(CHILD), *args, str(journal)] if args[0] == "restart"
                                else [sys.executable, str(CHILD), args[0], args[1], str(journal), args[2]],
                                env=env, cwd=str(te.ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def rows(self, journal: Path) -> list[dict]:
        return [json.loads(x) for x in journal.read_text().splitlines()] if journal.exists() else []

    def killed_before(self, effect: str) -> tuple[list[dict], list[dict]]:
        """A child closes bead t-1 and is killed right before `effect`; a new child restarts. -> (the first journal, the second)."""
        first, second = Path(self.tmp.name, "first.jsonl"), Path(self.tmp.name, "second.jsonl")
        marker = Path(self.tmp.name, "pid")
        dying = self.child("die", effect, str(marker), journal=first)
        try:
            until(marker.exists, WAIT)
            pid = int(marker.read_text())
            self.assertEqual(pid, dying.pid)
            os.kill(pid, signal.SIGKILL)  # the pid of the child this test started
        finally:
            dying.wait(WAIT)
        self.assertEqual(dying.returncode, -signal.SIGKILL, dying.stderr.read().decode() if dying.stderr else "")
        again = self.child("restart", journal=second)
        _, err = again.communicate(timeout=WAIT)
        self.assertEqual(again.returncode, 0, err.decode())
        return self.rows(first), self.rows(second)

    @staticmethod
    def effects(rows: list[dict]) -> list[str]:
        return [r["effect"] for r in rows if "effect" in r]

    @staticmethod
    def closes(rows: list[dict]) -> int:
        return sum(1 for r in rows if r.get("bd", [""])[:1] == ["close"])

    @te.real_git("a child process is killed and a new one restarts on the same checkout and config dir")
    def test_a_process_killed_before_the_bd_close_is_finished_by_the_next_one_which_closes_once(self):
        first, second = self.killed_before("CloseBead")
        self.assertEqual(self.effects(first), ["SaveBranch", "RecordRun", "FileNotes", "Reflect"])
        self.assertEqual(self.effects(second), ["CloseBead", "ReleaseSlot", "DropCheckpoint"], "only the effects left")
        self.assertEqual(self.closes(first) + self.closes(second), 1)
        self.assertTrue(next(r for r in second if "dead" in r)["dead"])
        creates = [r for r in first + second if r.get("bd", [""])[:1] == ["create"]]
        self.assertEqual(len(creates), 1, "the follow-up was filed once")

    @te.real_git("a child process is killed and a new one restarts on the same checkout and config dir")
    def test_a_process_killed_after_the_bd_close_does_not_close_again(self):
        first, second = self.killed_before("ReleaseSlot")
        self.assertEqual(self.closes(first), 1)
        self.assertEqual(self.effects(second), ["ReleaseSlot", "DropCheckpoint"])
        self.assertEqual(self.closes(second), 0)

    @te.real_git("a child process is killed and a new one restarts on the same checkout and config dir")
    def test_the_restart_reuses_the_dead_runs_id(self):
        _, second = self.killed_before("Reflect")
        run = next(r for r in second if "run" in r)["run"]
        runs = RunLocator(ConfigDir(Path(os.environ["XDG_CONFIG_HOME"], "task-loop"))).of_bead("t-1")
        self.assertEqual([b.run for b in runs], [run])  # one run, taken up by the second process: two attempts
        self.assertEqual(runs[0].manifest.attempts, 2)


if __name__ == "__main__":
    unittest.main()
