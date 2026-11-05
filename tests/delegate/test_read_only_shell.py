"""delegate-xzx: the read-only filter reads shell words: a quoted separator is part of the word, and for/while loops over reads pass."""

from delegate.domain.policy.shell import read_only_problem

import hermetic  # noqa: F401  (a home of its own for every test)

PASS = (
    "sed -n '1466p;854p;12p' f",
    'grep -n "" f | grep -E "a|b"',
    'rg -n "a\\|b" src',
    "for f in a b; do cat $f; done",
    'for f in a.txt b.txt\ndo\n  wc -l "$f"\ndone',
    "while true; do head -1 f; done",
    "cd x; grep | head",
    "cd x && grep -n 'a;b' f | head -5",
    "echo 'a && b' | cut -d'|' -f1",
    "git log --format='%h|%s' -3",
)
BLOCK = (
    "sed -i 's/a;b/c/' f",
    "echo 'a;b' > f",
    "cat $(ls)",
    "rm x",
    "echo 'a;b'; rm x",
    "grep 'a|b' f | tee out",
    "for f in a b; do rm $f; done",
    "for f in a b; do cat $f > $f.bak; done",
    "while true; do touch x; done",
    "for f in $(ls); do cat $f; done",
    "grep 'x' f; sed -i s/a/b/ f",
    "echo 'unterminated",
)


class ReadOnlyShellTest:
    def test_reads_with_quoted_separators_and_loops_pass(self):
        for c in PASS:
            assert read_only_problem(c) is None, c

    def test_writes_substitutions_and_non_reads_still_block(self):
        for c in BLOCK:
            assert read_only_problem(c) is not None, c
