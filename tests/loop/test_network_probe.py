"""Factory loops explicitly probe GitHub through the delegate's network probe."""
from unittest import mock

from taskloop.app.launch import loop
from tlkernel.env import Env
from tltestkit.case import Case


class NetworkProbe(Case):
    def test_loop_requests_github_from_the_delegate(self):
        with mock.patch.object(loop, "delegate_route", return_value="/route.py"):
            probe = loop.make_probe("/repo", Env(), mock.Mock())
        assert probe is not None
        assert probe.hosts == ("github.com",)

    def test_missing_delegate_keeps_the_existing_no_probe_fallback(self):
        with mock.patch.object(loop, "delegate_route", return_value=""):
            assert loop.make_probe("/repo", Env(), mock.Mock()) is None
