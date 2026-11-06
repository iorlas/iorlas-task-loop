"""A pass recorded on one executor does not certify another: the executor's host is in the key of an `in: linux` check."""
from support.memstores import fake_stores
from support.spawn import port_git

from taskloop.app.checks.cache import InputKeys, RunMemo
from taskloop.contracts.checks import Check, CheckResult
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.runkey import BaseSha


def memo(stores, executor: str) -> RunMemo:
    keys = InputKeys(port_git(), "/unused", TreeSha("tree"))
    keys.files = {}
    return RunMemo(stores, "repo", keys, BaseSha("base"), {}, executor=executor)


def test_a_receipt_from_executor_a_does_not_certify_executor_b():
    stores, check = fake_stores(), Check(id=CheckId("t"), cmd="true", where="linux")
    a = memo(stores, "pix-a")
    key = a.key(check)
    assert key is not None
    a.remember(key, CheckResult(id=check.id, cmd="true", group="tests", exit=0, status="passed"), 1, "")
    assert a.result(check) is not None
    assert memo(stores, "pix-b").result(check) is None
    assert memo(stores, "pix-a").result(check) is not None


def test_a_host_check_is_keyed_without_the_executor():
    check = Check(id=CheckId("t"), cmd="true")
    assert memo(fake_stores(), "pix-a").key(check) == memo(fake_stores(), "pix-b").key(check)
