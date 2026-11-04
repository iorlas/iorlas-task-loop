"""The injected command vocabulary covers the real CLI dispatch table."""
import re
import unittest

from support.tlmain import tl

from taskloop.domain import selfdescribe

# The git pre-push hook's internal protocol is not a session command.
EXCLUDED = {"judge-push"}


class CommandCoverage(unittest.TestCase):
    def test_every_named_verb_exists_and_every_public_verb_is_described(self):
        named = set(re.findall(r"\btl ([a-z][a-z-]*)", selfdescribe.text()))
        self.assertLessEqual(named, set(tl.VERBS))
        self.assertEqual(named | EXCLUDED, set(tl.VERBS))
        self.assertFalse(named & EXCLUDED)
