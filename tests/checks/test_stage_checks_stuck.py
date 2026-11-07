"""A stuck check delegates its facts to the host and raises the host's stop."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from taskloop.app.checks.step import CheckStepHost, StageChecks
from tlgate.host import CheckStuck


def test_stuck_checks_raise_the_hosts_stop(tmp_path: Path) -> None:
    stuck = CheckStuck("red-output-signature", 4)
    stop = RuntimeError("owner hint needed")
    host = Mock(spec=CheckStepHost, run_dir=tmp_path, MARKERS="")
    host.checker.run.side_effect = stuck
    host.checker.reds.return_value = []
    host.blocked_stuck.return_value = stop

    with pytest.raises(RuntimeError) as raised:
        StageChecks(host).run({"checks": [], "files": []}, "stage")

    assert raised.value is stop
    assert raised.value.__cause__ is stuck
    host.blocked_stuck.assert_called_once_with(
        "the same checks failed with the same output in 4 rounds in a row: "
        "more writes will not fix them; it needs the owner's hint\n"
        "signature: red-output-signature\n- (no checks)",
        "the same red checks", 4, "red-output-signature",
    )
    host.assert_tree.assert_called_once_with("checks", "after")
