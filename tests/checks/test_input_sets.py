"""engine.input_sets and engine.hatch: globs written once, named by @name; a hatch file change forces every glob-keyed check."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
import unittest

from taskloop.contracts import inputsets
from taskloop.contracts.config import ConfigError, load
from taskloop.domain.checks.inputs import reads_digest, touched
from taskloop.domain.checks.specs import due, repo_check

SRC = ["src/**", "lib/**"]


def engine(checks, **eng):
    return load({"engine": {"input_sets": {"code": SRC}, "checks": checks, **eng}}).engine


def spec(cid, **kw):
    return {"id": cid, "argv": ["true"], **kw}


class InputSets(unittest.TestCase):
    def test_a_check_names_a_set_in_inputs_exclude_and_when(self):
        eng = engine([spec("a", inputs="@code", when=["@code", "docs/**"], exclude=["@code"])])
        c = repo_check(eng.checks[0], eng)
        self.assertEqual((c.inputs, c.when, c.exclude), (SRC, [*SRC, "docs/**"], SRC))

    def test_an_unknown_name_is_refused_at_load(self):
        with self.assertRaisesRegex(ConfigError, "check a names @nope, which engine.input_sets does not declare"):
            engine([spec("a", inputs=["@nope"])])
        with self.assertRaisesRegex(ConfigError, "engine.hatch names @nope"):
            engine([spec("a")], hatch=["@nope"])

    def test_a_set_that_names_a_set_is_refused(self):
        with self.assertRaisesRegex(ConfigError, "input_sets.deep names another set"):
            load({"engine": {"input_sets": {"code": SRC, "deep": ["@code"]}}})

    def test_a_set_no_check_uses_is_found(self):
        eng = engine([spec("a", inputs=["x/**"])], hatch=[])
        self.assertEqual(inputsets.unused(eng), ["code"])
        self.assertEqual(inputsets.unused(engine([spec("a", inputs=["@code"])])), [])
        self.assertEqual(inputsets.unused(engine([spec("a")], hatch=["@code"])), [])

    def test_a_hatch_file_change_runs_every_check_even_one_that_names_other_inputs(self):
        eng = engine([spec("keyed", inputs=["src/**"], inputs_only=True), spec("gated", when=["src/**"]), spec("whole")],
                     hatch=["tools/gate.py", ".task-loop.json"])
        keyed, gated, whole = (repo_check(k, eng) for k in eng.checks)
        changed = ["tools/gate.py"]
        self.assertTrue(touched(keyed, changed))
        self.assertTrue(due(gated, changed))
        self.assertTrue(due(whole, changed))
        self.assertFalse(touched(keyed, ["docs/readme.md"]))
        self.assertFalse(due(gated, ["docs/readme.md"]))

    def test_the_hatch_files_are_part_of_what_the_cache_keys_on(self):
        eng = engine([spec("keyed", inputs=["src/**"], inputs_only=True)], hatch=["tools/gate.py"])
        keyed = repo_check(eng.checks[0], eng)
        before = reads_digest(keyed, {"src/a.py": "100644 aa", "tools/gate.py": "100644 11"}, {})
        after = reads_digest(keyed, {"src/a.py": "100644 aa", "tools/gate.py": "100644 22"}, {})
        self.assertNotEqual(before, after)

    def test_a_check_with_no_inputs_or_when_stays_whole_tree(self):
        eng = engine([spec("whole")], hatch=["tools/gate.py"])
        c = repo_check(eng.checks[0], eng)
        self.assertEqual((c.inputs, c.when), ([], []))


if __name__ == "__main__":
    unittest.main()
