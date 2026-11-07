"""tl-7y6.18: every command a bead runs in a slot gets that slot's environment (temp, dotnet, NuGet, compiler-server id, TL_SLOT)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import engine_case as te
from support.builders import make_engine

from taskloop.domain import slot_env
from tlkernel import config

KEYS = ("TMPDIR", "TMP", "TEMP", "TL_SLOT")


def push(cwd):
    done = subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=cwd, capture_output=True, text=True, check=False)
    return done.returncode, done.stdout + done.stderr


class Pure(Case):
    def test_slots_differ_and_the_same_slot_is_stable(self):
        a, a2, b = (slot_env.slot_env(Path("/s") / n, "repo", n) for n in ("A", "A", "B"))
        assert a == a2
        for k in KEYS:
            assert k in a
        assert a["TL_SLOT"] == "A"
        assert all(a[k] != b[k] for k in KEYS), [k for k in KEYS if a[k] == b[k]]

    def test_slot_env_adds_and_overrides_with_placeholders_filled(self):
        env = slot_env.slot_env(Path("/s/A"), "repo", "A", {"TMPDIR": "{slot_dir}/t2", "X_HOME": "{slot_dir}/x-{repo}-{slot}"})
        assert (env["TMPDIR"], env["X_HOME"], env["TMP"]) == ("/s/A/t2", "/s/A/x-repo-A", "/s/A/tmp")

    def test_an_unknown_placeholder_is_refused_at_load(self):
        for bad in ("{nope}", "{", "{0}"):
            with pytest.raises(config.ConfigError):
                config.load({"engine": {"slot_env": {"K": bad}}})
        ok = config.load({"engine": {"slot_env": {"K": "{slot}-{slot_dir}-{repo}"}}})
        assert ok.engine.slot_env["K"] == "{slot}-{slot_dir}-{repo}"


class EverySpawnPath(te.EngineTest):
    def dumps(self, name):
        return json.loads((Path(self.tmp.name) / name).read_text())


    def test_two_slots_differ_and_one_slot_is_stable_across_beads(self):
        mk = lambda wt, bead: make_engine(wt, bead=bead, store=self.store).bead_env  # noqa: E731
        other = self.wt.parent / "wt2"
        other.mkdir()
        a1, a2, b = mk(self.wt, "t-1"), mk(self.wt, "t-2"), mk(other, "t-3")
        assert a1 == a2
        assert a1["TMPDIR"] != b["TMPDIR"]
