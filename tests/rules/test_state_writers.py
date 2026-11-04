"""WRITERS: typed store mutations and raw publications stay with their authoritative module."""
import unittest

from rules.arch_ratchets import production_trees
from rules.writer_invariants import WRITERS, writer_tree_problems


class StateFilesHaveOneWriter(unittest.TestCase):
    def test_store_mutations_and_raw_publications_belong_to_their_writer(self):
        self.assertEqual(writer_tree_problems(production_trees()), [])

    def test_writer_table_names_existing_modules(self):
        modules = production_trees()
        for store, owners in WRITERS.items():
            self.assertTrue(owners, store)
            self.assertLessEqual(owners, modules.keys(), store)
