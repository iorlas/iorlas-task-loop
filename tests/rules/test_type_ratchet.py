"""The escapes from the type checker in src/ (explicit `Any`, `# pyrefly: ignore`, `# type: ignore`, `cast(`) never rise in a change, and
every match ends in assert_never. No total is stored: tests/rules/real/test_changed_files.py compares the files a change touches with their
merge base, so two parallel releases never write the same file."""
import ast

from support.case import Case

from rules.gate_rules import ROOT
from rules.type_counts import KINDS, change_problems, count_source


def open_matches(text: str) -> list[int]:
    """The lines of `match` statements whose last case is not `case _: assert_never(...)`."""
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Match):
            last = node.cases[-1]
            body = last.body[-1]
            closed = isinstance(last.pattern, ast.MatchAs) and last.pattern.pattern is None and isinstance(body, ast.Expr) \
                and isinstance(body.value, ast.Call) and ast.unparse(body.value.func).endswith("assert_never")
            if not closed:
                out.append(node.lineno)
    return out


class TypeRatchet(Case):
    def test_every_match_in_src_ends_in_assert_never(self):
        bad = [f"{p.relative_to(ROOT)}:{n}" for p in sorted((ROOT / "src").rglob("*.py")) if "_vendor" not in p.parts
               for n in open_matches(p.read_text(encoding="utf-8"))]
        assert bad == []

    def test_an_open_match_is_found(self):
        assert open_matches("match x:\n    case 1:\n        pass\n") == [1]
        assert open_matches("match x:\n    case 1:\n        pass\n    case _:\n        assert_never(x)\n") == []

    def test_a_planted_escape_of_each_kind_is_counted_and_fails_a_change(self):
        planted = {
            "any": "from typing import Any\nx: Any = 1\n",
            "pyrefly_ignore": "x = 1  # pyrefly: ignore[bad-assignment]\n",
            "type_ignore": "x = 1  # type: ignore\n",
            "cast": "from typing import cast\nx = cast(int, 1)\n",
        }
        for kind, text in planted.items():
            with self.subTest(kind):
                assert count_source(text)[kind] == 1
                assert len(change_problems({"m.py": "x = 1\n"}, {"m.py": text})) == 1
                assert change_problems({"m.py": text}, {"m.py": "x = 1\n"}) == []

    def test_moving_an_escape_between_files_is_free_and_a_new_file_pays(self):
        any_x = "from typing import Any\nx: Any = 1\n"
        assert change_problems({"a.py": any_x}, {"a.py": "x = 1\n", "b.py": any_x}) == []
        assert change_problems({}, {"new.py": any_x})
        assert set(KINDS) == {"any", "pyrefly_ignore", "type_ignore", "cast"}
