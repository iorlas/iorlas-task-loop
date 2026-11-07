"""Release handovers preserve precedence, counters and the unfinished-close fallback."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from tlkernel.env import Env
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tlkernel.run import NetPause, Reexec

from tlrelease import reexec


@pytest.mark.parametrize("exec_bead,paused,dry,unfinished,source", [
    ("tl-one", True, False, True, "exec"),
    ("tl-other", True, False, True, "pause"),
    ("", False, False, True, "close"),
    ("", False, True, True, "fresh"),
    ("", False, False, False, "fresh"),
])
def test_resume_selects_one_source(tmp_path: Path, monkeypatch, exec_bead, paused, dry, unfinished, source):
    handover = Reexec(run="old", bead=exec_bead, frm="1.0.0") if exec_bead else None
    pause = NetPause(run="paused", bead="tl-one", t=1) if paused else None
    take_pause = Mock(return_value=pause)
    read = Mock(return_value="checkpoint")
    monkeypatch.setattr(reexec, "take_reexec", lambda env: handover)
    monkeypatch.setattr(reexec, "take_net_pause", take_pause)
    found = reexec.resume(Env(), ConfigDir(tmp_path), BeadId("tl-one"), dry, read, lambda ck: ck is not None and unfinished)
    assert (found.reexec is not None) == (source == "exec")
    assert (found.pause is not None) == (source == "pause")
    assert found.dead == ("checkpoint" if source == "close" else None)
    assert read.call_count == int(source == "close" or (source == "fresh" and not dry))
    assert take_pause.call_count == int(source != "exec")


@pytest.mark.parametrize("source", ["exec", "pause", "fresh"])
def test_restore_carries_done_memo_only_after_a_network_pause(tmp_path: Path, monkeypatch, source):
    exec_note = Reexec(run="old", bead="tl-one", frm="1.0.0") if source == "exec" else None
    pause = NetPause(run="paused", bead="tl-one", t=1) if source == "pause" else None
    doc = Mock()
    monkeypatch.setattr(reexec.rundocs, "reexec", lambda home, run: doc)
    monkeypatch.setattr(reexec.rundocs, "pause", lambda home, run: doc)
    restored, carried, notes = [], [], []
    reexec.Resume(exec_note, pause, None).restore(ConfigDir(tmp_path), "new", restored.append, carried.append, notes.append)
    assert restored == ([] if source == "fresh" else [doc])
    assert carried == ([ConfigDir(tmp_path).run_dir("paused")] if source == "pause" else [])
    assert notes == (["back from the network pause of paused: continuing as run new"] if source == "pause" else [])
