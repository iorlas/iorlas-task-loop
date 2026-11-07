"""Shared prose matchers retain their wording rules."""
from tltestkit.case import Case

from tlwork.work.matchers import Wording, without_runner, word_set


class WordingTable(Case):
    def rows(self, fn, table):
        for text, want in table:
            assert fn(text) == want

    def test_wording(self):
        self.rows(Wording.about_filing, [("a follow-up bead", True), ("the parser", False)])
        self.rows(Wording.ownerish, [("Owner review of the knob values", True), ("Tune the knob values", False)])
        self.rows(Wording.is_look, [("Only the owner can judge the look.", True), ("the owner decides the price", False)])
        self.rows(Wording.marked_unverified, [("see https://x unverified", True), ("see https://x", False)])


def test_words_and_runner():
    assert word_set("The parser checks résumé foo_bar 123") == {"the", "parser", "résumé", "foo", "bar", "123"}
    assert without_runner("just unity-tests") == "unity-tests"
