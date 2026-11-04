"""The dashboard's host is supplied once at its process edge and shared by readers."""

import unittest
from typing import Any, cast
from unittest.mock import patch

from taskloop.contracts.slottable import SlotSource
from taskloop_dash.cli import dash
from taskloop_dash.env import Env, Ports
from taskloop_dash.readers.world import Worlds


class DashboardHost(unittest.TestCase):
    def test_the_launcher_supplies_the_system_host_once(self):
        with patch("socket.gethostname", return_value="dtomilin-mWG") as hostname, \
                patch.object(dash, "code_version", return_value="v-test"), \
                patch.object(dash.serve, "main") as serve:
            dash.main([])
        hostname.assert_called_once_with()
        self.assertEqual(serve.call_args.args[0].host, "dtomilin-mWG")

    def test_the_injected_host_is_shared_by_world_and_slot_source(self):
        env = Env(config=".", host="injected", ports=Ports(slot_source=lambda _: SlotSource(host="other", count=4)))
        worlds = Worlds(*[cast(Any, value) for value in (env, None, None, None)])
        source = worlds.slot_source("/repo")
        self.assertEqual(source.host, env.host)
        self.assertEqual(source.count, 4)
