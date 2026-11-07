"""The dashboard's host is supplied once at its process edge and shared by readers."""
from typing import Any, cast
from unittest.mock import patch

from support.case import Case

from taskloop_dash.cli import dash
from taskloop_dash.env import Env, Ports
from taskloop_dash.readers.world import Worlds
from tlkernel import factorydb
from tlkernel.slottable import SlotSource


class DashboardHost(Case):
    def test_the_launcher_supplies_the_system_host_once(self):
        with patch.object(factorydb._STORE, "parts", None), \
                patch.object(factorydb._STORE, "complete", True), patch.object(factorydb._STORE, "needs", None), \
                patch("socket.gethostname", return_value="dtomilin-mWG") as hostname, \
                patch.object(dash, "code_version", return_value="v-test"), \
                patch.object(dash.serve, "main") as serve:
            dash.main([])
        hostname.assert_called_once_with()
        assert serve.call_args.args[0].host == "dtomilin-mWG"

    def test_the_injected_host_is_shared_by_world_and_slot_source(self):
        env = Env(config=".", host="injected", ports=Ports(slot_source=lambda _: SlotSource(host="other", count=4)))
        worlds = Worlds(*[cast(Any, value) for value in (env, None, None, None)])
        source = worlds.slot_source("/repo")
        assert source.host == env.host
        assert source.count == 4
