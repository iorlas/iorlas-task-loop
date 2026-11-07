"""ratchet_change.texts_at: the texts of many files at a revision from one git process; a file that did not exist is None."""
import subprocess

import support.paths  # noqa: F401

from rules.ratchet_change import texts_at


def test_texts_at_reads_present_and_missing_files_in_order(tmp_path):
    def git(*argv):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", *argv], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "a.py").write_text("A = 1\n")
    (tmp_path / "b.py").write_text("B = 'é'\n\n")
    git("add", ".")
    git("commit", "-qm", "x")
    got = texts_at(tmp_path, "HEAD", ("a.py", "gone.py", "b.py"))
    assert got == {"a.py": "A = 1\n", "gone.py": None, "b.py": "B = 'é'\n\n"}
