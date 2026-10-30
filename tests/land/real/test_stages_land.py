"""Stage tests, part 3: the stale tree, slot hygiene, dead lanes, contracts and follow-ups. Split from test_stages."""
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from run.test_stages import StagesTest
from support import engine_case as te
from support.engine_case import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, engine, lint, real_git, real_proc  # noqa: F401
from support.pushsim import pusher

from taskloop.app.wire import slots as wslots


class SlotHygiene(StagesTest):
    """tl-g6a: base-ignored files do not make a slot dirty; a parked bead leaves the slot at the base."""

    def put_ignore_on_main(self, text, name=".gitignore", sub=""):
        base = Path(self.tmp.name, "base-ignore")
        if not base.exists():
            te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        te.sh("git", "pull", "-q", "origin", "main", cwd=base)
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "gitignore", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)


    @real_git("reads the user's own global git excludes file, which only a real git does")
    def test_the_users_own_global_excludes_still_apply(self):
        self.put_ignore_on_main("client/log.txt\n")
        glob = Path(self.tmp.name, "global-ignore")
        glob.write_text("*.swp\n")
        te.sh("git", "config", "core.excludesFile", str(glob), cwd=self.wt)
        (self.wt / "notes.swp").write_text("editor\n")
        (self.wt / "client").mkdir()
        (self.wt / "client" / "log.txt").write_text("unity\n")
        e = engine.Engine("t-1", str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        self.assertEqual(e.checkout.dirty_status(), "")


class Contracts(StagesTest):
    """tl-bxk.13.16: infrastructure is retried with a rest, never asked; the version is recorded."""

    def land_with(self, fails):
        return pusher("flaky-push", Path(self.tmp.name, "flaky-count"), cut_first=fails)

    @real_git("the land script is a child process that runs git push itself")
    def test_a_network_failure_on_the_push_is_retried_with_a_rest_and_lands(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=self.land_with(2))
        self.assertEqual(rc, 0, self.blocked)
        text = self.eng.log_path.read_text()
        self.assertEqual(text.count("the push failed with a network error"), 2)
        self.assertIsNone(self.eng.__dict__.get("asked") or None)
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))


class FollowUps(StagesTest):
    """tl-7y6.7.9: a follow-up is filed only when bd's create worked; lint sections are added once; a refused one is never 'filed'."""
    LO: ClassVar[Any] = {"title": "Rename x", "why": "found in passing"}
    LINT = "missing required sections for task: ## Acceptance Criteria, ## Touches"

    def lint_bd(self, always=False):
        def fake(*a, **kw):
            r = self.fake_bd(*a, **kw)
            if a[:1] == ("create",):
                body = a[a.index("--description") + 1] if "--description" in a else ""
                if always or not ("## Touches" in body and "## Acceptance Criteria" in body):
                    return mock.Mock(returncode=1, stdout="", stderr=self.LINT)
            return r
        return fake

    def reflect_comments(self):
        return [c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Reflect (engine)")]


if __name__ == "__main__":
    unittest.main()
