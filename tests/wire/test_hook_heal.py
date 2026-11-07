"""The engine verbs recreate the git hooks dir at start; no other verb touches it."""
from pathlib import Path

from support.case import Case
from support.tlmain import tl
from support.tmpdir import TemporaryDirectory

from taskloop.app.wire import hook
from tlkernel.env import Env
from tlkernel.paths import ConfigDir

ROOT = Path(__file__).resolve().parents[2]


class HookHeal(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env({"HOME": tmp.name, "XDG_CONFIG_HOME": str(Path(tmp.name) / ".config")})
        self.dir = ConfigDir(Path(tmp.name) / ".config" / "task-loop").hooks_dir()

    def test_each_engine_verb_makes_a_missing_hooks_dir(self):
        for verb in sorted(hook.ENGINE_VERBS):
            with self.subTest(verb=verb):
                hook.heal(verb, ROOT, self.env)
                assert len(list(self.dir.iterdir())) == len(hook.HOOK_NAMES)
                for f in self.dir.iterdir():
                    f.unlink()

    def test_another_verb_leaves_the_dir_alone(self):
        hook.heal("status", ROOT, self.env)
        assert not self.dir.exists()

    def test_the_hooks_verb_is_gone_and_the_engine_verbs_are_real_verbs(self):
        assert "hooks" not in tl.VERBS
        assert set(tl.VERBS) >= hook.ENGINE_VERBS
