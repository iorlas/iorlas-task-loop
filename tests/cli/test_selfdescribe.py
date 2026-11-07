"""The injected command vocabulary covers the real CLI dispatch table."""
import re

from support.tlmain import tl

from taskloop.domain import selfdescribe
from tltestkit.case import Case

# The git pre-push hook's and the artifact_add tool server's internal protocols are not session commands, nor is the owner's one-time
# `tl layout migrate`, which runs with every loop stopped.
EXCLUDED = {"judge-push", "artifact-server", "layout"}


class CommandCoverage(Case):
    def test_every_named_verb_exists_and_every_public_verb_is_described(self):
        named = set(re.findall(r"\btl ([a-z][a-z-]*)", selfdescribe.text()))
        assert named <= set(tl.VERBS)
        assert named | EXCLUDED == set(tl.VERBS)
        assert not named & EXCLUDED
