"""Connectivity failures before work pause the factory rather than failing a bead."""
import sys
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.land.checkout import Checkout
from taskloop.app.land.gitcall import must
from taskloop.contracts.slots import SlotGitError
from taskloop.domain.land.matchers import NetText, Push

DNS = "fatal: unable to access 'https://github.com/org/repo': Could not resolve host: github.com"


class Connectivity(Case):
    def test_network_table(self):
        positives = (
            DNS,
            "Temporary failure in name resolution",
            "fatal: unable to access 'https://github.com/r': Connection timed out",
            "fatal: unable to access 'https://github.com/r': Connection refused",
            "fatal: unable to access 'https://github.com/r': Failed to connect",
            "fatal: unable to access 'https://github.com/r': Network is unreachable",
            "fatal: unable to access 'https://github.com/r': SSL connection timeout",
            "fatal: unable to access 'https://github.com/r': Operation timed out",
            "Connection reset by peer",
            "fatal: early EOF",
            "fatal: the remote end hung up unexpectedly",
            "kex_exchange_identification: read: Connection reset by peer",
            "kex_exchange_identification: Connection closed by remote host",
            "ssh: connect to host github.com port 22: Connection timed out",
            "ssh: connect to host github.com port 22: Connection refused",
            "ssh: connect to host github.com port 22: Network unreachable",
            "ssh: connect to host github.com: cannot resolve",
            "Connection reset by peer\nfatal: Could not read from remote repository.",
        )
        negatives = (
            "Permission denied (publickey)",
            "Authentication failed",
            "fatal: couldn't find remote ref main",
            "CONFLICT (content): Merge conflict in app.py",
            "fatal: Could not read from remote repository.",
            "Permission denied (publickey)\nfatal: Could not read from remote repository.",
            "RPC failed",
        )
        for text in positives:
            with self.subTest(text=text):
                assert NetText.down(text.swapcase())
        for text in negatives:
            with self.subTest(text=text):
                assert not NetText.down(text)

    def test_only_the_last_600_characters_are_network_evidence(self):
        assert not NetText.down(DNS + "x" * 600)
        assert NetText.down("x" * 600 + DNS)
        assert Push.transient("RPC failed")

    def test_checked_fetch_classifies_network_and_preserves_other_faults(self):
        for text, kind, prefix in ((DNS, "PAUSE_NETWORK", "paused"),
                                   ("fatal: couldn't find remote ref main", "FAULT_INFRA", "failed")):
            with self.subTest(kind=kind):
                host = mock.Mock(wt="/slot")
                host.git.fetch.side_effect = SlotGitError(text)
                blocked = RuntimeError("blocked")
                host.blocked_for.return_value = blocked
                with pytest.raises(RuntimeError) as caught:
                    Checkout(host).fetch(check=True)
                assert caught.value is blocked
                host.blocked_for.assert_called_once_with(f"{prefix}: `git fetch -q origin`: {text}", kind)

    def test_unchecked_fetch_keeps_its_return_contract(self):
        host = mock.Mock(wt="/slot")
        host.git.fetch.side_effect = SlotGitError(DNS)
        assert Checkout(host).fetch() == (1, DNS)
        host.blocked_for.assert_not_called()

    def test_required_git_calls_classify_network_failures_before_work(self):
        for text, kind, prefix in ((DNS, "PAUSE_NETWORK", "paused"),
                                   ("Permission denied (publickey)", "FAULT_INFRA", "failed")):
            with self.subTest(kind=kind):
                host = mock.Mock()
                host.blocked_for.return_value = RuntimeError("blocked")
                call = mock.Mock(side_effect=SlotGitError(text))
                with pytest.raises(RuntimeError):
                    must(host, "checkout task/x-1", call)
                host.blocked_for.assert_called_once_with(f"{prefix}: `git checkout task/x-1`: {text}", kind)
