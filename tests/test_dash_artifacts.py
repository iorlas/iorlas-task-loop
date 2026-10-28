"""The dash's artifact display: the gallery on the bead page (newest first), the thumbs under each timeline step that made a
file (from the typed Artifacts record), and what the file route serves (HTML only ever as a download)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401  (ROOT/src on sys.path)
from support.dashes import make_dash  # noqa: E402
from support.logs import typed, write_log  # noqa: E402
from support.narrow import must  # noqa: E402

from taskloop_dash import http  # noqa: E402

BEAD = "tl-9"
RUN = BEAD + "-20261028-100000"
STATIC = ROOT / "src" / "taskloop_dash" / "static"
STEPS = [("n1", "write", ["a.png"]), ("n2", "review", ["b.png", "report.pdf"]), ("n3", "write", ["c.png"])]


def fake_run(cfg: str, dash) -> None:
    """A run of three steps that left 3 PNGs and 1 PDF, one Artifacts record per step, and the files as ingest copies them."""
    art = dash.env.config.artifacts(BEAD)
    art.mkdir(parents=True)
    recs, t = [typed("run_start", 1.0, run=RUN, bead=BEAD, worktree="/w", slot="s1", started_because="first")], 2.0
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

    def test_the_bead_page_carries_the_gallery_newest_round_first(self):
        dash = self.dash
        with mock.patch.object(dash.beads, "resolve_repo", lambda r, b="": "/repo"), \
                mock.patch.object(dash.beads, "show", lambda repo, bead: {"id": BEAD, "title": "T"}), \
                mock.patch.object(dash.beads, "comments", lambda repo, bead: []):
            out = dash.bead.api_bead("demo", BEAD)
        got = [(a["name"], a["kind"]) for a in out["artifacts"]]
        self.assertEqual(len(got), 4)
        self.assertEqual(got[0], ("c.png", "image"))  # the last step's file first
        self.assertEqual(sorted(got), [("a.png", "image"), ("b.png", "image"), ("c.png", "image"), ("report.pdf", "pdf")])

    def test_each_timeline_step_carries_the_thumbs_of_its_own_record(self):
        d = self.dash.tasks.api_task_timeline("", BEAD)
        blocks = d["runs"][0]["blocks"]
        files = {b["kind"] + b["label"]: [(f["name"], f["kind"]) for f in b["files"]] for b in blocks}
        self.assertEqual([[(f["name"], f["kind"]) for f in b["files"]] for b in blocks],
                         [[("a.png", "image")], [("b.png", "image"), ("report.pdf", "pdf")], [("c.png", "image")]], files)

    def test_the_pages_have_the_gallery_container_and_the_thumb_hooks(self):
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        for hook in ('id="artgal"', "Screenshots and files · ", "function thumbsHtml", "galleryHtml(b.id", 'class="thumbs"', "gi big"):
            self.assertIn(hook, index)
        self.assertLess(index.index("${arts}${cost}"), index.index("${sec('Description'"))  # the gallery is first, above cost
        live = (STATIC / "live.html").read_text(encoding="utf-8")
        for hook in ("k==='artifacts'", "'thumbs'", "/api/artifact?bead="):
            self.assertIn(hook, live)

    def test_html_is_only_ever_a_download_and_a_pdf_opens_as_a_pdf(self):
        art = self.dash.env.config.artifacts(BEAD)
        (art / "page.html").write_text("<script>alert(1)</script>")
        page = STATIC / "index.html"
        served = {n: http.raw_route(self.dash, page, page, "/api/artifact", {"bead": BEAD, "name": n})
                  for n in ("page.html", "report.pdf", "a.png")}
        self.assertEqual(must(served["page.html"])[2], "application/octet-stream")
        self.assertEqual(must(served["report.pdf"])[2], "application/pdf")
        self.assertEqual(must(served["a.png"])[2], "image/png")
        self.assertIn(("page.html", "file"), [(a["name"], a["kind"]) for a in self.dash.artifacts.listing(BEAD)])


if __name__ == "__main__":
    unittest.main()
