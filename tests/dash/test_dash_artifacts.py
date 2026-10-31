"""What GET /api/artifact serves: HTML only ever as a download, a PDF as a PDF."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401  (ROOT/src on sys.path)
from support.dashes import make_dash  # noqa: E402
from support.logs import typed, write_log  # noqa: E402
from support.narrow import must  # noqa: E402

from taskloop.contracts.ids import BeadId  # noqa: E402
from taskloop_dash import http  # noqa: E402

BEAD = "tl-9"
RUN = BEAD + "-20261028-100000"
STATIC = ROOT / "src" / "taskloop_dash" / "static"
STEPS = [("n1", "write", ["a.png"]), ("n2", "review", ["b.png", "report.pdf"]), ("n3", "write", ["c.png"])]


def fake_run(cfg: str, dash) -> None:
    """A run of three steps that left 3 PNGs and 1 PDF, one Artifacts record per step, and the files as ingest copies them."""
    art = dash.env.config.artifacts(BEAD)
    art.mkdir(parents=True)
    recs, t = [typed("run_start", 1.0, run_id=RUN, bead=BEAD, worktree="/w", slot="s1", started_because="first")], 2.0
    for n, (sid, step, names) in enumerate(STEPS):
        recs.append(typed("step_start", t, id=sid, step=step, text=step))
        for name in names:
            (art / name).write_bytes(b"%PDF" if name.endswith(".pdf") else b"png")
            os.utime(art / name, (100 + n, 100 + n))  # a later step is newer
        recs.append(typed("artifacts", t + 1, id=sid, step=step, bead=BEAD, names=names))
        recs.append(typed("step_end", t + 2, id=sid, step=step, outcome="ok"))
        t += 3
    (Path(cfg) / "engine").mkdir(parents=True, exist_ok=True)
    write_log(Path(cfg) / "engine" / (RUN + ".jsonl"), recs)


class Gallery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dash = make_dash(config=self.tmp.name)
        fake_run(self.tmp.name, self.dash)

    def tearDown(self):
        self.tmp.cleanup()

    def test_html_is_only_ever_a_download_and_a_pdf_opens_as_a_pdf(self):
        art = self.dash.env.config.artifacts(BeadId(BEAD))
        (art / "page.html").write_text("<script>alert(1)</script>")
        served = {n: http.route(self.dash, STATIC, "/api/artifact", {"bead": BEAD, "name": n})
                  for n in ("page.html", "report.pdf", "a.png")}
        self.assertEqual(must(served["page.html"])[2], "application/octet-stream")
        self.assertEqual(must(served["report.pdf"])[2], "application/pdf")
        self.assertEqual(must(served["a.png"])[2], "image/png")


if __name__ == "__main__":
    unittest.main()
