"""~/.local/bin/tl links to the shim; a different `tl` there is never replaced, and the doctor says which it is."""
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case

from taskloop.app.wire import doctor, hook
from taskloop.contracts.env import Env


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
class PathLink(Case):
    def setup_method(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.env = Env({"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "cfg"),
                        "PATH": f"/usr/bin{os.pathsep}{self.home}/.local/bin"})
        self.shim = self.home / "cfg" / "task-loop" / "bin" / "tl"
        self.link = self.home / ".local" / "bin" / "tl"

    def test_it_links_when_local_exists_and_is_idempotent(self):
        (self.home / ".local").mkdir()
        hook.ensure_path_link(self.env)
        assert self.link.is_symlink()
        assert os.readlink(self.link) == str(self.shim)
        assert hook.link_state(self.env) == "ours"
        hook.ensure_path_link(self.env)
        assert os.readlink(self.link) == str(self.shim)

    def test_it_makes_no_local_folder_on_a_machine_without_one(self):
        hook.ensure_path_link(self.env)
        assert not (self.home / ".local").exists()
        assert hook.link_state(self.env) == "missing"

    def test_a_link_made_by_hand_to_the_shim_is_ours_and_a_different_tl_is_never_replaced(self):
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(self.shim)  # dangling until the shim is written: still ours
        assert hook.link_state(self.env) == "ours"
        self.link.unlink()
        self.link.write_text("#!/bin/sh\necho other tl\n")
        hook.ensure_path_link(self.env)
        assert not self.link.is_symlink()
        assert hook.link_state(self.env) == "foreign"
        elsewhere = self.home / "elsewhere"
        elsewhere.write_text("")
        self.link.unlink()
        self.link.symlink_to(elsewhere)
        hook.ensure_path_link(self.env)
        assert os.readlink(self.link) == str(elsewhere)

    def test_it_never_raises(self):
        (self.home / ".local").mkdir()
        with mock.patch.object(Path, "symlink_to", side_effect=PermissionError("read-only home")):
            hook.ensure_path_link(self.env)

    def test_the_doctor_line_shows_the_state_and_whether_the_folder_is_on_path(self):
        (self.home / ".local").mkdir()
        line, foreign = doctor.path_link_line(self.env)
        assert not foreign
        assert "is missing" in line
        assert "is on PATH" in line
        hook.ensure_path_link(self.env)
        assert doctor.path_link_line(self.env)[0].startswith(f"PATH tl: {self.link} -> the shim")
        assert "NOT on PATH" in doctor.path_link_line(Env({**self.env.vars, "PATH": "/usr/bin"}))[0]
        self.link.unlink()
        self.link.write_text("x")
        line, foreign = doctor.path_link_line(self.env)
        assert foreign
        assert line.startswith(f"PATH tl is not ours: {self.link}")
