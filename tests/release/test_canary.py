"""Origin-backed canary acknowledgements and emergency rollback."""
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.shells import quiet_shell
from support.tmpdir import TemporaryDirectory

from taskloop.app.release import canary, pins
from taskloop.app.release.shell import Abort
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import Ref
from taskloop.contracts.slots import SlotGitError
from taskloop.contracts.snapshots import Pin


class Canary(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = Path(tmp.name) / "task-loop"
        self.git = mock.Mock()
        self.git.ls_remote.return_value = []

    def acknowledge(self):
        self.git.ls_remote.return_value = [Ref(name="refs/tags/v1.2.3", oid="release"),
                                         Ref(name="refs/tags/devbox-ok/v1.2.3", oid="release")]

    def test_acknowledgement_publishes_the_origin_release_oid_and_is_idempotent(self):
        sh = replace(quiet_shell(), port=self.git)
        self.git.ls_remote.return_value = [Ref(name="refs/tags/v1.2.3", oid="release")]
        with mock.patch.object(canary.clone, "ready", return_value=self.config):
            canary.devbox_ok(self.config, "origin", "1.2.3", sh)
            self.git.push.assert_called_once_with(str(self.config), "origin", "release:refs/tags/devbox-ok/v1.2.3")
            self.acknowledge()
            canary.devbox_ok(self.config, "origin", "1.2.3", sh)
        assert self.git.push.call_count == 1
        self.git.log.assert_not_called()

    def test_acknowledgement_refuses_a_missing_release_or_mismatched_tag(self):
        sh = replace(quiet_shell(), port=self.git)
        with mock.patch.object(canary.clone, "ready", return_value=self.config):
            with pytest.raises(Abort, match="no release tag"):
                canary.devbox_ok(self.config, "origin", "1.2.3", sh)
            self.acknowledge()
            self.git.ls_remote.return_value[1] = Ref(name="refs/tags/devbox-ok/v1.2.3", oid="wrong")
            with pytest.raises(Abort, match="does not match"):
                canary.devbox_ok(self.config, "origin", "1.2.3", sh)
        self.git.push.assert_not_called()

    def test_unreadable_origin_refuses_a_forward_pin(self):
        self.git.ls_remote.side_effect = SlotGitError("offline")
        assert "cannot read origin" in canary.mac_pin_refusal(self.config, "origin", "1.2.3", self.git)

    def test_mac_pin_is_refused_until_canary_acknowledgement(self):
        env = Env({"XDG_CONFIG_HOME": str(self.config.parent), "CLAUDE_CONFIG_DIR": str(self.config.parent / "claude")})
        with mock.patch.object(pins.sys, "platform", "darwin"), \
                mock.patch.object(pins, "installed_version", return_value="1.2.2"), \
                mock.patch.object(pins, "cache_dirs", return_value={"1.2.3": Path("/installed")}):
            _, why = pins.set_pin(env, "1.2.3", git=self.git)
            assert "devbox-ok" in why
            assert pins.pin_store(env).get() is None
            self.acknowledge()
            pin, why = pins.set_pin(env, "1.2.3", git=self.git)
            assert why == ""
            assert pin.task_loop == "1.2.3"

    def test_unknown_and_invalid_versions_cannot_authorize_a_pin(self):
        assert canary.mac_pin_refusal(self.config, "origin", "1.2.3", self.git)
        assert canary.mac_pin_refusal(self.config, "origin", "../../elsewhere", self.git)
        self.acknowledge()
        self.git.ls_remote.return_value[1] = Ref(name="refs/tags/devbox-ok/v1.2.3", oid="wrong")
        assert canary.mac_pin_refusal(self.config, "origin", "1.2.3", self.git)

    def test_installing_a_version_does_not_authorize_the_first_standing_pin(self):
        env = Env({"XDG_CONFIG_HOME": str(self.config.parent), "CLAUDE_CONFIG_DIR": str(self.config.parent / "claude")})
        with mock.patch.object(pins.sys, "platform", "darwin"), \
                mock.patch.object(pins, "installed_version", return_value="1.2.3"), \
                mock.patch.object(pins, "cache_dirs", return_value={"1.2.3": Path("/installed")}):
            _, why = pins.set_pin(env, "1.2.3", git=self.git)
            assert "devbox-ok" in why
            self.acknowledge()
            assert pins.run_pin(env, "1.2.3", None, False, self.git) == 0

    def test_mac_rollback_and_night_repin_need_no_network_or_new_acknowledgement(self):
        env = Env({"XDG_CONFIG_HOME": str(self.config.parent), "CLAUDE_CONFIG_DIR": str(self.config.parent / "claude")})
        pins.pin_store(env).write(Pin(task_loop="1.2.4"))
        with mock.patch.object(pins.sys, "platform", "darwin"), \
                mock.patch.object(pins, "previous_version", return_value="1.2.3"), \
                mock.patch.object(pins, "cache_dirs", return_value={"1.2.3": Path("/old"), "1.2.4": Path("/new")}):
            assert pins.run_rollback(env, self.git) == 0
            assert pins.run_pin(env, "1.2.3", None, False, self.git) == 0
            assert pins.read_pin(env).task_loop == "1.2.3"
            pins.clear_pin(env)
            assert pins.run_rollback(env, self.git) == 0
            assert pins.read_pin(env).task_loop == "1.2.3"
        self.git.ls_remote.assert_not_called()
