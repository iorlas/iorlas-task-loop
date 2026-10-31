"""RUNENV: every check, fix and gate command is told its run through the one child-env builder: TL_RUN_ID, TL_RUN_DIR, TL_ATTEMPT,
TL_ARTIFACT_DIR (<run dir>/artifacts/<step>/attempt-N), TL_WORKTREE, TL_BRANCH. None of them is part of a result's identity."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import EngineTest

# isort: split
from support import procsim

from taskloop.adapters import childenv
from taskloop.contracts.envvars import EnvVar

NAMES = (EnvVar.TL_RUN_ID, EnvVar.TL_RUN_DIR, EnvVar.TL_ATTEMPT, EnvVar.TL_ARTIFACT_DIR, EnvVar.TL_WORKTREE, EnvVar.TL_BRANCH)


def show(cwd, env):
    Path(env["TL_ARTIFACT_DIR"], "tool.log").write_text("from the tool")  # a tool writes straight into its folder
    return 0, "|".join(f"{n}={env.get(n, '')}" for n in (v.value for v in NAMES))


SHOW = procsim.default("show-run-env", show)


class RunEnv(EngineTest):
    def seen(self):
        eng = self.checks_engine(checks=[{"id": "c", "cmd": SHOW}])
        res = eng.run_checks({"checks": [], "files": []}, "s")[0]
        out = (eng.run_dir / res.log).read_text()
        return eng, dict(kv.split("=", 1) for kv in out.strip().splitlines()[-1].split("|"))

    def test_a_check_process_sees_the_six_names_with_their_values(self):
        eng, got = self.seen()
        art = eng.run_dir / "artifacts" / "c" / "attempt-1"
        self.assertEqual(got, {
            "TL_RUN_ID": eng.run_id, "TL_RUN_DIR": str(eng.run_dir), "TL_ATTEMPT": "1", "TL_ARTIFACT_DIR": str(art),
            "TL_WORKTREE": str(eng.wt), "TL_BRANCH": eng.git.branch(str(eng.wt))})

    def test_what_the_tool_wrote_there_is_kept_beside_the_log_as_evidence(self):
        _eng, got = self.seen()
        art = Path(got["TL_ARTIFACT_DIR"])
        self.assertEqual((art / "tool.log").read_text(), "from the tool")
        self.assertTrue((art / "check.log").is_file())
        self.assertFalse((art / "tool.log").stat().st_mode & 0o222)  # read-only once the attempt ended

    def test_none_of_them_is_part_of_a_results_identity(self):
        base = {n.value: "x" for n in NAMES}
        self.assertEqual(childenv.reaching(base), {})

    def test_the_builder_gives_exactly_the_six(self):
        out = childenv.run_env(run_id="r", run_dir="/d", attempt=3, artifact_dir="/d/artifacts/s/attempt-3", worktree="/w", branch="b")
        self.assertEqual(out, {"TL_RUN_ID": "r", "TL_RUN_DIR": "/d", "TL_ATTEMPT": "3", "TL_ARTIFACT_DIR": "/d/artifacts/s/attempt-3",
                               "TL_WORKTREE": "/w", "TL_BRANCH": "b"})
