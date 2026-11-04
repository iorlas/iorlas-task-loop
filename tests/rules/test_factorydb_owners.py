"""Every factory table has exactly one authoritative writer role."""

import ast
import sqlite3
from pathlib import Path

from support.case import Case

from taskloop.contracts.factorydb import DDL, OWNERS

RUN_FILE_READERS = {"taskloop.contracts.runrows"}
RECEIPT_FILE_READERS = {"taskloop.contracts.receiptrows"}
ASK_FILE_READERS = {"taskloop.contracts.askrows"}


def legacy_readers(tree):
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr in {"run_manifest", "done_memo", "legacy_done_memo"}]


def receipt_file_readers(tree):
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr in {"result", "base_red"}
            and isinstance(n.value, ast.Name) and n.value.id == "cfg"]


def ask_file_readers(tree):
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr in {"ask", "ask_beads", "ask_ledger", "asks_dir"}
            and ((isinstance(n.value, ast.Name) and n.value.id == "cfg")
                 or (isinstance(n.value, ast.Attribute) and n.value.attr == "cfg"))]


class FactoryOwnersTest(Case):
    def test_each_schema_table_has_one_owner_role(self):
        with sqlite3.connect(":memory:") as con:
            con.executescript(DDL)
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(OWNERS) == tables
        for table, role in OWNERS.items():
            with self.subTest(table=table):
                assert role in {"index", "engine", "loop", "owner"}
        assert OWNERS["lease"] == "loop"
        assert "event" not in OWNERS  # logs stay files: the DB holds state only
        assert OWNERS["bead"] == "index"
        assert OWNERS["ask"] == "engine"
        assert OWNERS["ask_ledger"] == "engine"
        assert OWNERS["run"] == "engine"
        assert "family" not in OWNERS

    def test_only_the_legacy_importer_may_name_the_run_manifest_file(self):
        root = Path(__file__).resolve().parents[2] / "src"
        bad = []
        for path in root.rglob("*.py"):
            if "_vendor" in path.parts:
                continue
            module = ".".join(path.relative_to(root).with_suffix("").parts)
            if module not in RUN_FILE_READERS:
                bad.extend(f"{module}:{line}" for line in legacy_readers(ast.parse(path.read_text(encoding="utf-8"))))
            if module not in RECEIPT_FILE_READERS:
                bad.extend(f"{module}:{line}" for line in receipt_file_readers(ast.parse(path.read_text(encoding="utf-8"))))
            if module not in ASK_FILE_READERS and module != "taskloop.contracts.paths":
                bad.extend(f"{module}:{line}" for line in ask_file_readers(ast.parse(path.read_text(encoding="utf-8"))))
        assert bad == []

    def test_reader_rule_sees_a_planted_file_read(self):
        assert legacy_readers(ast.parse("JsonStore(cfg.run_manifest(run), RunManifest).get()")) == [1]
        assert legacy_readers(ast.parse("RunFiles(run_dir).done_memo().read_text()")) == [1]
        assert legacy_readers(ast.parse("RunFiles(run_dir).legacy_done_memo().read_text()")) == [1]
        assert receipt_file_readers(ast.parse("JsonStore(cfg.result(repo, check, digest), PassRecord).get()")) == [1]
        assert receipt_file_readers(ast.parse("cfg.base_red(repo, digest).read_bytes()")) == [1]
        assert receipt_file_readers(ast.parse("stores.base_red(repo).of(digest).get()")) == []
        assert ask_file_readers(ast.parse("JsonStore(cfg.ask(bead), Ask).read()")) == [1]
        assert ask_file_readers(ast.parse("cfg.ask_beads()")) == [1]
        assert ask_file_readers(ast.parse("self.cfg.ask_ledger().read_text()")) == [1]
        assert ask_file_readers(ast.parse("AskStore.at(cfg).all()")) == []
