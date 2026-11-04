"""Old sessions keep launchers on the newest readable numeric cache install."""
import tempfile
from pathlib import Path
from unittest import mock

from support.case import Case

from taskloop.app.wire import doctor, hook
from taskloop.contracts.env import Env


class ShimPin(Case):
    def setup_method(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = Env({"XDG_CONFIG_HOME": str(self.root / "config"),
                        "CLAUDE_CONFIG_DIR": str(self.root / "claude")})
        self.config = self.root / "config" / "task-loop"
        self.old = self.install("0.23.99")

    def install(self, version):
        root = self.root / "cache" / version
        for name in ("skills/task-loop/tl.py", "hooks/hook.py", "AGENTS.md"):
            f = root / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("## Ownership\n")
        return root

    def write(self, root):
        hook.write_shim(root, self.env)
        assert len(hook.write_hooks(root, self.env)) == len(hook.HOOK_NAMES)

    def files(self):
        return [self.config / "bin/tl", *(self.config / "githooks" / n for n in hook.HOOK_NAMES)]

    def assert_targets(self, root):
        assert str(root / "skills/task-loop/tl.py") in self.files()[0].read_text()
        for f in self.files()[1:]:
            assert str(root / "hooks/hook.py") in f.read_text()
            assert str(self.config / "bin/tl") in f.read_text()

    def test_old_session_never_downgrades_newer_shim_or_hooks(self):
        new = self.install("0.23.100")
        self.write(new)
        before = [(f.read_bytes(), f.stat().st_mtime_ns) for f in self.files()]
        self.write(self.old)
        self.assert_targets(new)
        assert before == [(f.read_bytes(), f.stat().st_mtime_ns) for f in self.files()]

    def test_new_install_upgrades_both_launchers_in_numeric_order(self):
        self.write(self.old)
        self.assert_targets(self.old)
        new = self.install("0.23.100")
        self.install("not-a-version")
        self.write(new)
        self.assert_targets(new)

    def test_old_session_also_upgrades_to_newest_install(self):
        self.write(self.old)
        new = self.install("0.23.100")
        self.write(self.old)
        self.assert_targets(new)

    def test_unreadable_newest_keeps_all_current_files(self):
        self.write(self.old)
        new = self.install("0.23.100")
        before = [f.read_bytes() for f in self.files()]
        read = Path.read_bytes
        for name in ("skills/task-loop/tl.py", "hooks/hook.py"):
            def unreadable(path, target=new / name):
                if path == target:
                    raise PermissionError("unreadable install")
                return read(path)
            with self.subTest(name=name), mock.patch.object(Path, "read_bytes", unreadable):
                hook.write_shim(self.old, self.env)
                assert hook.write_hooks(self.old, self.env) == []
            assert before == [f.read_bytes() for f in self.files()]

    def test_doctor_reports_shim_or_hook_skew_in_one_finding(self):
        self.write(self.old)
        new = self.install("0.23.100")
        for stale in ("both", "shim", "hook"):
            with self.subTest(stale=stale):
                if stale == "shim":
                    hook.write_hooks(new, self.env)
                elif stale == "hook":
                    hook.write_shim(new, self.env)
                    f = self.config / "githooks/pre-push"
                    f.write_text(f.read_text().replace(str(new), str(self.old)))
                with mock.patch.object(doctor.catalog, "installed_version", return_value=""), \
                        mock.patch.object(doctor.catalog, "cache_dirs", return_value={}):
                    findings = doctor.install_problems(self.old, self.env)
                assert len(findings) == 1
                assert "older than newest installed task-loop 0.23.100" in findings[0]
                assert ("shim" if stale == "shim" else "pre-push") in findings[0]
        self.write(new)
        with mock.patch.object(doctor.catalog, "installed_version", return_value=""), \
                mock.patch.object(doctor.catalog, "cache_dirs", return_value={}):
            assert doctor.install_problems(self.old, self.env) == []
