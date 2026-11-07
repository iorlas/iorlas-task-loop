"""Every factory table has exactly one authoritative writer role."""

import ast
import sqlite3
from pathlib import Path

from support.case import Case

from rules.gate_rules import parsed
from taskloop.app.parts import STAGE_PARTS
from tlkernel.dbparts import ddl
from tlkernel.factorydb import OWNERS

RUN_FILE_READERS = {"tlkernel.runrows"}


def legacy_readers(tree):
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr in {"run_manifest", "done_memo", "legacy_done_memo"}]


class FactoryOwnersTest(Case):
    def test_each_schema_table_has_one_owner_role(self):
        with sqlite3.connect(":memory:") as con:
            con.executescript(ddl(STAGE_PARTS))
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(OWNERS) == tables
        for table, role in OWNERS.items():
            with self.subTest(table=table):
                assert role in {"index", "engine", "loop", "owner", "gate"}
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
            tree = parsed(path)[1]  # the gate's cache: one parse per file for every rule
            if module not in RUN_FILE_READERS:
                bad.extend(f"{module}:{line}" for line in legacy_readers(tree))
        assert bad == []

    def test_reader_rule_sees_a_planted_file_read(self):
        assert legacy_readers(ast.parse("JsonStore(cfg.run_manifest(run), RunManifest).get()")) == [1]
        assert legacy_readers(ast.parse("RunFiles(run_dir).done_memo().read_text()")) == [1]
        assert legacy_readers(ast.parse("RunFiles(run_dir).legacy_done_memo().read_text()")) == [1]
