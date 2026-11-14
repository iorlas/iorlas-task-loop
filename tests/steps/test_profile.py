"""The repository profile: every refusal word of the strict schema, defaults and bounds; the version rule (setup and
checks from the commit, required and target from the target ref) over a semantic port fake; and the Git adapter over
git_porcelain's in-memory fake (a file at a commit, absent, no commit, Git unavailable)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from git_porcelain import GitUnavailable, Repo
from git_porcelain.testing import FakeRemote, FakeRepo

from taskloop.git_views import GitProfileFiles
from taskloop.profile import (
    DEFAULT_SETUP,
    PROFILE_PATH,
    Check,
    LandMode,
    NoCommit,
    NotAFile,
    Profile,
    Refused,
    Resolved,
    Unavailable,
    parse,
    read_profile,
    resolve,
)

CHECK = {"name": "check", "argv": ["just", "check"], "timeout": 1800}
TEST = {"name": "test", "argv": ["just", "test"], "timeout": 60}


def encoded(**table: object) -> bytes:
    return json.dumps(table).encode()


@dataclass
class FakeProfileFiles:
    """Profile bytes per commit name; a name it does not hold names no commit."""

    commits: dict[str, bytes | None] = field(default_factory=dict)
    down: bool = False

    def blob(self, commit: str, path: str) -> bytes | NoCommit | Unavailable | None:
        assert path == PROFILE_PATH
        if self.down:
            return Unavailable("git down")
        return self.commits[commit] if commit in self.commits else NoCommit()


def test_an_empty_object_takes_every_default() -> None:
    assert parse(b"{}") == Profile(DEFAULT_SETUP, (), (), "main")
    assert DEFAULT_SETUP == (("just", "install"),)


def test_land_is_manual_unless_the_profile_says_auto() -> None:
    assert parse(b"{}") == Profile(DEFAULT_SETUP, (), (), "main", LandMode.MANUAL)
    for word, mode in (("manual", LandMode.MANUAL), ("auto", LandMode.AUTO)):
        found = parse(encoded(land=word))
        assert isinstance(found, Profile) and found.land is mode


@pytest.mark.parametrize("value", ["automatic", "", True, 1, None, ["auto"]])
def test_land_names_only_a_known_mode(value: object) -> None:
    found = parse(encoded(land=value))
    assert isinstance(found, Refused) and (found.reason, found.key) == ("bad_value", "land")


def test_a_full_profile_is_typed() -> None:
    data = encoded(setup=[["just", "install"], ["./bootstrap", "x"]], checks=[CHECK, TEST], required=["check"], target="trunk")
    assert parse(data) == Profile(
        (("just", "install"), ("./bootstrap", "x")),
        (Check("check", ("just", "check"), 1800), Check("test", ("just", "test"), 60)),
        ("check",),
        "trunk",
    )


def test_an_empty_setup_list_means_no_setup_and_timeouts_take_their_bounds() -> None:
    low, high = {**CHECK, "timeout": 1}, {**TEST, "timeout": 86400}
    found = parse(encoded(setup=[], checks=[low, high]))
    assert isinstance(found, Profile)
    assert found.setup == ()
    assert [check.timeout for check in found.checks] == [1, 86400]


def check_with(**changes: object) -> dict[str, object]:
    return {**CHECK, **changes}


REFUSALS = [
    ("not_json", b"{", ""),
    ("not_json", b"\xff{}", ""),
    ("not_json", b'{"target": "a", "target": "b"}', ""),
    ("not_json", b'{"checks": [{"name": "a", "argv": ["x"], "timeout": NaN}]}', ""),
    ("not_object", b"[]", ""),
    ("not_object", b'"main"', ""),
    ("unknown_key", encoded(engine={}), "engine"),
    ("unknown_key", b'{"x\\nRequired: (none)": 1}', "'x\\nRequired: (none)'"),
    ("unknown_key", b'{"checks": [{"name": "a", "argv": ["x"], "timeout": 1, "\\u001b[2J": 1}]}', "checks[0].'\\x1b[2J'"),
    ("unknown_key", encoded(checks=[check_with(group="tests")]), "checks[0].group"),
    ("bad_value", encoded(setup="just install"), "setup"),
    ("bad_value", encoded(setup=[[]]), "setup[0]"),
    ("bad_value", encoded(setup=[[""]]), "setup[0][0]"),
    ("bad_value", encoded(setup=[["just", 1]]), "setup[0][1]"),
    ("bad_value", encoded(setup=[["just", "a\0b"]]), "setup[0][1]"),
    ("bad_value", encoded(setup=[["just", ""]]), "setup[0][1]"),
    ("bad_value", encoded(setup=[["  "]]), "setup[0][0]"),
    ("bad_value", encoded(setup=[["\t"]]), "setup[0][0]"),
    ("bad_value", b'{"setup": [["just", "\\ud800"]]}', "setup[0][1]"),
    ("bad_value", encoded(setup=[["just", "x\nRequired: (none)"]]), "setup[0][1]"),
    ("bad_value", encoded(setup=[["just", "a\tb"]]), "setup[0][1]"),
    ("bad_value", encoded(setup=[["just", "\x1b[2J"]]), "setup[0][1]"),
    ("bad_value", encoded(setup=[["just", "\x7f"]]), "setup[0][1]"),
    ("bad_value", encoded(setup=[["just", "\x85"]]), "setup[0][1]"),
    ("bad_value", encoded(checks=[check_with(argv=["x", "a\rb"])]), "checks[0].argv[1]"),
    ("not_json", b'{"checks": [{"name": "a", "argv": ["x"], "timeout": Infinity}]}', ""),
    ("not_json", b'{"target": -Infinity}', ""),
    ("bad_value", encoded(checks={"check": CHECK}), "checks"),
    ("bad_value", encoded(checks=["just check"]), "checks[0]"),
    ("bad_value", encoded(checks=[{"name": "check", "argv": ["just"]}]), "checks[0].timeout"),
    ("bad_value", encoded(checks=[check_with(argv=[])]), "checks[0].argv"),
    ("bad_value", encoded(checks=[check_with(name="")]), "checks[0].name"),
    ("bad_value", encoded(checks=[check_with(name="two words")]), "checks[0].name"),
    ("bad_value", encoded(checks=[check_with(timeout=0)]), "checks[0].timeout"),
    ("bad_value", encoded(checks=[check_with(timeout=86401)]), "checks[0].timeout"),
    ("bad_value", encoded(checks=[check_with(timeout=True)]), "checks[0].timeout"),
    ("bad_value", encoded(checks=[check_with(timeout="60")]), "checks[0].timeout"),
    ("bad_value", encoded(checks=[check_with(timeout=1.5)]), "checks[0].timeout"),
    ("bad_value", encoded(checks=[CHECK], required=["check", "check"]), "required"),
    ("bad_value", encoded(required="check"), "required"),
    ("bad_value", encoded(target=""), "target"),
    ("bad_value", encoded(target=None), "target"),
    *[("bad_value", encoded(target=odd), "target") for odd in (
        "-x", "--upload-pack=y", "a..b", "a//b", "/a", "a/", "a.", "a.lock", "a/b.lock", "a/.b", ".a", "@", "a@{b", "a~1", "a^",
        "a:b", "a?", "a*", "a[b", "a\\b", "a b", "a\nb", "a\x1bb", "a\x7f", "\ud800")],
    *[("bad_value", encoded(checks=[check_with(name=odd)]), "checks[0].name") for odd in (
        ".hidden", "-flag", "a/b", "a:b", "a\nb", "é", "a\ud800", "a b")],
    ("bad_value", encoded(checks=[CHECK], required=["-check"]), "required[0]"),
    ("too_large", b" " * (64 * 1024 + 1), ""),
    ("too_large", encoded(checks=[check_with(name=f"c{index}") for index in range(33)]), "checks"),
    ("too_large", encoded(setup=[["just"]] * 33), "setup"),
    ("too_large", encoded(checks=[check_with(argv=["x"] * 65)]), "checks[0].argv"),
    ("too_large", encoded(checks=[check_with(argv=["x", "a" * 4097])]), "checks[0].argv[1]"),
    ("too_large", encoded(checks=[check_with(name="n" * 65)]), "checks[0].name"),
    ("too_large", encoded(target="b" * 256), "target"),
    ("duplicate_check", encoded(checks=[CHECK, check_with(argv=["other"])]), "checks"),
]


@pytest.mark.parametrize("reason, data, key", REFUSALS, ids=[f"{reason}:{key or index}" for index, (reason, _d, key) in
                                                            enumerate(REFUSALS)])
def test_each_refusal_has_its_fixed_word_and_key(reason: str, data: bytes, key: str) -> None:
    found = parse(data)
    assert isinstance(found, Refused)
    assert (found.reason, found.key) == (reason, key)
    assert found.detail


def test_a_refusal_never_carries_a_raw_control_character() -> None:
    found = parse(b'{"a\\nb": 1, "c\\u001bd": 2}')
    assert isinstance(found, Refused)
    assert found.detail == "Unknown keys: 'a\\nb', 'c\\x1bd'"
    assert all(each.isprintable() for each in (found.key, found.detail))
    long = parse(json.dumps({"k" * 5000: 1}).encode())
    assert isinstance(long, Refused)
    assert len(long.key) < 100


def test_the_bounds_themselves_are_accepted() -> None:
    data = encoded(setup=[["just"]] * 32, checks=[check_with(name="n" * 64, argv=["x"] * 63 + ["a" * 4096])], target="b" * 255)
    assert isinstance(parse(data), Profile)
    assert isinstance(parse(encoded(checks=[check_with(name="a.b_C-9")], target="feature/x-1_y.z", required=["a.b_C-9"])), Profile)
    assert isinstance(parse(b" " * (64 * 1024 - 2) + b"{}"), Profile)


def test_read_profile_refuses_a_commit_without_the_file_and_a_name_that_is_no_commit() -> None:
    files = FakeProfileFiles({"x": None})
    assert read_profile(files, "x") == Refused("missing", detail="No .task-loop.json at x")
    assert read_profile(files, "nope") == Refused("no_commit", detail="nope names no commit")
    assert read_profile(FakeProfileFiles(down=True), "x") == Unavailable("git down")


MAIN = encoded(setup=[["main-setup"]], checks=[CHECK, TEST], required=["check", "test"], target="main")


def test_commands_come_from_the_commit_and_required_and_target_from_the_target_ref() -> None:
    branch = encoded(setup=[["task-setup"]], checks=[check_with(argv=["edited"]), TEST, check_with(name="extra")],
                     required=[], target="elsewhere")
    found = resolve(FakeProfileFiles({"X": branch, "main": MAIN}), "X", "main")
    assert found == Resolved(
        (("task-setup",),),
        (Check("check", ("edited",), 1800), Check("test", ("just", "test"), 60), Check("extra", ("just", "check"), 1800)),
        ("check", "test"),
        "main",
    )


def test_the_setup_default_applies_only_to_an_existing_profile_without_the_key() -> None:
    found = resolve(FakeProfileFiles({"X": encoded(checks=[CHECK, TEST]), "main": MAIN}), "X", "main")
    assert isinstance(found, Resolved)
    assert found.setup == DEFAULT_SETUP
    missing = resolve(FakeProfileFiles({"X": None, "main": MAIN}), "X", "main")
    assert missing == Refused("missing", detail="No .task-loop.json at X", side="commit")


def test_a_commit_cannot_drop_a_required_check() -> None:
    found = resolve(FakeProfileFiles({"X": encoded(checks=[CHECK]), "main": MAIN}), "X", "main")
    assert isinstance(found, Refused)
    assert (found.reason, found.side, found.key) == ("required_undefined", "commit", "required")
    assert found.detail == "Required but not defined at X: test"


def test_the_targets_required_names_must_be_its_own_checks_first() -> None:
    broken_main = encoded(checks=[CHECK], required=["check", "lint"])
    found = resolve(FakeProfileFiles({"X": encoded(checks=[CHECK]), "main": broken_main}), "X", "main")
    assert isinstance(found, Refused)
    assert (found.reason, found.side) == ("required_undefined", "target")


@pytest.mark.parametrize("commits, side, reason", [
    ({"X": MAIN}, "target", "no_commit"),
    ({"X": MAIN, "main": None}, "target", "missing"),
    ({"X": b"[]", "main": MAIN}, "commit", "not_object"),
    ({"main": MAIN}, "commit", "no_commit"),
])
def test_a_refusal_names_whose_profile_it_is(commits: dict[str, bytes | None], side: str, reason: str) -> None:
    found = resolve(FakeProfileFiles(commits), "X", "main")
    assert isinstance(found, Refused)
    assert (found.side, found.reason) == (side, reason)


def test_git_unavailable_is_no_verdict() -> None:
    assert resolve(FakeProfileFiles(down=True), "X", "main") == Unavailable("git down")


@pytest.fixture
def clone(tmp_path: Path) -> tuple[FakeRepo, str, str]:
    remote = FakeRemote("https://example.invalid/repo.git")
    without = remote.advance("main", {"README": "one"})
    with_profile = remote.advance("main", {PROFILE_PATH: MAIN.decode()})
    return FakeRepo.clone(remote, tmp_path / "main"), without, with_profile


def test_the_adapter_reads_the_file_at_a_commit(clone: tuple[FakeRepo, str, str]) -> None:
    repo, without, with_profile = clone

    def views(_path: Path, /, *, git_dir: Path | None = None) -> Repo:
        return repo

    files = GitProfileFiles(repo.path, views)
    assert files.blob(with_profile, PROFILE_PATH) == MAIN
    assert files.blob(without, PROFILE_PATH) is None
    assert files.blob("0" * 40, PROFILE_PATH) == NoCommit()
    assert files.blob("-x", PROFILE_PATH) == NoCommit()


def test_a_symlink_or_submodule_profile_is_refused_not_unavailable() -> None:
    class Moded:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        def blob(self, commit: str, path: str) -> NotAFile:
            return NotAFile(self.mode)

    assert read_profile(Moded("160000"), "X") == Refused("not_a_file", detail=".task-loop.json at X is not a regular file (mode 160000)")
    assert resolve(Moded("120000"), "X", "main") == Refused(
        "not_a_file", detail=".task-loop.json at X is not a regular file (mode 120000)", side="commit")


def test_the_adapter_reports_git_failure_as_unavailable(tmp_path: Path) -> None:
    def broken(_path: Path, /, *, git_dir: Path | None = None) -> Repo:
        raise GitUnavailable("Malformed GIT_CONFIG_COUNT", hint="git_config")

    assert GitProfileFiles(tmp_path, broken).blob("HEAD", PROFILE_PATH) == Unavailable("Malformed GIT_CONFIG_COUNT")
