"""Pictures keeps a render once through the artifacts keeper and registers it in the store (the look stage's side of the keeper)."""
import os
import sys
from pathlib import Path
from unittest import mock

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.spawn import port_git

from taskloop.app.look import shots
from tlartifacts import store

PNG = b"\x89PNG\r\n\x1a\n"


def png(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class Host(mock.NonCallableMock):
    """The engine as Pictures sees it: a worktree evidence dir, a run folder, the cap and a log (the rest of LookHost is a mock's)."""

    def __init__(self, root, run, cap_mb=200):
        super().__init__()
        self.bead, self.evidence_dir, self.run_dir = "x-1", root / "wt" / "evidence", root / "runs" / run
        self.cfg, self.notes, self.warned = mock.Mock(evidence_cap_mb=cap_mb, look_max_px=1280), [], []
        self.log = mock.Mock(note=self.notes.append)
        self.home = mock.Mock(artifact_store=lambda: root / "store")
        self.run_id, self.wt, self.artifact_repo = run, root / "wt", "r-1"
        self.ports = mock.Mock(repo=mock.Mock(key=lambda: "r-1"))
        self.facts = mock.Mock(bead=self.bead, evidence_dir=self.evidence_dir, run_dir=self.run_dir, cfg=self.cfg, home=self.home,
                               run_id=run, wt=self.wt)

    def make_pictures(self):
        """Pictures over this host: it is the facts' mock, the ports and the hand-offs at once."""
        return shots.Pictures(self.facts, self, mock.Mock(), self, port_git())

    def warn(self, text):
        self.warned.append(text)

    @staticmethod
    def now():
        return 5.0


class PicturesKeepOnce(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = mock.patch.object(shots.looks, "downscale")
        p.start()
        self.addCleanup(p.stop)

    def test_a_rerun_of_a_bead_keeps_its_pictures_as_links_to_the_first_runs(self):
        src = png(self.root / "raw" / "a.png", PNG + b"P" * 5000)
        for run in ("x-1-1", "x-1-2"):
            host = Host(self.root, run)
            host.evidence_dir.parent.joinpath("evidence").mkdir(parents=True, exist_ok=True)
            host.make_pictures().keep_picture(src, [], self.root / "base", 1)
            (host.run_dir / "evidence").mkdir(parents=True, exist_ok=True)
            assert len(host.make_pictures().keep_evidence()) == 1
        first, second = (self.root / "runs" / r / "evidence" / "a.png" for r in ("x-1-1", "x-1-2"))
        assert os.stat(first).st_ino == os.stat(second).st_ino

    def test_over_the_cap_the_picture_is_dropped_and_the_log_counts_it(self):
        host = Host(self.root, "x-1-1", cap_mb=0)
        pics = host.make_pictures()
        pics.keep_picture(png(self.root / "raw" / "a.png", b"P" * 10), [], self.root / "base", 1)
        assert not (host.evidence_dir / "a.png").exists()
        assert len(host.notes) == 1
        assert "1 file(s) not kept" in host.notes[0]

    def test_an_engine_render_is_registered_in_the_store_as_a_result_of_the_look_round(self):
        host = Host(self.root, "x-1-1")
        host.make_pictures().keep_picture(png(self.root / "raw" / "a.png", PNG + b"P" * 50), [], self.root / "base", 2)
        listed = store.listing(self.root / "store" / "r-1" / "x-1" / "x-1-1" / "look-2")
        assert [(m.name, m.role, m.created) for m in listed] == [("a.png", "result", 5.0)]
        assert host.warned == []

    def test_a_render_the_store_refuses_is_a_warning_not_a_failed_run(self):
        host = Host(self.root, "x-1-1")
        host.make_pictures().keep_picture(png(self.root / "raw" / "a.png", b"not a picture"), [], self.root / "base", 1)
        assert len(host.warned) == 1 and "not registered" in host.warned[0]
