"""tl-7y6.18: every command a bead runs in a slot gets that slot's environment (temp, dotnet, NuGet, compiler-server id, TL_SLOT)."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import engine_case as te
from support import fake_route, procsim
from support.engine_case import CLEAN, PLAN, WRITE, real_git

KEYS = ("TMPDIR", "TMP", "TEMP", "DOTNET_CLI_HOME", "NUGET_SCRATCH", "NUGET_HTTP_CACHE_PATH", "NUGET_PLUGINS_CACHE_PATH",
        "SharedCompilationId", "MSBUILDNODEHANDSHAKESALT", "TL_SLOT")


def dumper(name, out, then=None):
    """A procsim fake command `name` that writes the environment it was given to `out`, then runs `then(cwd)`."""
    def run(cwd, env):
        out.write_text(json.dumps(dict(env)))
        return then(cwd) if then else (0, "")
    return procsim.fake(name, run)


def push(cwd):
    done = subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=cwd, capture_output=True, text=True, check=False)
    return done.returncode, done.stdout + done.stderr


class EverySpawnPath(te.EngineTest):
    def dumps(self, name):
        return json.loads((Path(self.tmp.name) / name).read_text())

    @real_git("the land command is a real push")
    def test_checks_gate_land_and_the_worker_get_the_slot_values(self):
        out = lambda n: Path(self.tmp.name) / n  # noqa: E731
        plan = copy.deepcopy(PLAN)
        plan["stages"][0]["checks"] = [dumper("dump-check", out("check"))]
        seen = []
        real = fake_route.Script.__call__
        def spy(script, cmd, **kw):
            seen.append(kw["env"])
            return real(script, cmd, **kw)
        with mock.patch.object(fake_route.Script, "__call__", spy):
            gate, land = dumper("dump-gate", out("gate")), dumper("dump-land", out("land"), push)
            rc, _ = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]}, gate=gate, land=land,
                                    slot_env={"MY": "{repo}/{slot}"})
        self.assertEqual(rc, 0, self.blocked)
        slot = self.wt.name
        for name in ("check", "gate", "land"):
            env = self.dumps(name)
            self.assertEqual(env["TL_SLOT"], slot, name)
            self.assertEqual(env["MY"], f"{self.eng.bead_env['SharedCompilationId'].removesuffix('-' + slot)}/{slot}")
            for k in KEYS:
                self.assertEqual(env[k], self.eng.bead_env[k], (name, k))
        self.assertTrue(seen)
        for env in seen:  # the workers, through route.py
            for k in KEYS:
                self.assertEqual(env[k], self.eng.bead_env[k], k)
        self.assertTrue(Path(self.eng.bead_env["TMPDIR"]).is_dir())
        self.assertNotIn(str(self.wt), self.eng.bead_env["TMPDIR"])  # outside the worktree


if __name__ == "__main__":
    unittest.main()
