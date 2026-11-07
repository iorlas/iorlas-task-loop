"""EVIDENCE (tl-9un.21): after each attempt of a check, its log and the files its `keep` names are copied (never linked) into
<run folder>/attempts/<run>-attempt-R/artifacts/<check>/attempt-N/, one directory per attempt, read-only, with a row of sha256 and
bytes; the originals can then be overwritten by the next attempt or the slot's reset and the evidence stays readable."""
import hashlib
import os
import shlex
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.check_host import CheckHostCase

from taskloop.app.run import worker_call
from taskloop.contracts.paths import RunFiles

CMD = "unity-like-check"


class Evidence(CheckHostCase):
    def setup_method(self):
        super().setup_method()
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
        d = RunFiles(eng.run_dir).artifacts(1) / "u" / "attempt-1"
        assert (
            sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())
            == ["Logs/Editor.log", "Logs/results.xml", "check.log"]
        )
        assert (d / "Logs/Editor.log").read_text() == "editor log of run 1\n"
        assert (d / "check.log").read_text() == (eng.run_dir / res.log).read_text()
        rows = {r["artifact"]: r for r in eng.records("evidence") if r["call_id"] == "u"}
        assert len(rows) == 3
        for rel, r in rows.items():
            data = (eng.run_dir / rel).read_bytes()
            assert (
                (r["artifact_hash"], r["bytes"], r["attempt"], r["call_id"], r["run_id"])
                == (hashlib.sha256(data).hexdigest(), len(data), 1, "u", eng.run_id)
            )

    def test_a_copy_is_a_file_of_its_own_and_read_only(self):
        eng, _ = self.attempt()
        src = Path(eng.wt) / "Logs" / "Editor.log"
        copy = RunFiles(eng.run_dir).artifacts(1) / "u" / "attempt-1" / "Logs" / "Editor.log"
        assert os.stat(src).st_ino != os.stat(copy).st_ino
        assert os.stat(copy).st_nlink == 1
        assert copy.stat().st_mode & 0o222 == 0
        src.write_text("the slot's next run\n")
        assert copy.read_text() == "editor log of run 1\n"

    def test_a_second_attempt_gets_its_own_directory_and_the_first_stays_as_it_was(self):
        eng, _ = self.attempt()
        eng.run_checks({"checks": [], "files": []}, "s")
        root = RunFiles(eng.run_dir).artifacts(1) / "u"
        assert sorted(p.name for p in root.iterdir()) == ["attempt-1", "attempt-2"]
        assert (root / "attempt-1" / "Logs/Editor.log").read_text() == "editor log of run 1\n"
        assert (root / "attempt-2" / "Logs/Editor.log").read_text() == "editor log of run 2\n"

    def test_a_glob_that_names_nothing_leaves_the_log_alone(self):
        eng = self.checks_engine(checks=[{"id": "v", "cmd": CMD, "keep": ["nothing/*.xml"]}], base_red=False)
        eng.run_checks({"checks": [], "files": []}, "s")
        d = RunFiles(eng.run_dir).artifacts(1) / "v" / "attempt-1"
        assert [p.name for p in d.iterdir()] == ["check.log"]

    def test_a_symlink_out_of_the_tree_is_not_followed(self):
        outside = Path(self.tmp.name) / "secret.xml"
        outside.write_text("secret")
        eng = self.checks_engine(checks=[{"id": "w", "cmd": shlex.join([CMD]), "keep": ["Logs/link.xml"]}], base_red=False)
        (Path(eng.wt) / "Logs").mkdir(exist_ok=True)
        (Path(eng.wt) / "Logs" / "link.xml").symlink_to(outside)
        eng.run_checks({"checks": [], "files": []}, "s")
        d = RunFiles(eng.run_dir).artifacts(1) / "w" / "attempt-1"
        assert [p.name for p in d.iterdir()] == ["check.log"]

    def test_a_secret_looking_name_is_not_copied_and_a_tool_written_one_gets_no_row(self):
        def run(cwd, env):
            (Path(cwd) / "Logs").mkdir(exist_ok=True)
            (Path(cwd) / "Logs" / "Editor.log").write_text("log\n")
            (Path(cwd) / "Logs" / "api-token.log").write_text("t0k3n\n")
            (Path(cwd) / "Logs" / ".env.log").write_text("K=V\n")
            (Path(env["TL_ARTIFACT_DIR"]) / "id_rsa").write_text("key\n")  # a tool writes straight into its attempt directory
            return 1, "red"
        procsim.fake("secretive-check", run)
        eng = self.checks_engine(checks=[{"id": "x", "cmd": "secretive-check", "keep": ["Logs/*.log", "Logs/.env.log"]}], base_red=False)
        eng.run_checks({"checks": [], "files": []}, "s")
        d = RunFiles(eng.run_dir).artifacts(1) / "x" / "attempt-1"
        copied = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and p.name != "id_rsa")
        assert copied == ["Logs/Editor.log", "check.log"]
        rows = {r["artifact"].rsplit("/", 1)[-1] for r in eng.records("evidence") if r["call_id"] == "x"}
        assert rows == {"Editor.log", "check.log"}

    def test_keeping_evidence_makes_no_model_call(self):
        with mock.patch.object(worker_call.dg, "call", side_effect=AssertionError("ingest called a model")):
            eng, _ = self.attempt()
        assert len([r for r in eng.records("evidence") if r["call_id"] == "u"]) == 3
