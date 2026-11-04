"""Every factory table has exactly one authoritative writer role."""

import ast
import sqlite3
import unittest
from pathlib import Path

from taskloop.contracts.factorydb import DDL, OWNERS

RUN_FILE_READERS = {"taskloop.contracts.runrows"}


def legacy_readers(tree):
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr == "run_manifest"]


class FactoryOwnersTest(unittest.TestCase):
    def test_each_schema_table_has_one_owner_role(self):
        with sqlite3.connect(":memory:") as con:
            con.executescript(DDL)
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(set(OWNERS), tables)
        for table, role in OWNERS.items():
            with self.subTest(table=table):
                self.assertIn(role, {"index", "engine", "loop", "owner"})
        self.assertEqual(OWNERS["lease"], "loop")
        self.assertNotIn("event", OWNERS)  # logs stay files: the DB holds state only
        self.assertEqual(OWNERS["bead"], "index")
        self.assertEqual(OWNERS["ask"], "engine")
        self.assertEqual(OWNERS["ask_ledger"], "engine")
        self.assertEqual(OWNERS["run"], "engine")
        self.assertNotIn("family", OWNERS)

    def test_only_the_legacy_importer_may_name_the_run_manifest_file(self):
        root = Path(__file__).resolve().parents[2] / "src"
        bad = []
        for path in root.rglob("*.py"):
            if "_vendor" in path.parts:
                continue
            module = ".".join(path.relative_to(root).with_suffix("").parts)
            if module not in RUN_FILE_READERS:
                bad.extend(f"{module}:{line}" for line in legacy_readers(ast.parse(path.read_text(encoding="utf-8"))))
        self.assertEqual(bad, [])

    def test_reader_rule_sees_a_planted_file_read(self):
        self.assertEqual(legacy_readers(ast.parse("JsonStore(cfg.run_manifest(run), RunManifest).get()")), [1])
