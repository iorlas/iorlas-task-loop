"""`tl accounts` and the setup check: the worker accounts delegate reports, through the adapter."""

import io
from types import SimpleNamespace
from unittest import mock

# isort: split
from taskloop.adapters import delegate as dg
from taskloop.adapters.ident import config_dir
from taskloop.app.doctor import accounts, setup
from taskloop.stores.delegate import real_route
from tlkernel.env import snapshot
from tlkernel.paths import ConfigDir


def row(account, enabled=True, ready=True, fix=""):
    return SimpleNamespace(account=account, enabled=enabled, ready=ready, fix=fix)


def shown(op="list", account=""):
    out = io.StringIO()
    with mock.patch("sys.stdout", out):
        return accounts.accounts(op, account, real_route(), ConfigDir(config_dir(snapshot()))), out.getvalue()


def test_the_table_names_each_account_with_its_fix():
    rows = [row("A"), row("B", ready=False, fix="run b login")]
    with mock.patch.object(dg, "accounts", return_value=rows):
        rc, text = shown()
    assert rc == 0
    assert "A" in text
    assert "b login" in text.replace("run ", "")


def test_enable_and_decline_pass_the_choice_to_delegate():
    with mock.patch.object(dg, "accounts", return_value=[row("A")]), mock.patch.object(dg, "set_account") as put:
        assert shown("decline", "A")[0] == 0
        put.assert_called_once_with("A", False)


def test_an_unknown_account_is_an_error_line_not_a_crash():
    with mock.patch.object(dg, "set_account", side_effect=ValueError("unknown account X")):
        rc, text = shown("enable", "X")
    assert rc == 1
    assert "unknown account X" in text


def test_setup_asks_for_an_account_when_no_enabled_account_is_ready():
    with mock.patch.object(dg, "accounts", return_value=[row("A", ready=False)]):
        assert setup.accounts_check(real_route()).ok is False
    with mock.patch.object(dg, "accounts", return_value=[row("A")]):
        assert setup.accounts_check(real_route()).ok is True
