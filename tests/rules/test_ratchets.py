"""The three ratchets' pure parts (the change-against-origin/main run is tests/rules/real/test_ratchets_change.py): what each counts in one
file, and the rise and the allowance."""
import ast

from rules import layer_ratchet, needs_ratchet, ratchet_change, temp_ratchet


def tree(text):
    return ast.parse(text)


def test_layer_counts_a_mark_and_a_sleep_outside_real_only():
    src = tree("@real_proc('x')\ndef test_a(): time.sleep(1)\n")
    assert layer_ratchet.file_counts("tests/land/test_x.py", src) == {"real_mark": 1, "sleep": 1}
    assert layer_ratchet.file_counts("tests/land/real/test_x.py", src) == {}
    assert layer_ratchet.file_counts("tests/land/helper.py", src) == {}


def test_temp_counts_tempfile_and_tmp_strings_but_not_the_helper():
    src = tree("import tempfile\nx = tempfile.mkdtemp()\ny = '/tmp/a'\n")
    assert temp_ratchet.file_counts("src/taskloop/app/x.py", src) == {"site": 2}
    assert temp_ratchet.file_counts(temp_ratchet.HOME_FILE, src) == {}
    assert temp_ratchet.file_counts("docs/x.py", src) == {}


def test_needs_keys_are_capability_and_reason():
    src = tree("@needs('git', 'a real rebase conflict')\ndef test_a(): pass\n")
    assert needs_ratchet.file_counts("tests/land/test_x.py", src) == {"git: a real rebase conflict": 1}


def test_a_new_reason_is_said_once_and_in_words():
    assert needs_ratchet.weak_new({"git: old reason": 3}, {"git: old reason": 3, "git: x": 1, "git: a long enough line of words": 2}) == [
        "'git: a long enough line of words' is on 2 tests", "'git: x' is under 5 words"]


def test_rises_names_only_increases_and_a_move_is_net_zero():
    assert ratchet_change.rises({"site": 2}, {"site": 3, "other": 1}) == {"other": 1, "site": 1}
    assert ratchet_change.rises({"site": 2}, {"site": 2}) == {}
    assert ratchet_change.rises({"site": 2}, {"site": 1}) == {}


def test_declared_reads_the_three_spellings():
    src = tree("@needs('long_run', 'a worker waits out its grace')\n@real_proc('r1')\n@te.real_git(why)\ndef test_x(): pass\n")
    assert needs_ratchet.declared(src) == [("long_run", "a worker waits out its grace"), ("process", "r1"), ("git", needs_ratchet.DYNAMIC)]


def test_temp_exceptions_skip_only_the_documented_paths():
    src = tree("x = tempfile.tempdir\n")
    for path, reason in temp_ratchet.EXCEPTIONS.items():
        assert reason
        assert temp_ratchet.file_counts(path, src) == {}
        assert temp_ratchet.file_counts(path + ".other.py", src) == {"site": 1}
