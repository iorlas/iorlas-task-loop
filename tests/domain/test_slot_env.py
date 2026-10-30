"""tl-7y6.18: every command a bead runs in a slot gets that slot's environment (temp, dotnet, NuGet, compiler-server id, TL_SLOT)."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as te
from support import fake_route, procsim
from support.builders import make_engine
from support.engine_case import CLEAN, PLAN, WRITE, real_git

from taskloop.app.checks.container import Box
from taskloop.contracts import config
from taskloop.domain import slot_env

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


class Pure(unittest.TestCase):
    def test_slots_differ_and_the_same_slot_is_stable(self):
        a, a2, b = (slot_env.slot_env(Path("/s") / n, "repo", n) for n in ("A", "A", "B"))
        self.assertEqual(a, a2)
        for k in KEYS:
            self.assertIn(k, a)
        self.assertEqual(a["TL_SLOT"], "A")
        self.assertEqual(a["SharedCompilationId"], "repo-A")
        self.assertTrue(all(a[k] != b[k] for k in KEYS), [k for k in KEYS if a[k] == b[k]])

    def test_slot_env_adds_and_overrides_with_placeholders_filled(self):
        env = slot_env.slot_env(Path("/s/A"), "repo", "A", {"TMPDIR": "{slot_dir}/t2", "X_HOME": "{slot_dir}/x-{repo}-{slot}"})
        self.assertEqual((env["TMPDIR"], env["X_HOME"], env["TMP"]), ("/s/A/t2", "/s/A/x-repo-A", "/s/A/tmp"))

    def test_an_unknown_placeholder_is_refused_at_load(self):
        for bad in ("{nope}", "{", "{0}"):
            with self.assertRaises(config.ConfigError, msg=bad):
                config.load({"engine": {"slot_env": {"K": bad}}})
        ok = config.load({"engine": {"slot_env": {"K": "{slot}-{slot_dir}-{repo}"}}})
        self.assertEqual(ok.engine.slot_env["K"], "{slot}-{slot_dir}-{repo}")


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

    def test_two_slots_differ_and_one_slot_is_stable_across_beads(self):
        mk = lambda wt, bead: make_engine(wt, bead=bead, store=self.store).bead_env  # noqa: E731
        other = self.wt.parent / "wt2"
        other.mkdir()
        a1, a2, b = mk(self.wt, "t-1"), mk(self.wt, "t-2"), mk(other, "t-3")
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1["TMPDIR"], b["TMPDIR"])
        self.assertNotEqual(a1["SharedCompilationId"], b["SharedCompilationId"])

    def test_a_container_check_is_given_the_slot_name_only(self):
        e = make_engine(self.wt, store=self.store)
        host = mock.Mock(bead_env=e.bead_env, run_dir=Path("r"), cfg=mock.Mock(container=None))
        box = Box(host)
        box._why, box._image = "", "img"
        check = mock.Mock(container=True, id="c")
        argv, _ = box.plan(check, ["just", "x"], {})
        passed = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
        self.assertIn(f"TL_SLOT={self.wt.name}", passed)
        self.assertEqual([p for p in passed if "tmp" in p.lower() or "/" in p], [])


if __name__ == "__main__":
    unittest.main()
