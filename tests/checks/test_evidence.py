"""EVIDENCE (tl-9un.21): after each attempt of a check, its log and the files its `keep` names are copied (never linked) into
<run folder>/artifacts/<check>/attempt-N/, one directory per attempt, read-only, with a row of sha256 and bytes; the originals can then
be overwritten by the next attempt or the slot's reset and the evidence stays readable."""
import hashlib
import os
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.engine_case import EngineTest
from support.logs import records

CMD = "unity-like-check"


class Evidence(EngineTest):
    def setUp(self):
        super().setUp()
        self.runs = 0

        def run(cwd, env):
            self.runs += 1
            (Path(cwd) / "Logs").mkdir(exist_ok=True)
            (Path(cwd) / "Logs" / "Editor.log").write_text(f"editor log of run {self.runs}\n")
            (Path(cwd) / "Logs" / "results.xml").write_text(f"<r n='{self.runs}'/>")
            return 1, f"red {self.runs}"
        procsim.fake(CMD, run)

    def attempt(self):
        eng = self.checks_engine(checks=[{"id": "u", "cmd": CMD, "keep": ["Logs/*.log", "Logs/*.xml", "../outside/*"]}], base_red=False)
        return eng, eng.run_checks({"checks": [], "files": []}, "s")[0]

    def test_the_log_and_the_kept_files_are_copied_with_hash_and_bytes_before_anything_can_overwrite_them(self):
        eng, res = self.attempt()
        d = eng.run_dir / "artifacts" / "u" / "attempt-1"
        self.assertEqual(sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()),
                         ["Logs/Editor.log", "Logs/results.xml", "check.log"])
        self.assertEqual((d / "Logs/Editor.log").read_text(), "editor log of run 1\n")
        self.assertEqual((d / "check.log").read_text(), (eng.run_dir / res.log).read_text())
        rows = {r["artifact"]: r for r in records(eng, "evidence") if r["call_id"] == "u"}
        self.assertEqual(len(rows), 3)
        for rel, r in rows.items():
            data = (eng.run_dir / rel).read_bytes()
            self.assertEqual((r["artifact_hash"], r["bytes"], r["attempt"], r["call_id"], r["run_id"]),
                             (hashlib.sha256(data).hexdigest(), len(data), 1, "u", eng.run_id))

    def test_a_copy_is_a_file_of_its_own_and_read_only(self):
        eng, _ = self.attempt()
        src = Path(eng.wt) / "Logs" / "Editor.log"
        copy = eng.run_dir / "artifacts" / "u" / "attempt-1" / "Logs" / "Editor.log"
        self.assertNotEqual(os.stat(src).st_ino, os.stat(copy).st_ino)
        self.assertEqual(os.stat(copy).st_nlink, 1)
        self.assertEqual(copy.stat().st_mode & 0o222, 0)
        src.write_text("the slot's next run\n")
        self.assertEqual(copy.read_text(), "editor log of run 1\n")

    def test_a_second_attempt_gets_its_own_directory_and_the_first_stays_as_it_was(self):
        eng, _ = self.attempt()
        eng.run_checks({"checks": [], "files": []}, "s")
        root = eng.run_dir / "artifacts" / "u"
        self.assertEqual(sorted(p.name for p in root.iterdir()), ["attempt-1", "attempt-2"])
        self.assertEqual((root / "attempt-1" / "Logs/Editor.log").read_text(), "editor log of run 1\n")
        self.assertEqual((root / "attempt-2" / "Logs/Editor.log").read_text(), "editor log of run 2\n")

    def test_a_glob_that_names_nothing_leaves_the_log_alone(self):
        eng = self.checks_engine(checks=[{"id": "v", "cmd": CMD, "keep": ["nothing/*.xml"]}], base_red=False)
        eng.run_checks({"checks": [], "files": []}, "s")
        d = eng.run_dir / "artifacts" / "v" / "attempt-1"
        self.assertEqual([p.name for p in d.iterdir()], ["check.log"])

    def test_a_symlink_out_of_the_tree_is_not_followed(self):
        outside = Path(self.tmp.name) / "secret.xml"
        outside.write_text("secret")
        eng = self.checks_engine(checks=[{"id": "w", "cmd": shlex.join([CMD]), "keep": ["Logs/link.xml"]}], base_red=False)
        (Path(eng.wt) / "Logs").mkdir(exist_ok=True)
        (Path(eng.wt) / "Logs" / "link.xml").symlink_to(outside)
        eng.run_checks({"checks": [], "files": []}, "s")
        d = eng.run_dir / "artifacts" / "w" / "attempt-1"
        self.assertEqual([p.name for p in d.iterdir()], ["check.log"])


if __name__ == "__main__":
    unittest.main()
