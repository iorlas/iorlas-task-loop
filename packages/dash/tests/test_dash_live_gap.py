"""A cursor that points into a worker file retention removed is reported as a gap, not read as a quiet stream."""

import os
import time
from pathlib import Path

from tlkernel.paths import ConfigDir
from tltestkit.narrow import must

from tldash.api import live
from tldash.testing import ingest, make_run


def test_a_removed_worker_file_is_a_gap_for_a_cursor_that_had_read_it(tmp_path: Path) -> None:
    b, lf = make_run(str(tmp_path))
    run = live.LiveRun(ConfigDir(tmp_path / "task-loop"), b.run)
    ingest(run.cfg, time.time())
    run.refresh()
    first = live.page(run)
    assert first["gap"] is False
    cursor = must(live.decode(first["cursor"]))
    assert live.page(run, cursor)["gap"] is False
    os.unlink(lf)  # retention
    run.refresh()
    assert live.page(run, cursor)["gap"] is True
    assert live.page(run)["gap"] is False  # a first load reads what there is
