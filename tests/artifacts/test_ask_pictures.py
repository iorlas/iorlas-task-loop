"""A stuck or decision ask carries the pictures the failing check left (tl-3qz): registered in the store, named on the ask."""
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

from taskloop.app.artifacts import ask_pictures, store
from taskloop.contracts.artifact import ArtifactSlot
from taskloop.contracts.paths import RunFiles

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class AskPictures(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name) / "run"
        self.root = Path(tmp.name) / "store"
        self.slot = ArtifactSlot(repo="r-1", bead="t-1", run="RUN", stage="ask", attempt=1)

    def attempt(self, check: str, n: int, **files: bytes) -> Path:
        d = RunFiles(self.run_dir).artifacts(1) / check / f"attempt-{n}"
        d.mkdir(parents=True)
        for name, data in files.items():
            (d / name.replace("_", ".")).write_bytes(data)
        return d

    def test_the_images_of_the_last_attempt_of_each_check_are_registered_and_named(self):
        self.attempt("skin", 1, old_png=PNG)
        self.attempt("skin", 2, cheek_png=PNG, check_log=b"log text")
        self.attempt("other", 1, plain_txt=b"no picture")
        ids = ask_pictures.attach(self.root, self.slot, self.run_dir, now=5.0)
        assert ids == ["r-1/t-1/RUN/ask-1/skin-cheek.png"]
        (meta,) = store.listing(store.folder(self.root, self.slot))
        assert (meta.name, meta.role, meta.kind) == ("skin-cheek.png", "result", "png")
        assert "skin" in meta.caption

    def test_a_run_that_kept_nothing_attaches_nothing(self):
        assert ask_pictures.attach(self.root, self.slot, self.run_dir, now=5.0) == []

    def test_a_file_that_is_not_what_its_name_says_is_skipped_and_the_cap_holds(self):
        self.attempt("c", 1, fake_png=b"not a picture", **{f"p{i}_png": PNG for i in range(ask_pictures.MAX_PICTURES + 3)})
        ids = ask_pictures.attach(self.root, self.slot, self.run_dir, now=5.0)
        assert len(ids) == ask_pictures.MAX_PICTURES
        assert all("fake" not in i for i in ids)
