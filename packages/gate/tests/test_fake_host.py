"""Gate receipts and runner rounds work with only package ports and scripted observations."""
from pathlib import Path

import pytest
from tlkernel.checks import Check, CheckResult
from tlkernel.config import CheckSpec, EngineConfig
from tlkernel.env import Env
from tlkernel.gitfacts import TreeEntry
from tlkernel.gitport import GateGit
from tlkernel.ids import CheckId, TreeSha
from tlkernel.log import CheckStart, CmdEnd, CmdStart
from tlkernel.runkey import BaseSha

from tlgate import authorization
from tlgate.cache import InputKeys, RunMemo
from tlgate.domain import inputs
from tlgate.host import CheckHost, CheckStuck
from tlgate.runner import Checker
from tlgate.testing import FakeGateHost, FakeGateStores, ScriptedGateGit


def keys(digest="one", tree="tree", pins=(), pin_digest="pin"):
    git = ScriptedGateGit(ls_tree=(TreeEntry(mode="100644", kind="blob", oid=digest, path="src/a.py"),
                                  TreeEntry(mode="100644", kind="blob", oid=pin_digest, path="pins.txt")), ls_files=())
    return InputKeys(git, "repo", TreeSha(tree), pins=pins)


def check():
    return Check(id=CheckId("test"), cmd="test", inputs=["src/**"], cache=True)


def memo(stores, digest="one", tree="tree"):
    return RunMemo(stores, "repo", keys(digest, tree), BaseSha("base"), {})


def test_scripted_git_prefers_longest_key_and_records_sequences():
    fake = ScriptedGateGit(rev_parse="fallback", rev_parse__HEAD=["a", "b"])
    git: GateGit = fake
    assert [git.rev_parse("repo", "HEAD"), git.rev_parse("repo", "HEAD"), git.rev_parse("repo", "other")] == ["a", "b", "fallback"]
    assert fake.calls == [("rev_parse", "HEAD"), ("rev_parse", "HEAD"), ("rev_parse", "other")]


def test_unscripted_git_fails_by_name():
    with pytest.raises(AssertionError, match="git merge_base HEAD base: no reply scripted"):
        ScriptedGateGit().merge_base("repo", "HEAD", "base")
    with pytest.raises(AssertionError, match="git rev_parse HEAD: no reply scripted"):
        ScriptedGateGit(rev_parse=[]).rev_parse("repo", "HEAD")


def test_identical_inputs_have_identical_keys():
    stores = FakeGateStores()
    assert memo(stores).key(check()) == memo(stores).key(check())


def test_changed_input_digest_changes_key():
    stores = FakeGateStores()
    assert memo(stores).key(check()) != memo(stores, "two").key(check())


def test_inputs_only_ignore_unrelated_tree_and_base():
    stores = FakeGateStores()
    c = check().replace(inputs_only=True)
    a, b = memo(stores), memo(stores, tree="other")
    b.base = BaseSha("other")
    assert a.key(c) == b.key(c)


def test_custom_pin_changes_toolchain_even_for_inputs_only():
    c = check().replace(inputs_only=True)
    assert keys(pins=("pins.txt",)).toolchain("host") != keys(pins=("pins.txt",), pin_digest="changed").toolchain("host")
    assert keys().key(c) == keys(tree="other").key(c)


def test_tracked_listing_is_read_once():
    k = keys()
    k.key(check())
    k.toolchain("host")
    assert isinstance(k.git, ScriptedGateGit)
    assert sum(c[0] == "ls_tree" for c in k.git.calls) == 1


def test_pass_is_reused_but_changed_inputs_need_a_run():
    stores = FakeGateStores()
    first = memo(stores)
    c = check()
    key = first.key(c)
    assert key is not None
    result = CheckResult(id=c.id, cmd=c.cmd, group=c.group, exit=0, status="passed")
    first.remember(key, result, 1, "")
    second = memo(stores)
    hit = second.hit(second.key(c))
    assert hit is not None and second.cached(c, hit).cached
    assert memo(stores, "two").hit(memo(stores, "two").key(c)) is None


def host(tmp_path, commands, red=False):
    command = commands.fake("gate-answer", commands.exits(1 if red else 0, "red" if red else "green"))
    cfg = EngineConfig(checks=[CheckSpec(id=CheckId("answer"), argv=[command], run="both")], base_red=False, max_same_red=2)
    git = ScriptedGateGit(common_dir="", rev_parse="", merge_base="", branch="", ls_tree=())
    return FakeGateHost(tmp_path, cfg, git), command


def test_runner_reuses_green_and_reruns_changed_tree(tmp_path: Path, commands):
    fake, command = host(tmp_path, commands)
    port: CheckHost = fake
    runner = Checker(port)
    first, second = runner.run([], "first"), runner.run([], "second")
    fake.checkout.tree = TreeSha("changed")
    third = runner.run([], "third")
    assert [first.round, second.round, third.round] == [1, 2, 3]
    assert [first.hits, second.hits, third.hits] == [0, 1, 0]
    assert commands.ran(command) == 2
    assert [r.round for r in fake.log.records if isinstance(r, CheckStart)] == [1, 2, 3]


def test_runner_reports_red_and_green_in_one_round(tmp_path: Path, commands):
    fake, green = host(tmp_path, commands)
    red = commands.fake("gate-red", commands.exits(1, "broken"))
    fake.cfg = fake.cfg.replace(checks=[*fake.cfg.checks, CheckSpec(id=CheckId("red"), argv=[red])])
    run = Checker(fake).run([], "mixed")
    assert [(r.id, r.exit) for r in run.results] == [("answer", 0), ("red", 1)]
    assert run.round == 1 and commands.ran(green) == commands.ran(red) == 1
    assert fake.stores.check_run(fake.run_dir.name, 1).get() == run


def test_identical_red_rounds_raise_stuck(tmp_path: Path, commands):
    fake, command = host(tmp_path, commands, red=True)
    runner = Checker(fake)
    assert runner.run([], "first").failed
    with pytest.raises(CheckStuck) as caught:
        runner.run([], "second")
    assert caught.value.rounds == 2 and commands.ran(command) == 2


def test_shell_records_commands_and_saves_output(tmp_path: Path, commands):
    fake, command = host(tmp_path, commands)
    saved = tmp_path / "output"
    assert fake.sh([command], save=saved) == (0, "green")
    assert saved.read_text() == "green\n"
    assert isinstance(fake.log.records[0], CmdStart)
    assert isinstance(fake.log.records[1], CmdEnd)


def test_authorization_requires_exact_receipt(tmp_path: Path):
    cfg = EngineConfig(checks=[CheckSpec(id=CheckId("test"), argv=["test"], run="gate")])
    git, stores, env = ScriptedGateGit(common_dir="", ls_tree=()), FakeGateStores(), Env()
    tree, base = TreeSha("tree"), BaseSha("base")
    m = authorization.memo_for(stores, git, str(tmp_path), cfg, tree, base, env)
    c = m.checks[CheckId("test")]
    key = m.key(c)
    assert key is not None
    assert authorization.results(stores, git, str(tmp_path), cfg, tree, base, env) == {"test": None}
    assert "no green run" in authorization.explain(stores, git, str(tmp_path), cfg, tree, base, env, [c.id])[c.id]
    result = CheckResult(id=c.id, cmd=c.cmd, group=c.group, exit=0, status="passed")
    m.remember(key, result, 1, "")
    assert authorization.results(stores, git, str(tmp_path), cfg, tree, base, env)[c.id] == result
    changed = cfg.replace(checks=[cfg.checks[0].replace(argv=["different"])])
    assert authorization.results(stores, git, str(tmp_path), changed, tree, base, env)[c.id] is None
    assert "cmd differs" in authorization.explain(stores, git, str(tmp_path), changed, tree, base, env, [c.id])[c.id]


def test_input_sets_exclude_paths_and_detect_dead_globs():
    paths = ["src/a.py", "src/generated/x.py", "docs/a.md"]
    assert inputs.matching(paths, ["src/**"], ["src/generated/**"]) == ["src/a.py"]
    assert inputs.dead_globs(paths, ["src/**", "missing/**"]) == ["missing/**"]
    assert not inputs.touched(check(), ["docs/a.md"])
    assert inputs.touched(check(), ["src/a.py"])


def test_spawner_captures_text_stdin_and_bytes(tmp_path: Path, commands):
    fake, command = host(tmp_path, commands)
    assert fake.spawner.run([command], input="paths\0").out == "green"
    assert fake.spawner.run_bytes([command]).out == b"green"
    assert commands.ran(command) == 2
