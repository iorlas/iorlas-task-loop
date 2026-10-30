"""A ratchet on the escapes from the type checker in src/: explicit `Any`, `# pyrefly: ignore`, `# type: ignore` and `cast(`.

tests/rules/type_ratchet.json records today's counts. A count above its record fails; a count below it fails too until the
record is lowered to match (so the number only goes down and a freed slot cannot be spent again).
"""
import ast
import io
import json
import sys
import tokenize
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
RECORD = Path(__file__).with_name("type_ratchet.json")
KINDS = ("any", "pyrefly_ignore", "type_ignore", "cast")


def count_source(text: str) -> dict[str, int]:
    """The four counts in one module's source: Any names and attributes outside imports, ignore comments, cast calls."""
    out = dict.fromkeys(KINDS, 0)
    for node in ast.walk(ast.parse(text)):
        if (isinstance(node, ast.Name) and node.id == "Any") or (isinstance(node, ast.Attribute) and node.attr == "Any"):
            out["any"] += 1
        elif isinstance(node, ast.Call):
            fn = node.func
            if (isinstance(fn, ast.Name) and fn.id == "cast") or (isinstance(fn, ast.Attribute) and fn.attr == "cast"):
                out["cast"] += 1
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            body = tok.string.lstrip("# ").lower()
            out["pyrefly_ignore"] += body.startswith("pyrefly: ignore")
            out["type_ignore"] += body.startswith("type: ignore")
    return out


def count_tree(root: Path = ROOT) -> dict[str, int]:
    total = dict.fromkeys(KINDS, 0)
    for path in sorted((root / "src").rglob("*.py")):
        if "_vendor" in path.parts:
            continue
        for kind, n in count_source(path.read_text(encoding="utf-8")).items():
            total[kind] += n
    return total


def problems(actual: dict[str, int], recorded: dict[str, int]) -> list[str]:
    out = []
    for kind in KINDS:
        if actual[kind] > recorded[kind]:
            out.append(f"{kind}: {actual[kind]} in src/, recorded {recorded[kind]}: remove the new one, do not raise the record")
        elif actual[kind] < recorded[kind]:
            out.append(f"{kind}: {actual[kind]} in src/, recorded {recorded[kind]}: lower it in tests/rules/type_ratchet.json")
    return out


class TypeRatchet(unittest.TestCase):
    def test_the_counts_in_src_match_the_record_and_never_rise(self):
        self.assertEqual(problems(count_tree(), json.loads(RECORD.read_text(encoding="utf-8"))), [])

    def test_a_planted_escape_of_each_kind_is_counted(self):
        planted = {
            "any": "from typing import Any\nx: Any = 1\n",
            "pyrefly_ignore": "x = 1  # pyrefly: ignore[bad-assignment]\n",
            "type_ignore": "x = 1  # type: ignore\n",
            "cast": "from typing import cast\nx = cast(int, 1)\n",
        }
        for kind, text in planted.items():
            with self.subTest(kind):
                self.assertEqual(count_source(text)[kind], 1)
                bumped = {k: v + (k == kind) for k, v in count_tree().items()}
                self.assertEqual(len(problems(bumped, count_tree())), 1)

    def test_the_recorded_kinds_are_exactly_the_counted_ones(self):
        self.assertEqual(sorted(json.loads(RECORD.read_text(encoding="utf-8"))), sorted(KINDS))


if __name__ == "__main__":
    unittest.main()
