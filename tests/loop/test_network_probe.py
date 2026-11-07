"""Factory loops explicitly probe GitHub through the delegate's network probe."""
import sys
from pathlib import Path
from unittest import mock

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.launch import loop
from tlkernel.env import Env


class NetworkProbe(Case):
    def test_loop_requests_github_from_the_delegate(self):
        with mock.patch.object(loop, "delegate_route", return_value="/route.py"):
            probe = loop.make_probe("/repo", Env(), mock.Mock())
        assert probe is not None
        assert probe.hosts == ("github.com",)

    def test_missing_delegate_keeps_the_existing_no_probe_fallback(self):
        with mock.patch.object(loop, "delegate_route", return_value=""):
            assert loop.make_probe("/repo", Env(), mock.Mock()) is None
