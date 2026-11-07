"""A checkout has one key however its folder is spelled: a symlinked folder (/var is /private/var on a Mac) is the same repo, for the
loop's files, the slots and the run rows alike."""

from support import homes

from taskloop.app.launch import loop as wloop
from taskloop.app.wire import slots as wslots
from tlkernel.ids import loop_key
from tlkernel.locator import RunLocator
from tlkernel.loop import LoopState


class TestRepoKey:
    def folders(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (tmp_path / "link").symlink_to(real)
        return str(tmp_path / "link"), str(real.resolve())

    def test_a_symlinked_folder_has_the_key_of_the_real_one(self, tmp_path):
        link, real = self.folders(tmp_path)
        assert loop_key(link) == loop_key(real) == wslots.repo_key(link)

    def test_a_loop_started_on_one_spelling_is_seen_on_the_other(self, tmp_path):
        link, real = self.folders(tmp_path)
        cfg = homes.cfg()
        wloop.files_of(link, cfg).write(LoopState(pid=1, started=1.0, t=1.0, repo=link, version="0.0.1", code_dir="/x", actor="tl-x"))
        assert wloop.files_of(real, cfg).read(1) is not None

    def test_a_run_made_on_one_spelling_is_keyed_as_the_other(self, tmp_path):
        link, real = self.folders(tmp_path)
        locator = RunLocator(homes.cfg())
        made = locator.create(link, "t-1", 1.0)
        with locator.rows.transaction() as con:
            row = con.execute("SELECT repo_key FROM run WHERE run=?", (made.run,)).fetchone()
        assert row[0] == loop_key(real)
