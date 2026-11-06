"""engine.writer_family and the label writer-family:<f> (domain/lanes/pin.py): who is pinned, which roles carry the flag."""
import sys
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import delegate
from taskloop.domain.lanes import pin, says
from taskloop.domain.lanes import policy as lp


class Pin(Case):
    def test_the_profile_pins_and_a_bead_label_overrides_it(self):
        assert pin.families(["openai"], ["x"]) == ["openai"]
        assert pin.families(["openai"], ["writer-family:xai"]) == ["xai"]
        assert pin.families([], ["writer-family:OpenAI", "writer-family:xai"]) == ["openai", "xai"]
        assert pin.families([], ["writer-family:"]) == []
        assert pin.families([], []) == []

    def test_only_the_worker_role_carries_the_pin(self):
        assert pin.for_role("worker", ["openai"]) == ["openai"]
        assert [pin.for_role(r, ["openai"]) for r in ("planner", "reviewer")] == [[], []]

    def test_the_flag_is_one_per_family_and_absent_without_a_pin(self):
        base = {"role": "worker", "brief_path": "b", "cwd": "/w", "schema_path": "s"}
        argv = delegate.RunRequest(**base, only_family=["openai", "xai"]).to_argv("py", "r")
        assert [argv[i + 1] for i, x in enumerate(argv) if x == "--only-family"] == ["openai", "xai"]
        assert "--only-family" not in delegate.RunRequest(**base).to_argv("py", "r")

    def test_the_words_name_the_pin_the_reason_and_that_no_other_family_runs(self):
        why = pin.stop_why("write", ["openai"], "only_family_unready", "codex out until 21:00")
        assert why.startswith("paused: no ready lane of the pinned writer family (openai) for write (only_family_unready)")
        assert "no other family is used" in why
        assert "openai" in pin.describe(["openai"])
        assert "none" in pin.describe([])

    def test_unenforced_stop_names_the_harness_recipes_and_fix_even_without_a_pin(self):
        reason = delegate.REASON_ENGINE_ONLY_UNENFORCED
        assert reason in pin.STOP_REASONS
        stop = lp.Stop("machine", "needs_owner", reason=reason, fix="use advisory or another harness")
        action = lp.decide(stop, lp.Ctx(now=1, node="write"))
        assert isinstance(action, lp.Yield)
        assert isinstance(action, lp.Yield)
        for why in (pin.stop_why("write", ["openai"], reason, "CODEX: just check", stop.fix),
                    says.stop_why("write", action.kind, stop, "CODEX: just check", now=0)):
            assert "paused: the writer's harness cannot deny the engine-only recipes:" in why
            assert "CODEX: just check" in why
            assert stop.fix in why
            assert reason in why


class SecondFamily(Case):
    """engine.second_writer_family: one light bead in ten is written by a second family, chosen by the bead id alone (tl-7i9k.17)."""

    def test_the_share_is_one_in_ten_and_the_same_for_the_same_id(self):
        ids = [f"tl-{n:04x}" for n in range(2000)]
        hits = [i for i in ids if pin.warm_second(i, True, "claude", [], ["openai"])]
        assert 0.08 * len(ids) <= len(hits) <= 0.12 * len(ids)
        assert hits == [i for i in ids if pin.warm_second(i, True, "claude", [], ["openai"])]

    def test_a_chosen_bead_is_pinned_to_the_second_family_alone(self):
        chosen = next(i for i in (f"tl-{n}" for n in range(500)) if pin.warm_second(i, True, "claude", [], ["openai"]))
        assert pin.warm_second(chosen, True, "claude", [], ["openai"]) == ["claude"]

    def test_nothing_moves_when_off_heavy_or_labelled(self):
        chosen = next(i for i in (f"tl-{n}" for n in range(500)) if pin.warm_second(i, True, "claude", [], ["openai"]))
        assert pin.warm_second(chosen, True, "", [], ["openai"]) == []  # unset: dark
        assert pin.warm_second(chosen, False, "claude", [], ["openai"]) == []  # a heavy plan
        assert pin.warm_second(chosen, True, "claude", ["writer-family:xai"], ["openai"]) == []  # the bead pins its own family
        assert pin.warm_second(chosen, True, "claude", [], ["claude"]) == []  # already the pinned family

    def test_light_is_one_stage_and_no_host_grant(self):
        assert pin.is_light(1, False)
        assert not pin.is_light(2, False)
        assert not pin.is_light(1, True)
        assert not pin.is_light(0, False)  # no plan yet: not known to be light

    def test_the_effective_pin_is_the_second_family_for_a_chosen_bead_else_the_usual_one(self):
        chosen = next(i for i in (f"tl-{n}" for n in range(500)) if pin.warm_second(i, True, "claude", [], ["openai"]))
        other = next(i for i in (f"tl-{n}" for n in range(500)) if not pin.warm_second(i, True, "claude", [], ["openai"]))
        assert pin.families(["openai"], [], second=pin.Warm("claude", chosen, True)) == ["claude"]
        assert pin.families(["openai"], [], second=pin.Warm("claude", other, True)) == ["openai"]
        assert pin.families(["openai"], []) == ["openai"]

    def test_the_stop_words_say_it_is_the_warm_second_family_and_the_bead_waits(self):
        why = pin.stop_why("write", ["claude"], "only_family_unready", "claude out", warm="claude")
        assert "second writer family (claude)" in why
        assert "no other family is used" in why
