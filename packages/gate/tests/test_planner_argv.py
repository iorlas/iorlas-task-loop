"""Plan argv admission has no profile-owned harness grant."""
from tlkernel.plancheck import adhoc
from tltestkit.cfgs import cfg_with

from tlgate.domain import planref


def test_adhoc_commands_do_not_consult_a_harness_grant():
    cfg = cfg_with(checks=[{"id": "lint", "argv": ["ruff", "check"], "run": "both"}])
    assert planref.refusal(adhoc("curl http://x"), cfg) == ""
    assert planref.refusal(adhoc("python3 -m pytest"), cfg) == ""
