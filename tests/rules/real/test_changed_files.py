"""The change against origin/main: the files it touches in src/ add no type-checker escape (Any, ignore, cast) on net. Nothing is stored;
the base is the merge base with origin/main (a release works in a clone that has it). No origin/main: the check is skipped, said so."""
import subprocess
import sys
from pathlib import Path

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from rules.gate_rules import ROOT
from rules.type_counts import change_problems


def git(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(ROOT), *argv], capture_output=True, text=True, check=False)


class ChangedFiles(Case):
    def test_the_files_a_change_touches_add_no_type_escape_on_net(self):
        base = git("merge-base", "HEAD", "origin/main")
        if base.returncode != 0:
            pytest.skip("no origin/main to compare with")
        tip = base.stdout.strip()
        names = set(git("diff", "--no-renames", "--name-only", "--diff-filter=ACMRD", tip).stdout.split())
        names |= set(git("ls-files", "--others", "--exclude-standard").stdout.split())
        paths = sorted(n for n in names if n.startswith("src/") and n.endswith(".py") and "_vendor" not in n)
        before = {n: git("show", f"{tip}:{n}").stdout for n in paths if git("cat-file", "-e", f"{tip}:{n}").returncode == 0}
        after = {n: (ROOT / n).read_text(encoding="utf-8") for n in paths if (ROOT / n).is_file()}
        assert change_problems(before, after) == []
