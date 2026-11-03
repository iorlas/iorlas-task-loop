"""Release interval and canary acknowledgement are durable policy, independent of the clock and git."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

from taskloop.app.release import pins, train
from taskloop.app.release.shell import Abort
from taskloop.contracts.env import Env


class Train(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = Path(tmp.name) / "task-loop"
        self.url = "test-origin"

    def ship(self, at=1000.0, version="1.2.3", urgent=""):
        train.shipped(self.config, self.url, version, urgent, lambda: at)

    def test_first_release_and_exactly_two_hours_are_allowed(self):
        train.require_slot(self.config, self.url, "", lambda: 1000)
        self.ship()
        train.require_slot(self.config, self.url, "", lambda: 8200)

    def test_second_release_and_backwards_clock_are_refused(self):
        self.ship()
        for now in (1000, 8199.9, 500):
            with self.subTest(now=now), self.assertRaisesRegex(Abort, "--urgent"):
                train.require_slot(self.config, self.url, "", lambda at=now: at)

    def test_urgent_reason_bypasses_interval_and_is_preserved(self):
        self.ship()
        train.require_slot(self.config, self.url, "fix outage", lambda: 1001)
        self.ship(1001, "1.2.4", "fix outage")
        rec = train.read(train.state(self.config, self.url))
        assert rec
        self.assertEqual((rec.version, rec.urgent, rec.ring), ("1.2.4", "fix outage", "devbox"))

    def test_blank_reason_and_torn_state_cannot_bypass_interval(self):
        self.ship()
        with self.assertRaises(Abort):
            train.require_slot(self.config, self.url, "  ", lambda: 1001)
        train.state(self.config, self.url).path.write_text("{torn")
        with self.assertRaises(Abort):
            train.require_slot(self.config, self.url, "repair", lambda: 1001)

    def test_acknowledgement_changes_ring_without_resetting_the_interval(self):
        self.ship()
        self.assertIn("devbox-ok", train.mac_pin_refusal(self.config, "1.2.3"))
        train.devbox_ok(self.config, self.url, "1.2.3")
        self.assertEqual(train.mac_pin_refusal(self.config, "1.2.3"), "")
        rec = train.read(train.state(self.config, self.url))
        assert rec
        self.assertEqual((rec.ring, rec.at), ("devbox-ok", 1000))
        with self.assertRaises(Abort):
            train.devbox_ok(self.config, self.url, "9.9.9")

    def test_mac_pin_is_refused_until_canary_acknowledgement(self):
        self.ship()
        env = Env({"XDG_CONFIG_HOME": str(self.config.parent)})
        with mock.patch.object(pins.sys, "platform", "darwin"), \
                mock.patch.object(pins, "cache_dirs", return_value={"1.2.3": Path("/installed")}):
            _, why = pins.set_pin(env, "1.2.3")
            self.assertIn("devbox-ok", why)
            self.assertIsNone(pins.pin_store(env).get())
            train.devbox_ok(self.config, self.url, "1.2.3")
            pin, why = pins.set_pin(env, "1.2.3")
            self.assertEqual(why, "")
            self.assertEqual(pin.task_loop, "1.2.3")

    def test_unknown_and_invalid_versions_cannot_authorize_a_pin(self):
        self.assertTrue(train.mac_pin_refusal(self.config, "1.2.3"))
        self.assertTrue(train.mac_pin_refusal(self.config, "../../elsewhere"))
