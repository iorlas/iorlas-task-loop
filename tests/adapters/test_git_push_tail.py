"""Failed pushes preserve rejection details while other git errors keep their existing diagnostics."""
import support.paths  # noqa: F401
from support.case import Case

from taskloop.adapters.git_base import classify, error_line, push_error_line
from taskloop.contracts.slots import BranchPinned, DirtyTree, IndexLocked, RefRace

TRAILER = "error: failed to push some refs to 'origin'"


class PushTail(Case):
    def test_fetch_first_rejection_and_hints_replace_the_trailer(self):
        rejection = "! [rejected] main -> main (fetch first)"
        hint = "hint: Updates were rejected because the remote contains work"
        stderr = f"To origin\n {rejection}\n{TRAILER}\n{hint}\n"
        assert push_error_line(stderr) == rejection + " | " + hint
        assert error_line(stderr) == TRAILER
        assert classify(stderr).tail == TRAILER

    def test_remote_hook_output_and_rejection_are_preserved_in_order(self):
        lines = ["remote: GH013: Repository rule violations found",
                 "remote: pre-push check: required approval missing",
                 "! [remote rejected] main -> main (pre-receive hook declined)"]
        assert push_error_line("\n".join([*lines, TRAILER])) == " | ".join(lines)

    def test_unmatched_output_uses_whole_lines_without_the_generic_footer(self):
        network = "ssh: connect to host example.invalid port 22: Connection timed out"
        for stderr, expected in ((network + "\n" + TRAILER, network), (network, network),
                                 ("progress\n" + TRAILER, "progress"), ("progress\nunknown failure", "progress | unknown failure"),
                                 ("", "no message from git"), ("fatal: network unavailable\n" + TRAILER,
                                                              "fatal: network unavailable")):
            with self.subTest(stderr=stderr):
                assert push_error_line(stderr) == expected

    def test_long_diagnostic_lines_are_never_cut(self):
        line = "remote: " + "x" * 500
        assert push_error_line(line + "\n" + TRAILER) == line

    def test_refusal_in_the_middle_of_500_lines_is_preserved(self):
        lines = [f"progress {n}" for n in range(500)]
        refusal = "gate: refusing the push: run just check"
        lines.insert(250, refusal)
        assert push_error_line("\n".join([*lines, TRAILER])) == refusal

    def test_at_most_eight_matching_or_fallback_lines_are_selected(self):
        for prefix in ("remote:", "progress"):
            lines = [f"{prefix} {n}" for n in range(20)]
            expected = lines[:8] if prefix == "remote:" else lines[-8:]
            assert push_error_line("\n".join([*lines, TRAILER])) == " | ".join(expected)

    def test_all_hook_diagnostic_markers_are_recognized(self):
        for line in ("Refused by policy", "Rejected by hook", "error: checks failed", "pre-push failed",
                     "gate: red", "remote: denied", "! denied", "hint: run checks"):
            with self.subTest(line=line):
                assert push_error_line("progress\n" + line + "\n" + TRAILER) == line

    def test_classification_reads_the_full_stderr_even_beyond_the_tail_limit(self):
        prefix = "remote: " + "x" * 500 + "\n"
        cases = (("error: cannot lock ref 'refs/heads/main'", RefRace),
                 ("fatal: Unable to create '/repo/index.lock'", IndexLocked),
                 ("error: local changes would be overwritten", DirtyTree),
                 ("fatal: 'main' is already used by worktree at '/other'", BranchPinned))
        for diagnostic, kind in cases:
            with self.subTest(kind=kind):
                error = classify(prefix + diagnostic + "\n" + TRAILER, push=True)
                assert isinstance(error, kind)
                assert prefix.strip() in error.tail
                assert TRAILER not in error.tail
                if isinstance(error, BranchPinned):
                    assert error.where == "/other"
