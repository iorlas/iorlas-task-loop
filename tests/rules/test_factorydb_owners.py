"""Every factory table has exactly one authoritative writer role."""

import sqlite3
import unittest

from taskloop.contracts.factorydb import DDL, OWNERS


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
        self.assertEqual(OWNERS["event"], "engine")
        self.assertEqual(OWNERS["ask"], "engine")
        self.assertEqual(OWNERS["ask_ledger"], "engine")
