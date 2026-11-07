"""Enum dispatch tables must cover the vocabulary, including future members."""
import ast

from rules.enumtotal import enum_problems
from rules.gate_rules import ROOT, parsed, py_files
from tltestkit.case import Case


class EnumTotal(Case):
    def problems(self, source, extra=None):
        trees = {"sample": ast.parse(source)}
        trees.update({name: ast.parse(text) for name, text in (extra or {}).items()})
        return enum_problems(trees)

    def test_partial_literal_fails_without_an_annotation(self):
        assert len(self.problems(
            "from enum import Enum\nclass E(Enum):\n A = 1\n B = 2\nTABLE = {E.A: 'a'}\n"
        )) == 1

    def test_total_literal_and_non_enum_dictionary_pass(self):
        assert self.problems(
            "import enum\nclass E(enum.StrEnum):\n A = 'a'\n B = 'b'\n"
            "TABLE = {E.A: 1, E.B: 2}\nOTHER = {'a': 3}\n"
        ) == []

    def test_import_aliases_and_qualified_members_are_resolved(self):
        extra = {"model": "from enum import Enum as Base\nclass E(Base):\n A = 1\n B = 2\n"}
        assert len(self.problems("from model import E as Alias\nTABLE = {Alias.A: 1}\n", extra)) == 1
        assert len(self.problems("import model as m\nTABLE = {m.E.A: 1}\n", extra)) == 1

    def test_same_named_enums_are_not_conflated(self):
        assert self.problems(
            "from model import E\nTABLE = {E.A: 1}\n",
            {"model": "from enum import Enum\nclass E(Enum):\n A = 1\n",
             "other": "from enum import Enum\nclass E(Enum):\n A = 1\n B = 2\n"},
        ) == []

    def test_mixed_keys_and_unpacking_cannot_hide_missing_members(self):
        base = "from enum import Enum\nclass E(Enum):\n A = 1\n B = 2\n"
        for literal in ("{E.A: 1, 'other': 2}", "{E.A: 1, **other}"):
            assert len(self.problems(base + "TABLE = " + literal)) == 1

    def test_only_upper_case_module_or_class_bindings_are_tables(self):
        base = "from enum import Enum\nclass E(Enum):\n A = 1\n B = 2\n"
        for suffix in ("TABLE = {E.A: 1}", "class C:\n TABLE: dict = {E.A: 1}",
                       "if True:\n TABLE = {E.A: 1}", "TABLE = wrap({E.A: 1})"):
            assert len(self.problems(base + suffix)) == 1, suffix
        for suffix in ("TABLE: dict", "table = {E.A: 1}", "def f():\n return send({E.A: 1})",
                       "def f():\n TABLE = {E.A: 1}\n return TABLE",
                       "def f():\n class C:\n  TABLE = {E.A: 1}\n return C"):
            assert self.problems(base + suffix) == [], suffix

    def test_reexported_enum_and_member_aliases_are_resolved(self):
        extra = {"model": "from enum import Enum\nclass E(Enum):\n A = 1\n B = 2\n",
                 "api": "from model import E\n"}
        assert len(self.problems("from api import E\nTABLE = {E.A: 1}", extra)) == 1

    def test_relative_import_from_package_init(self):
        assert len(self.problems("import pkg\nTABLE = {pkg.E.A: 1}", {
            "pkg": "from .model import E", "pkg.model": "from enum import Enum\nclass E(Enum):\n A=1\n B=2",
        })) == 1

    def test_enum_aliases_cover_the_same_member_and_private_members_still_count(self):
        base = "from enum import Enum\nclass E(Enum):\n A = 1\n ALIAS = A\n _PRIVATE = 2\n"
        assert self.problems(base + "TABLE = {E.ALIAS: 1, E._PRIVATE: 2}") == []
        assert len(self.problems(base + "TABLE = {E.A: 1}")) == 1

    def test_enum_ignore_names_are_not_members(self):
        assert self.problems("from enum import Enum\nclass E(Enum):\n"
            " _ignore_ = 'helper'\n helper = 3\n A = 1\nTABLE = {E.A: 1}") == []

    def test_every_production_enum_literal_is_total(self):
        trees = {}
        for path in py_files(ROOT, ("src", "skills", "dev")):
            parts = path.relative_to(ROOT).with_suffix("").parts
            if parts[0] == "src":
                parts = parts[1:]
            if parts[-1] == "__init__":
                parts = parts[:-1]
            trees[".".join(parts)] = parsed(path)[1]
        assert enum_problems(trees) == []
