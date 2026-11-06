"""The tl shim picks the newest installed task-loop on every call (the real sh, a fake uv that prints what it was asked to run)."""
import shutil
import subprocess
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

from taskloop.app.wire import hook
from taskloop.contracts.env import Env


class ShimResolves(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.env = Env({"XDG_CONFIG_HOME": str(self.root / "config"), "CLAUDE_CONFIG_DIR": str(self.root / "claude")})
        uv = self.root / "bin" / "uv"
        uv.parent.mkdir()
        uv.write_text('#!/bin/sh\nshift 3\necho "$@"\n')  # `uv run --quiet --script <tl.py> args`: prints tl.py and args
        uv.chmod(0o755)
        self.old = self.install("0.23.99")
        hook.write_shim(self.old, self.env)
        self.shim = self.root / "config" / "task-loop" / "bin" / "tl"

    def install(self, version):
        f = self.root / "cache" / version / "skills" / "task-loop" / "tl.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")
        (f.parents[2] / "hooks").mkdir(exist_ok=True)
        (f.parents[2] / "hooks" / "hook.py").write_text("")
        return f.parents[2]

    def ran(self, *args):
        done = subprocess.run([str(self.shim), *args], capture_output=True, text=True, check=False,
                              env={"PATH": f"{self.root / 'bin'}:/usr/bin:/bin"})
        return done.stdout.strip()

    def test_the_newest_install_runs_by_number_and_a_release_needs_no_rewrite(self):
        assert self.ran("a", "b") == f"{self.old}/skills/task-loop/tl.py a b"
        for version in ("0.23.100", "0.23.1000", "0.23.999"):
            with self.subTest(version=version):
                self.install(version)
                shown = "0.23.1000" if version == "0.23.999" else version  # 1000 is above 999 by number, not by text
                assert self.ran() == f"{self.root / 'cache' / shown}/skills/task-loop/tl.py"

    def test_a_half_installed_or_malformed_dir_is_skipped_and_a_pruned_one_needs_no_rewrite(self):
        top = self.install("0.23.100")
        (self.root / "cache" / "0.99.0" / "skills" / "task-loop").mkdir(parents=True)  # no tl.py
        self.install("0.99.1x")
        self.install("1.02.3")  # a leading zero is not a version
        assert self.ran() == f"{top}/skills/task-loop/tl.py"
        shutil.rmtree(top)
        assert self.ran() == f"{self.old}/skills/task-loop/tl.py"

    def test_with_no_install_left_it_falls_back_to_the_path_it_was_written_with(self):
        shutil.rmtree(self.old)
        assert self.ran() == f"{self.old}/skills/task-loop/tl.py"
