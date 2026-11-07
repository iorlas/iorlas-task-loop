"""Ignore-rule anchoring for the helper moved into the kernel."""
from tlkernel.treehash import ignore_rules


def test_ignore_rules_anchor_nested_patterns():
    assert ignore_rules("base", {
        ".gitignore": ["# comment", "", "*.log", "!keep.log"],
        "sub/.gitignore": ["/root.txt", "dir/file", "*.tmp", "!keep.tmp"],
    }) == [
        "*.log", "!keep.log", "/sub/root.txt", "/sub/dir/file",
        "/sub/**/*.tmp", "!/sub/**/keep.tmp",
    ]
