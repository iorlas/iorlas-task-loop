"""Real layer, the keep-awake helper on Linux: this machine's `systemd-inhibit ... tail --pid` started through the shelf's
held spawn (`composition.keep_awake_host`), the hold replayed, and the helper's tree stopped and reaped on the way out.
Whether the inhibitor took effect is not checked (without a logind session it exits at once: still started and reaped);
skipped where the tools are absent. macOS (`caffeinate`) has no real test here."""

import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from taskloop.composition import keep_awake_host, keep_awake_spawn
from taskloop.keep_awake import Helper, Host, awake

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("systemd-inhibit") is None or shutil.which("tail") is None,
    reason="Linux with systemd-inhibit and tail only")


def test_the_helper_is_started_through_the_shelf_and_gone_after_the_block(tmp_path: Path) -> None:
    started: list[Helper] = []

    def spawn(argv: Sequence[str]) -> Helper:
        started.append(keep_awake_spawn(argv))
        return started[-1]

    real = keep_awake_host()
    lines: list[str] = []
    with awake(Host(real.platform, real.which, spawn), os.getpid(), "tasks", lines.append, lambda: 0.0, lines.append):
        assert len(started) == 1 and Path(f"/proc/{started[0].pid}").exists()  # running, or exited and not yet reaped
    assert [line.split(" ", 2)[2] for line in lines] == [f"rounds keep_awake started pid={started[0].pid}"]
    assert not Path(f"/proc/{started[0].pid}").exists()  # stopped and reaped (its pid not yet reused in this instant)
