"""The bead page's artifacts: the store `<config>/artifacts/<repo>/<bead>/<run>/<stage>-<attempt>/<name>` + `<name>.json`, listed by
fixed levels and cached by folder mtime, served by GET /api/artifact?repo=&bead=&run=&stage=&attempt=&name=. The writer is another
session's: the sidecar here follows the agreed schema, built by hand."""
import json
import os
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401  (ROOT/src on sys.path)
from support.dashes import make_dash  # noqa: E402
from support.dashlogs import RunScript  # noqa: E402
from support.narrow import must  # noqa: E402

from taskloop.app.artifacts import store  # noqa: E402
from taskloop_dash import http  # noqa: E402
from taskloop_dash.views import bead_detail, passes  # noqa: E402
from taskloop_dash.views.artifact_files import split_stage  # noqa: E402
from tlkernel.artifact import ArtifactSlot  # noqa: E402

REPO, BEAD = "lifesim", "tl-9"
RUN = BEAD + "-20261028-100000"
STATIC = ROOT / "src" / "taskloop_dash" / "static"
Q = {"repo": REPO, "bead": BEAD, "run": RUN}


def put(cfg: str, folder: str, name: str, data: bytes = b"x", role: str = "result", created: float = 100.0, caption: str = "",
        run: str = RUN):
    """A file and its sidecar, in the order the writer leaves them (file first, sidecar last)."""
    d = Path(cfg, "artifacts", REPO, BEAD, run, folder)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    kind = "png" if name.endswith(("html", "svg")) else name.rsplit(".", 1)[-1]  # forged for html/svg
    side = {"v": 1, "name": name, "caption": caption, "role": role, "kind": kind, "size": len(data), "sha256": "0" * 64, "created": created}
    (d / (name + ".json")).write_text(json.dumps(side))
    return d


def bump(path: Path, n: int = 5) -> None:
    """A folder change the listing must notice, whatever the filesystem's timestamp grain."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + n * 1_000_000_000))


class Store(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.dash = make_dash(config=self.tmp.name)
        self.art = self.dash.artifacts

    def teardown_method(self):
        self.tmp.cleanup()

    def names(self):
        return [(i.stage, i.attempt, i.name) for i in self.art.listing(REPO, BEAD, [RUN])]

    def test_walks_stage_attempt_folders_newest_sidecar_first(self):
        put(self.tmp.name, "write-1", "a.png", created=10)
        put(self.tmp.name, "write-2", "b.png", created=30, role="after", caption="the dialog")
        put(self.tmp.name, "look-1", "c.mp4", created=20, role="progress")
        got = self.art.listing(REPO, BEAD, [RUN])
        assert [(i.name, i.kind, i.role) for i in got] == [
            ("b.png", "image", "after"), ("c.mp4", "video", "progress"), ("a.png", "image", "result")]
        assert (got[0].stage, got[0].attempt, got[0].caption, got[0].t) == ("write", 2, "the dialog", 30.0)

    def test_a_file_without_a_sidecar_is_not_an_artifact(self):
        d = put(self.tmp.name, "write-1", "a.png")
        (d / "loose.png").write_bytes(b"x")
        (d / "orphan.png.json").write_text("{}")
        assert self.names() == [("write", 1, "a.png")]

    def test_a_sidecar_that_does_not_fit_the_schema_is_skipped(self):
        d = put(self.tmp.name, "write-1", "a.png")
        (d / "a.png.json").write_text(json.dumps({"v": 1, "caption": "", "role": "weird", "name": "a.png"}))
        assert self.names() == []

    def test_only_the_runs_asked_for_are_read(self):
        put(self.tmp.name, "write-1", "a.png", run="other-run")
        assert self.art.listing(REPO, BEAD, [RUN]) == []
        assert self.art.listing(REPO, BEAD, ["../" + RUN, ""]) == []
        assert [i.run for i in self.art.listing(REPO, BEAD, [RUN, "other-run"])] == ["other-run"]

    def test_the_old_flat_bead_folder_is_not_read(self):
        old = Path(self.tmp.name, "artifacts", BEAD)
        old.mkdir(parents=True)
        (old / "old.png").write_bytes(b"png")
        assert self.art.listing(REPO, BEAD, [RUN, BEAD]) == []
        assert must(http.route(self.dash, STATIC, "/api/artifact", {**Q, "stage": "write", "attempt": "1", "name": "old.png"}))[0] == 404
        assert must(http.route(self.dash, STATIC, "/api/artifact", {"bead": BEAD, "name": "old.png"}))[0] == 404

    def test_folder_names(self):
        assert split_stage("write-2") == ("write", 2)
        assert split_stage("a-b-10") == ("a-b", 10)
        assert [split_stage(x) for x in ("write", "-1", "write-x", "write-")] == [None] * 4


class Cache(Case):
    """A bead with 100 artifacts: each sidecar is read once per folder change, and a poll that changed nothing reads none."""

    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.dash = make_dash(config=self.tmp.name)
        self.art = self.dash.artifacts
        self.reads: list[str] = []
        real = type(self.art).sidecar

        def counting(me, path):
            self.reads.append(str(path))
            return real(me, path)

        type(self.art).sidecar = counting  # type: ignore[method-assign]
        self.real = real

    def teardown_method(self):
        type(self.art).sidecar = self.real  # type: ignore[method-assign]
        self.tmp.cleanup()

    def test_a_hundred_files_cost_a_hundred_sidecar_reads_once(self):
        for stage in range(1, 5):
            for n in range(25):
                put(self.tmp.name, f"write-{stage}", f"s{n}.png", created=stage * 100 + n)
        assert len(self.art.listing(REPO, BEAD, [RUN])) == 100
        assert len(self.reads) == 100
        for _ in range(5):
            self.art.listing(REPO, BEAD, [RUN])
        assert len(self.reads) == 100

    def test_a_changed_folder_is_read_again_and_no_other(self):
        d1 = put(self.tmp.name, "write-1", "a.png")
        put(self.tmp.name, "write-2", "b.png")
        self.art.listing(REPO, BEAD, [RUN])
        self.reads.clear()
        put(self.tmp.name, "write-1", "c.png")
        bump(d1)
        got = self.art.listing(REPO, BEAD, [RUN])
        assert len(got) == 3
        assert sorted(Path(p).parent.name for p in self.reads) == ["write-1", "write-1"]

    def test_a_new_stage_folder_is_found_by_the_run_folders_mtime(self):
        put(self.tmp.name, "write-1", "a.png")
        self.art.listing(REPO, BEAD, [RUN])
        put(self.tmp.name, "look-1", "b.png")
        bump(Path(self.tmp.name, "artifacts", REPO, BEAD, RUN))
        assert len(self.art.listing(REPO, BEAD, [RUN])) == 2

    def test_the_snapshot_and_the_bead_list_touch_no_artifact_file(self):
        put(self.tmp.name, "write-1", "a.png")
        self.dash.reads.snapshot()
        assert self.reads == []


class Serve(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.dash = make_dash(config=self.tmp.name)
        put(self.tmp.name, "write-1", "a.png", b"png")
        put(self.tmp.name, "write-1", "page.html", b"<script>alert(1)</script>")
        put(self.tmp.name, "write-1", "report.pdf", b"%PDF")
        put(self.tmp.name, "write-1", "clip.mp4", b"mp4")
        put(self.tmp.name, "write-1", "voice.wav", b"wav")
        put(self.tmp.name, "write-1", "pic.svg", b"<svg onload=alert(1)>")

    def teardown_method(self):
        self.tmp.cleanup()

    def get(self, name, **over):
        return http.route(self.dash, STATIC, "/api/artifact", {**Q, "stage": "write", "attempt": "1", "name": name, **over})

    def test_media_plays_inline_and_everything_else_is_a_download(self):
        inline = [("a.png", "image/png"), ("report.pdf", "application/pdf"), ("clip.mp4", "video/mp4"), ("voice.wav", "audio/vnd.wave")]
        for name, ctype in inline:
            code, _body, got, extra = must(self.get(name))
            assert (code, got, extra) == (200, ctype, []), name
        for name in ("page.html", "pic.svg"):
            code, _body, got, extra = must(self.get(name))
            assert (code, got, extra) == (200, "application/octet-stream", [("Content-Disposition", "attachment")]), name

    def test_refuses_bad_parts_a_missing_sidecar_and_a_symlink(self):
        d = Path(self.tmp.name, "artifacts", REPO, BEAD, RUN, "write-1")
        (d / "loose.png").write_bytes(b"x")
        os.symlink(d / "a.png", d / "link.png")
        (d / "link.png.json").write_text((d / "a.png.json").read_text().replace("a.png", "link.png"))
        bad = [self.get("loose.png"), self.get("link.png"), self.get("a.png.json"), self.get("../a.png"), self.get(".hidden"),
               self.get(""), self.get("a.png", run=".."), self.get("a.png", run="../x"), self.get("a.png", stage="../write"),
               self.get("a.png", attempt="x"), self.get("a.png", attempt="2"), self.get("a.png", repo="../"),
               self.get("a.png", bead="-bad"), self.get("a.png", bead="tl-8")]
        assert [r[0] for r in map(must, bad)] == [404] * len(bad)


class Detail(Case):
    def test_each_file_knows_its_pass_and_phase_by_the_nth_span_of_its_step(self):
        script = RunScript(BEAD, stamp="20261028-100000", slot="a").step("plan", 10, 1).step("write", 10, 1).step("checks", 10, 1)
        run = script.move("n2", "bad_checks").step("write", 10, 1).run(1_800_000_000.0)
        ps = passes.passes_of([run])
        assert [p.n for p in ps] == [1, 2]
        tmp = TemporaryDirectory()
        art = make_dash(config=tmp.name).artifacts
        put(tmp.name, "write-1", "a.png", role="before", created=1, run=run.name)
        put(tmp.name, "write-2", "b.png", role="after", created=2, run=run.name, caption="fixed")
        put(tmp.name, "review-1", "c.png", created=3, run=run.name)
        got = bead_detail.artifacts_of(REPO, BEAD, art.listing(REPO, BEAD, [run.name]), ps)
        tmp.cleanup()
        assert [(a.name, a.pass_n, a.phase and a.phase.value, a.role) for a in got] == [
            ("c.png", None, None, "result"), ("b.png", 2, "write", "after"), ("a.png", 1, "write", "before")]
        assert got[1].url.startswith("/api/artifact?repo=lifesim&bead=tl-9&run=" + run.name)
        assert "stage=write&attempt=2&name=b.png" in got[1].url
        assert (got[1].caption, got[1].kind, got[1].t) == ("fixed", "image", 2.0)


class WithTheWriter(Case):
    def test_what_the_store_writer_leaves_is_what_the_reader_lists_and_serves(self):
        with TemporaryDirectory() as tmp:
            src = Path(tmp, "shot.png")
            src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
            dash = make_dash(config=tmp)
            slot = ArtifactSlot(repo=REPO, bead=BEAD, run=RUN, stage="write", attempt=2)
            store.add(dash.env.config.artifact_store(), slot, src, name="shot.png", caption="the dialog", role="after", now=50.0)
            got = dash.artifacts.listing(REPO, BEAD, [RUN])
            assert [(i.stage, i.attempt, i.name, i.role, i.t) for i in got] == [("write", 2, "shot.png", "after", 50.0)]
            served = must(http.route(dash, STATIC, "/api/artifact", {**Q, "stage": "write", "attempt": "2", "name": "shot.png"}))
            assert (served[0], served[2]) == (200, "image/png")
