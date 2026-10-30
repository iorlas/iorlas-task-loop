"""The fix round at land: what each kind is called, its goal, and the text the writer is told."""
from types import MappingProxyType
from typing import Final

FIX_WHAT: Final = MappingProxyType({
    "gate": "gate red on the rebased tree", "conflict": "merge conflict with main", "verify": "the check before land found defects"})
FIX_GOAL: Final = MappingProxyType({
    "gate": "make the gate pass on the tree rebased onto the latest base", "conflict": "resolve the merge conflict with the latest base",
    "verify": "fix what the check before land found wrong"})
FIX_TEXT: Final = MappingProxyType({
    "gate": "\nAll stages were accepted, then the gate{} failed on the tree rebased onto the latest base (another task may have "
            "landed first). Fix exactly this, without undoing what the stages built:\n{}\n",
    "conflict": "\nAll stages were accepted, then rebasing onto the latest base hit a merge conflict (another task landed "
                "first){}. The conflict markers are in the files: resolve every one, keeping both changes' intent. Do not run git.\n{}\n",
    "verify": "\nAll stages were accepted; then a check before land found these wrong. Fix exactly this, without undoing what the stages "
              "built:\n{}\n",
})
