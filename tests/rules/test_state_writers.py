"""WRITERS: typed store mutations and raw publications stay with their authoritative module."""

from support.case import Case

from rules.arch_rules import production_trees
from rules.writer_invariants import WRITERS, writer_tree_problems


class StateFilesHaveOneWriter(Case):
    def test_store_mutations_and_raw_publications_belong_to_their_writer(self):
        assert writer_tree_problems(production_trees()) == []

    def test_writer_table_names_existing_modules(self):
        modules = production_trees()
        for store, owners in WRITERS.items():
            assert owners, store
            assert owners <= modules.keys(), store
