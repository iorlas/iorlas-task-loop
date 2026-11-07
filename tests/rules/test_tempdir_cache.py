"""A test cannot leave tempfile's cached temp folder pointing at a folder it removed (the lander gate lost 1000+ tests to it)."""
import shutil
import tempfile
from pathlib import Path


def test_a_removed_temp_folder_stays_cached_only_inside_its_test(workdir):
    gone = workdir / "gone"
    gone.mkdir()
    tempfile.tempdir = str(gone)
    shutil.rmtree(gone)


def test_the_next_test_still_gets_a_temp_folder():
    made = Path(tempfile.mkdtemp())
    made.rmdir()
