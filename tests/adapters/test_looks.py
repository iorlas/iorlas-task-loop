"""tl-bxk.13.15: looks.py, the shot table and what the engine builds from a writer's shot request."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contextlib  # noqa: E402

import support.paths  # noqa: E402, F401

from taskloop.adapters import looks  # noqa: E402

TABLE = {"v": 1, "methods": [
    {"method": "CreatorShots", "summary": "named creator categories",
     "argv": ["Unity", "-batchmode", "-executeMethod", "Lifesim.Editor.CreatorShots.Run", "{args}", "-logFile", "client/Logs/c.log"],
     "args": [{"name": "shots", "flag": "-shots", "pattern": "[\\w=,:-]+", "about": "body=body,face=face"}],
     "out": "client/Logs/shots", "files": "*.png", "timeout_min": 15},
    {"method": "ShellShots", "summary": "main menu", "argv": ["Unity", "-executeMethod", "Shell.Run", "-out", "{out}"],
     "args": [{"name": "who", "flag": "--who", "required": True}]}]}


class Table(unittest.TestCase):
    def methods(self):
        m, err = looks.parse_table(json.dumps(TABLE))
        self.assertEqual(err, "")
        return m

    def test_a_table_parses_and_a_bad_one_names_its_fault(self):
        self.assertEqual(sorted(self.methods()), ["CreatorShots", "ShellShots"])
        self.assertIn("not JSON", looks.parse_table("{")[1])
        self.assertIn("no methods", looks.parse_table('{"methods": []}')[1])
        self.assertIn("name and an argv list", looks.parse_table('{"methods": [{"method": "X"}]}')[1])
        self.assertIn("without a name and a flag", looks.parse_table(json.dumps({"methods": [
            {"method": "X", "argv": ["c"], "args": [{"name": "a"}]}]}))[1])

    def test_the_writers_menu_lists_methods_and_arguments(self):
        text = looks.table_text(self.methods())
        self.assertIn("CreatorShots: named creator categories [args: shots e.g. body=body,face=face]", text)
        self.assertIn("who (required)", text)
        self.assertLessEqual(len(looks.table_text(self.methods(), cap=40)), 40)

    def test_a_long_summary_is_one_short_line_in_the_menu(self):
        m, _err = looks.parse_table(
            json.dumps({"methods": [{"method": "X", "argv": ["c"], "summary": "Does the first thing. " + "Second long sentence. " * 30}]})
        )
        text = looks.table_text(m)
        self.assertEqual(text, "- X: Does the first thing.")
        self.assertEqual(looks.short("a" * 400, 50), "a" * 47 + "...")

    def test_a_command_is_built_only_from_the_table_and_its_declared_arguments(self):
        m = self.methods()
        cmd, _entry, err = looks.build(m, {"method": "CreatorShots", "args": [{"name": "shots", "value": "body=body,face=face"}]}, "/o")
        self.assertEqual(err, "")
        self.assertEqual(cmd, ["Unity", "-batchmode", "-executeMethod", "Lifesim.Editor.CreatorShots.Run", "-shots", "body=body,face=face",
                               "-logFile", "client/Logs/c.log"])
        cmd, _, err = looks.build(m, {"method": "CreatorShots", "args": []}, "/o")
        self.assertEqual(cmd[-3:], ["Lifesim.Editor.CreatorShots.Run", "-logFile", "client/Logs/c.log"])
        cmd, _, err = looks.build(m, {"method": "ShellShots", "args": [{"name": "who", "value": "me"}]}, "/tmp/o dir")
        self.assertEqual(
            cmd, ["Unity", "-executeMethod", "Shell.Run", "-out", "/tmp/o dir", "--who", "me"]
        )  # one word, no quoting; no {args}: appended

    def test_a_request_the_table_does_not_allow_builds_nothing(self):
        m = self.methods()
        for req, why in (({"method": "Nope"}, "no shot method"),
                         ({"method": "CreatorShots", "args": [{"name": "evil", "value": "x"}]}, "takes no argument"),
                         ({"method": "CreatorShots", "args": [{"name": "shots", "value": "a; rm -rf /"}]}, "does not match"),
                         ({"method": "CreatorShots", "args": [{"name": "shots", "value": "$(id)"}]}, "does not match"),
                         ({"method": "ShellShots", "args": []}, "needs the argument")):
            cmd, _, err = looks.build(m, req, "/o")
            self.assertEqual(cmd, [], req)
            self.assertIn(why, err)

    def test_collect_takes_new_or_changed_pictures_not_old_ones_nor_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            wt, out = Path(d, "wt"), Path(d, "out")
            (wt / "client/Logs/shots").mkdir(parents=True)
            out.mkdir()
            shots = wt / "client/Logs/shots"
            (shots / "old.png").write_bytes(b"x")
            os.utime(shots / "old.png", (1, 1))
            m = self.methods()["CreatorShots"]
            before = looks.snapshot(m, wt)
            (shots / "new.png").write_bytes(b"x")
            (shots / "new.txt").write_text("x")
            (out / "mine.png").write_bytes(b"x")
            with contextlib.suppress(OSError):
                os.symlink("/etc/hosts", shots / "link.png")
            got = [f.name for f in looks.collect(m, wt, out, before)]
            self.assertEqual(sorted(got), ["mine.png", "new.png"])
            (shots / "old.png").write_bytes(b"changed")  # same name, new bytes: it was made now
            self.assertIn("old.png", [f.name for f in looks.collect(m, wt, out, before)])

    def test_a_value_never_starts_with_a_dash_and_a_bad_table_value_is_an_error_not_a_crash(self):
        m = self.methods()
        for v in ("--evil=1", "-executeMethod"):
            cmd, _, err = looks.build(m, {"method": "ShellShots", "args": [{"name": "who", "value": v}]}, "/o")
            self.assertEqual(cmd, [], v)
            self.assertIn("does not match", err)
        self.assertIn("timeout_min", looks.parse_table(json.dumps({"methods": [{"method": "X", "argv": ["c"], "timeout_min": "soon"}]}))[1])
        self.assertIn("bad pattern", looks.parse_table(json.dumps({"methods": [
            {"method": "X", "argv": ["c"], "args": [{"name": "a", "flag": "-a", "pattern": "("}]}]}))[1])
        positional = {"methods": [{"method": "P", "argv": ["run"], "args": [{"name": "n", "flag": ""}]}]}
        cmd, _, err = looks.build(
            looks.parse_table(json.dumps(positional))[0], {"method": "P", "args": [{"name": "n", "value": "main"}]}, "/o"
        )
        self.assertEqual((cmd, err), (["run", "main"], ""))


class Judge(unittest.TestCase):
    def test_same_defect_is_about_the_same_words(self):
        self.assertTrue(
            looks.same_defect("The Save button is clipped at the right edge", "save button clipped on the right edge of the card")
        )
        self.assertFalse(looks.same_defect("The Save button is clipped", "Magenta texture on the sofa"))
        self.assertFalse(looks.same_defect("", "anything"))
        self.assertFalse(looks.same_defect("clipped", "The Save button is clipped at the right edge"))  # one word is no match
        self.assertTrue(looks.same_defect("Clipped", "clipped"))

    def test_the_judges_brief_has_pictures_references_befores_items_and_no_repo(self):
        text = looks.judge_prompt(
            ["The picker shows a hue gradient"],
            ["build-6.png"],
            ["ref-mock.png"],
            [("build-6.png", "before-build-6.png")],
            "recoloured the picker",
        )
        for part in ("You have no other context", "- build-6.png", "- ref-mock.png", "before-build-6.png (before)", "hue gradient",
                     "recoloured the picker", "a matter of taste is never a defect", "magenta"):
            self.assertIn(part, text)

    def test_downscale_falls_back_to_a_copy_and_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "a.png")
            src.write_bytes(b"not an image")
            why = looks.downscale(src, Path(d, "sub", "b.png"), 100)
            self.assertTrue(Path(d, "sub", "b.png").is_file())
            self.assertIn("not downscaled", why)  # the bytes are no picture: the tool fails, the copy stands


if __name__ == "__main__":
    unittest.main()
