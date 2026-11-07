"""RunKey (tl-3u6.3): the repo's result store, keyed by (check, command, settings, toolchain, tree, base, inputs, selected tests, env).
The land gate asks it, a changed env misses it, and what git cannot see is never served from it (tl-bxk.8.19, tl-7y6.7.11). A moved base
does not invalidate a check that says `inputs_only` (tl-9un.34); two runners writing at once lose nothing (tl-9un.33)."""
import hashlib
import json
import sys
import threading
from pathlib import Path
from unittest import mock

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.check_host import CheckHostCase

from tltestkit import procsim
from tltestkit.checks import ck, res
from tltestkit.narrow import must
from tltestkit.plans import CLEAN, PLAN, WRITE

# isort: split
from support.memstores import fake_stores
from support.spawn import port_git

from taskloop.stores.real import real_stores
from tlgate.cache import KEEP, InputKeys, RunMemo, green_result, is_green, key_digest, plan_digest
from tlkernel import paths, wire
from tlkernel.checks import Check, CheckResult, PassRecord
from tlkernel.ids import CheckId, TreeSha
from tlkernel.runkey import BaseSha, Digest, RunKey

ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}
ST = {"checks": [], "files": []}


class TreeKeys(InputKeys):
    """The file list of the tree is given and no file is gitignored (so no git runs)."""

    def ignored_of(self, c):
        return {}


def memo(env=None, stores=None, tree="t", base="b", files=None, run_id="r1"):
    """A store over `stores` (the repo "repo"), as the runner of `run_id` sees this tree and base; `files` is the tree's file list."""
    keys = TreeKeys(port_git(), "/nonexistent", TreeSha(tree))
    keys.files = files or {}
    return RunMemo(stores or fake_stores(), "repo", keys, BaseSha(base), env or {}, run_id)


class Gate(CheckHostCase):




    def test_gate_green_is_every_key_in_the_memo(self):
        n = Path(self.tmp.name) / "runs"
        eng = self.checks_engine(checks=[{"id": "g", "cmd": procsim.fake("g", procsim.appends(n)), "run": "both"}])
        assert not eng.checker.gate_green()
        eng.run_checks(ST, "s")
        assert eng.checker.gate_green()
        (self.wt / "new.txt").write_text("x")  # another tree: another key
        assert not eng.checker.gate_green()


class Env(CheckHostCase):
    def test_slot_receipts_name_the_location_and_never_match_clean_receipts(self):
        c = Check(id=CheckId("setup"), cmd="true")
        m = memo()
        m.keys.clean = True
        clean_key = must(m.key(c))
        slot_key = must(m.key(c.replace(run_in="slot")))
        assert clean_key != slot_key
        assert slot_key.execution == "slot-v1:host-v1"
        m.keys.clean = False
        assert m.key(c.replace(run_in="slot")) == slot_key

    def test_clean_gate_slot_receipt_hashes_the_slots_ignored_inputs(self):
        c = Check(id=CheckId("setup"), cmd="true", run_in="slot", inputs=["client/**"], inputs_only=True)
        m = memo(files={"client/main.cs": "tracked"})
        m.keys.clean = True
        slot = InputKeys(m.keys.git, m.keys.wt, m.keys.tree)
        slot.files = m.keys.files
        m.slot_keys = slot
        with mock.patch.object(slot, "ignored_of", return_value={"client/setup": "one"}):
            before = must(m.key(c))
        with mock.patch.object(slot, "ignored_of", return_value={"client/setup": "two"}):
            assert m.key(c) != before

    def test_a_changed_check_env_misses_the_memo_even_without_inputs(self):
        n = Path(self.tmp.name) / "runs"
        cmd = procsim.fake("e", procsim.appends(n))
        self.checks_engine(checks=[{"id": "e", "cmd": cmd}]).run_checks(ST, "s")
        self.checks_engine(checks=[{"id": "e", "cmd": cmd}]).run_checks(ST, "s")
        assert n.read_text() == "1"
        self.checks_engine(checks=[{"id": "e", "cmd": cmd, "env": {"A": "1"}}]).run_checks(ST, "s")
        assert n.read_text() == "11"

    def test_a_changed_engine_env_digest_misses(self):
        c = Check(id=CheckId("e"), cmd="e")
        a, b = memo({"TL_SLOT": "one"}), memo({"TL_SLOT": "two"})
        assert a.key(c) != b.key(c)
        assert a.key(c) == memo({"TL_SLOT": "one"}).key(c)
        assert a.key(c) != a.key(c.replace(env={"A": "1"}))
        a.remember(must(a.key(c)), res("e", 0), 1, "/l")
        assert a.has(c)
        assert a.hit(b.key(c)) is None

    def test_the_key_names_tree_base_and_command(self):
        c = Check(id=CheckId("e"), cmd="e")
        assert memo().key(c) != memo(tree="t2").key(c)
        assert memo().key(c) != memo(base="b2").key(c)
        assert memo().key(c) != memo().key(c.replace(cmd="other"))
        assert memo().key(c) == memo().key(c.replace(cmd="e  "))


class MachineState(CheckHostCase):
    """tl-bxk.8.19: a check about a running editor or a log outside git was served by tree hash."""

    def test_a_check_that_may_not_be_cached_has_no_key_so_nothing_can_be_reused(self):
        c = Check(id=CheckId("editor"), cmd="! pgrep unity", cache=False)
        m = memo()
        assert m.key(c) is None
        assert not m.has(c)
        assert m.hit(None) is None

    def test_a_plan_command_reading_an_untracked_file_reruns_after_the_file_changes(self):
        n = Path(self.tmp.name) / "runs"
        log = self.wt / "Editor.log"
        eng = self.checks_engine()
        st = {"checks": ck([procsim.fake("reads-log", procsim.appends(n))]), "files": []}
        log.write_text("closed\n")
        eng.run_checks(st, "s")
        log.write_text("open\n")
        eng.run_checks(st, "s")
        assert n.read_text() == "11"

    def test_a_ref_to_a_registered_check_is_not_a_second_run(self):
        c = Check(id=CheckId("e"), cmd="e")
        m = memo()
        m.remember(must(m.key(c)), res("e", 0), 1, "/l")
        assert m.command_key(c).check == "e"  # a command is its own identity inside a block


FILES = {"client/a.cs": "100644 blob a1", "justfile": "100644 blob j1", "mise.toml": "100644 blob m1"}
ONLY = Check(id=CheckId("u"), cmd="u", inputs=["client/**"], inputs_only=True)


class InputsOnly(Case):
    """tl-9un.34: a moved base does not invalidate a check whose declared inputs are complete."""

    def test_a_moved_base_keeps_an_inputs_only_check_but_not_a_whole_tree_one(self):
        assert memo(files=FILES).key(ONLY) == memo(files=FILES, base="b2", tree="t2").key(ONLY)
        c = ONLY.replace(inputs_only=False)
        assert memo(files=FILES).key(c) != memo(files=FILES, base="b2").key(c)
        whole = Check(id=CheckId("w"), cmd="w")
        assert memo(files=FILES).key(whole) != memo(files=FILES, base="b2").key(whole)

    def test_a_changed_input_env_setting_toolchain_or_selected_set_misses(self):
        k = memo(files=FILES).key(ONLY)
        for what, other in {
            "input": memo(files={**FILES, "client/a.cs": "100644 blob a2"}).key(ONLY),
            "env": memo(files=FILES, env={"A": "1"}).key(ONLY),
            "exclude": memo(files=FILES).key(ONLY.replace(exclude=["client/gen/**"])),
            "inputs_only": memo(files=FILES).key(ONLY.replace(inputs_only=False)),
            "toolchain pin": memo(files={**FILES, "mise.toml": "100644 blob m2"}).key(ONLY),
            "command": memo(files=FILES).key(ONLY.replace(cmd="u2")),
            "selected": memo(files=FILES).key(ONLY.replace(selected=["t::a"])),
        }.items():
            with self.subTest(what):
                assert k != other
        assert k == memo(files={**FILES, "justfile": "100644 blob j2", "other": "x"}).key(ONLY)  # not an input
        assert memo(files=FILES).key(ONLY.replace(selected=["b", "a"])) == memo(files=FILES).key(ONLY.replace(selected=["a", "b"]))

    def test_serving_a_pass_for_a_new_base_writes_a_new_record_for_the_current_tree(self):
        stores = fake_stores()
        old = memo(stores=stores, files=FILES, tree="t1", base="b1", run_id="run-old")
        old.remember(must(old.key(ONLY)), res("u", 0), 1, "/l")
        new = memo(stores=stores, files=FILES, tree="t2", base="b2", run_id="run-new")
        hit = must(new.hit(new.key(ONLY)))
        assert (hit.tree, hit.base, hit.run_id) == ("t1", "b1", "run-old")  # asking changes nothing
        assert not is_green(stores, "repo", CheckId("u"), TreeSha("t2"), BaseSha("b2"))
        new.reuse(hit)
        again = must(new.hit(new.key(ONLY)))
        assert (again.tree, again.base, again.run_id, again.origin) == ("t2", "b2", "run-new", "run-old")
        assert is_green(stores, "repo", CheckId("u"), TreeSha("t2"), BaseSha("b2"))
        assert not is_green(stores, "repo", CheckId("u"), TreeSha("t1"), BaseSha("b1"))


class Store(Case):
    def test_old_keys_default_to_no_plan_output_and_keep_their_digest(self):
        key = must(memo().key(Check(id=CheckId("c"), cmd="c")))
        old = wire.dump(key)
        del old["plan"]
        del old["plan_output"]
        restored = wire.load(RunKey, old)
        assert restored.plan_output == ""
        assert key_digest(restored) == hashlib.sha1(json.dumps(old, sort_keys=True).encode()).hexdigest()
        assert key_digest(key) != key_digest(key.replace(plan_output=Digest("document")))

    def test_plans_with_different_argv_keep_separate_skip_records(self):
        m = memo()
        check = Check(id=CheckId("c"), cmd="c")
        first, second = plan_digest(["plan", "a b", "c"]), plan_digest(["plan", "a", "b c"])
        skip = CheckResult.skipped(check, "first policy").replace(planned=True)
        m.remember(m.planned_key(check, first), skip, 1, "")
        assert not is_green(m.stores, "repo", check.id, m.keys.tree, m.base, second)
        m.remember(m.planned_key(check, second), skip.replace(why="second policy"), 2, "")
        for digest, why in ((first, "first policy"), (second, "second policy")):
            with self.subTest(digest=digest):
                result = must(green_result(m.stores, "repo", check.id, m.keys.tree, m.base, digest))
                assert result.why == why

    def test_other_skip_kinds_and_unverified_results_are_never_green_even_if_stored(self):
        check = Check(id=CheckId("c"), cmd="c")
        m = memo()
        key = m.planned_key(check)
        for stored in (
            CheckResult.skipped(check, "static failed first"),
            CheckResult.skipped(check, "producer p did not run", producer="p"),
            CheckResult.skipped(check, "conflict_fix"),
            CheckResult.cancelled_by(check, "p"),
            CheckResult(id=check.id, cmd=check.cmd, group=check.group, exit=86, status="unverified"),
        ):
            with self.subTest(result=stored):
                m._put(PassRecord(key=key, result=stored, tree=m.keys.tree, base=m.base))
                assert not is_green(m.stores, "repo", check.id, m.keys.tree, m.base)

    def test_planned_skips_are_exact_diff_facts_even_with_inputs_only_or_cache_disabled(self):
        for check in (ONLY, ONLY.replace(cache=False), ONLY.replace(inputs=["missing/**"])):
            with self.subTest(check=check):
                m = memo(files=FILES)
                res = CheckResult.skipped(check, "no change under ui/**").replace(planned=True)
                m.remember(m.planned_key(check), res, 2, "")
                assert is_green(m.stores, "repo", check.id, m.keys.tree, m.base)
                assert not is_green(m.stores, "repo", check.id, TreeSha("t2"), m.base)
                assert not is_green(m.stores, "repo", check.id, m.keys.tree, BaseSha("b2"))
                assert m.hit(m.key(check)) is None
                newer = memo(stores=m.stores, files=FILES, tree="t2", base="b2")
                assert newer.hit(newer.key(check)) is None

    def test_a_pass_keeps_who_made_it_and_where_the_log_is(self):
        m = memo(run_id="run-7")
        c = Check(id=CheckId("e"), cmd="e")
        m.remember(must(m.key(c)), res("e", 0), 3, "/r/checks/00.log")
        rec = must(m.hit(m.key(c)))
        assert (rec.run_id, rec.round, rec.log_abs) == ("run-7", 3, "/r/checks/00.log")
        assert rec.host and rec.ts > 0
        assert "log has expired" in m.cached(c, rec).note  # /r/... is not there

    def test_base_red_is_remembered_for_the_repo_by_any_runner(self):
        stores = fake_stores()
        c = Check(id=CheckId("e"), cmd="e")
        assert memo(stores=stores).base_was_red(c) is None
        memo(stores=stores, run_id="a").set_base_red(c, True)
        assert memo(stores=stores, tree="other", run_id="b").base_was_red(c)
        assert memo(stores=stores, base="b2").base_was_red(c) is None

    def test_only_the_newest_passes_of_a_check_are_kept(self):
        stores = fake_stores()
        c = Check(id=CheckId("e"), cmd="e")
        for i in range(KEEP + 3):
            m = memo(stores=stores, tree=f"t{i}")
            m.remember(must(m.key(c)), res("e", 0), 1, "")
        assert len(stores.results("repo", CheckId("e")).keys()) == KEEP
        last = memo(stores=stores, tree=f"t{KEEP + 2}")
        assert last.has(c)
        assert not memo(stores=stores, tree="t0").has(c)


class Concurrent(Case):
    def test_runners_writing_at_once_lose_no_pass_and_no_base_answer(self):
        with TemporaryDirectory() as d:
            stores = real_stores(paths.ConfigDir(Path(d)))
            checks = [Check(id=CheckId(f"c{i % 4}"), cmd=f"cmd{i}") for i in range(12)]
            go = threading.Barrier(len(checks))
            same = Check(id=CheckId("same"), cmd="same")

            def runner(i: int) -> None:
                m = memo(stores=stores, run_id=f"run-{i}")
                go.wait()
                m.remember(must(m.key(checks[i])), res(checks[i].id, 0), 1, "")
                m.remember(must(m.key(same)), res("same", 0), 1, "")  # all twelve write the one key
                m.set_base_red(checks[i], bool(i % 2))

            threads = [threading.Thread(target=runner, args=(i,)) for i in range(len(checks))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            m = memo(stores=stores)
            assert all(m.has(c) for c in checks)
            assert m.has(same)
            assert [m.base_was_red(c) for c in checks] == [bool(i % 2) for i in range(12)]
