"""tl-bxk.10.28: a verify item never parks a bead unless it is a real owner decision. The fixtures are the five asks that
parked lifesim on 2026-10-22 (~/.config/task-loop/asks/lifesim-*.json), each item with the kind the engine now routes by."""
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as T
from support.builders import make_engine, plan_of
from support.engine_case import BEAD, CLEAN, PLAN, WRITE, engine, verdict

from taskloop.contracts import answers
from taskloop.domain.prompts import common as cp
from taskloop.domain.prompts import verify as vp

# lifesim-yxbb.7 and lifesim-fld.25.16: the engine files follow-up beads after the land
YXBB_7 = {"what": "Follow-up beads for table, chairs, sink, plates and second bed: the engine files them from the plan's "
                  "leftovers; this stage may not run bd.", "kind": "engine_step"}
FLD_25_16 = {"what": "The nine follow-up beads are not filed. Writers cannot run bd, so the engine has to file them from "
                     "the plan's leftovers. The README only lists them as Gaps.", "kind": "engine_step"}
# lifesim-iqad: a number the code computes across seeds; a test could prove it
IQAD = {"what": "Whether the energy decay of 2.9 an hour holds across other seeds or a soak longer than 14 days. The sweep "
                "and both 14-day soaks pass, but the 4-lifer soak is sensitive to small pace changes.", "kind": "checkable"}
IQAD_R2 = {"what": "I did not judge the decision file's narrowing of needs.R2 and R6: every need failure no longer ends the "
                   "running action. Whether to accept that reading is the owner's call.", "kind": "owner_decision"}
# lifesim-fld.25.15 and lifesim-fld.25.19: facts from web pages and binary files the repo does not hold
FLD_25_15 = {"what": "Prices and licences of engine-store or Sketchfab dread and braid packs were not read", "kind": "external_fact"}
FLD_25_15B = {"what": "Asset names, authors and licences were taken from the MakeHuman pack pages; I did not re-open the pages",
              "kind": "external_fact"}
FLD_25_19 = {"what": "Mesh sizes (73x91x16, 73x212x69) and the claim that only four meshes use mirror.mat were not re-read "
                     "from the FBX files", "kind": "external_fact"}


SOURCE = "https://example.com/pack-page"
LEFT = [{"title": "Table and chairs", "why": "the catalogue needs them"}]  # the plan's leftovers: the engine files them
PLAN_LEFT = dict(PLAN, leftovers=LEFT)
IQAD_BEAD = dict(
    BEAD, acceptance_criteria="f.txt exists; the energy decay holds across other seeds in a soak"
)  # IQAD is inside its done-when


def open_as(*kinds, source=SOURCE):
    """The verifier leaves every item open, with its own kind (n counts from 1) and, for an outside fact, its source."""
    return {"items": [verdict(n, "open", why="cannot check here", kind=k, source=source if k == "external_fact" else "")
                      for n, k in enumerate(kinds, 1)]}


class NoBlock(T.LandReviewBase):

    def go(self, items, verify=None, extra_reviews=(), bead=BEAD, writes=1, plan=PLAN_LEFT, **cfg):
        answers = {"plan": [plan], "write": [WRITE] * writes, "review": [dict(CLEAN, unchecked=items), *extra_reviews]}
        if verify:
            answers["verify"] = verify
        with self.store.stub(show=bead):
            return self.run_engine(answers, **cfg)

    def unit(self):
        """An engine at land with the verifier's plumbing stubbed (no model, no tree)."""
        e = self.verifier({"changed_paths": lambda: [], "diff_text": lambda: ""})
        e.budget.labels = ["visual"]  # verify runs only on a visual bead
        return e

    def comments(self):
        return [c[3] for c in self.bd_calls if c[:2] == ("comments", "add")]

    def creates(self):
        return [c for c in self.bd_calls if c[0] == "create" and "owner-look" in c]  # review beads (leftovers carry a from: label)

    def test_an_engine_step_is_settled_by_the_engine_with_no_verifier_and_no_ask(self):
        for item in (YXBB_7, FLD_25_16):
            self.bd_calls.clear()
            rc, s = self.go([item])
            self.assertEqual(rc, 0, self.blocked)
            self.assertIsNone(self.ask())
            self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])  # no verify call
            (v,) = self.eng.verified
            self.assertEqual((v["verdict"], v["why"]), ("settled", "the engine does this at land"))
            self.assertEqual(self.creates(), [])

    def test_a_checkable_item_goes_back_to_the_writer_for_a_test_never_to_the_owner(self):
        rc, s = self.go([IQAD], verify=[open_as("checkable")], extra_reviews=[CLEAN], writes=2, bead=IQAD_BEAD)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)  # the fix round
        self.assertTrue(any("add a test or check that proves: " + IQAD["what"] in p for p in s.prompts))
        self.assertEqual(self.eng.unverified, [])  # the round proved it (its review lists nothing)

    def test_a_checkable_item_the_round_leaves_unproven_goes_again_then_the_bead_is_stuck_not_landed(self):
        again = dict(CLEAN, unchecked=[IQAD])
        rc, s = self.go([IQAD], verify=[open_as("checkable")], extra_reviews=[again, again], writes=3, bead=IQAD_BEAD)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 3)  # the first write and max_fix_rounds (2) fix rounds
        self.assertEqual(self.closed, [])
        self.assertIn("it needs the owner's hint", self.blocked[0])
        self.assertNotIn("verify: before land", self.blocked[0])  # a stuck bead, not a verify ask
        self.assertEqual(self.eng.unverified, [])

    def test_a_checkable_item_with_no_fix_round_left_is_stuck_not_landed(self):
        rc, s = self.go([IQAD], verify=[open_as("checkable")], max_fix_rounds=0, bead=IQAD_BEAD)
        self.assertEqual(rc, 2)
        self.assertEqual(self.closed, [])
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)
        self.assertIn("it needs the owner's hint", self.blocked[0])

    def test_a_failed_proving_round_does_not_land(self):
        e = self.unit()
        rounds = []

        def fix(kind, tail):
            cast(Any, e).fixes += 1
            rounds.append(tail)
            return "stuck"  # the fix round did not pass its checks and review
        with (mock.patch.object(e, "ai", return_value=(open_as("checkable"), None)), mock.patch.object(e.fixer, "fix", side_effect=fix),
              self.assertRaises(engine.Blocked) as ctx):
            e.verifier.run([IQAD])
        self.assertEqual(len(rounds), 2)  # one per round of the budget, then stuck
        self.assertIn("it needs the owner's hint", ctx.exception.why)
        self.assertEqual(e.unverified, [])

    def lands_unverified(self, items):
        rc, _ = self.go(items, verify=[open_as(*["external_fact"] * len(items))], bead=dict(BEAD, parent="t-0"))
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        note = next(c for c in self.comments() if c.startswith("Land (engine)"))
        self.assertIn("Unverified, for the owner:", note)
        for u in items:
            self.assertIn(u["what"], note)
        (c,) = self.creates()
        self.assertEqual(c[c.index("--labels") + 1], "owner-look")  # not the auto label
        self.assertEqual(c[c.index("--parent") + 1], "t-0")
        body = c[c.index("--description") + 1]
        self.assertIn("Unverified, for the owner:", body)
        self.assertIn(items[0]["what"], body)

    def test_prices_and_licences_from_web_pages_land_with_an_unverified_list_and_an_owner_review_bead(self):  # fld.25.15
        self.lands_unverified([FLD_25_15, FLD_25_15B])

    def test_mesh_sizes_from_binary_files_land_with_an_unverified_list_and_an_owner_review_bead(self):  # fld.25.19
        self.lands_unverified([FLD_25_19])

    def test_taste_lands_unverified_too(self):
        item = {"what": "the menu reads well on a phone", "kind": "taste"}
        rc, _ = self.go([item], verify=[open_as("taste")])
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual(self.eng.unverified[0]["kind"], "taste")

    def test_an_owner_decision_still_asks(self):
        rc, _ = self.go([IQAD_R2], verify=[open_as("owner_decision")])
        self.assertEqual(rc, 2)
        self.assertEqual(T.read_ask()["kind"], "decision")
        self.assertIn("needs.R2", T.card_of(T.read_ask()))

    def test_one_owner_decision_among_unverified_items_asks_only_for_it(self):
        rc, _ = self.go([FLD_25_19, IQAD_R2], verify=[open_as("external_fact", "owner_decision")])
        self.assertEqual(rc, 2)
        q = T.card_of(T.read_ask())
        self.assertIn("needs.R2", q)
        self.assertNotIn("mirror.mat", q)

    def test_an_old_kind_that_stays_open_is_still_asked(self):
        rc, _ = self.go([{"what": "the menu reads well", "kind": "requirement"}], verify=[open_as("other")])
        self.assertEqual(rc, 2)
        self.assertIn("menu reads well", T.card_of(T.read_ask()))

    def test_an_engine_step_is_settled_only_when_the_engine_will_do_it(self):
        e = self.unit()
        claim = "the follow-up beads cover all nine objects correctly"
        self.assertFalse(e.routing.engine_does(claim))
        self.assertFalse(e.routing.engine_does(YXBB_7["what"]))  # the plan has no leftovers: nothing is filed
        e.plan_data = plan_of(PLAN_LEFT)
        self.assertFalse(e.routing.engine_does(claim))  # a claim about the result, not about the filing
        self.assertTrue(e.routing.engine_does(YXBB_7["what"]))
        self.assertTrue(e.routing.engine_does(FLD_25_16["what"]))
        self.assertTrue(e.routing.engine_does("The gate runs at land"))
        self.assertTrue(e.routing.engine_does("the engine closes the bead"))
        self.assertFalse(e.routing.engine_does("screenshots are copied into the repo"))  # no visual paths set
        with mock.patch.object(e, "ai", return_value=(open_as("engine_step"), None)) as ai, \
                mock.patch.object(e.fixer, "fix", return_value="accept") as fix:
            e.plan_data = plan_of(PLAN)
            e.verifier.run([{"what": claim, "kind": "engine_step"}])
        ai.assert_called_once()  # sent to the verifier, not settled blindly
        fix.assert_called_once()  # and, unproven, treated as checkable

    def test_an_item_naming_code_is_checkable_whatever_its_label(self):
        e = self.unit()
        item = {"what": "LotGrids.UseCellBeside picks the facing side", "kind": "external_fact"}
        diff = "+    public Cell UseCellBeside(Lot lot) {\n"
        with mock.patch.object(e, "diff_text", return_value=diff):
            self.assertEqual(e.routing.resolve_kind(item, {"kind": "external_fact", "source": SOURCE})[0], "checkable")
            self.assertEqual(e.routing.resolve_kind(dict(item, kind="taste"), {})[0], "checkable")
            with mock.patch.object(e, "ai", return_value=(open_as("external_fact"), None)), \
                    mock.patch.object(e.fixer, "fix", return_value="accept") as fix:
                e.verifier.run([item])
        fix.assert_called_once()  # a proving round, not an unverified landing
        self.assertEqual(e.unverified, [])
        for what in ("see src/lots/grid.py for the rule", "the config.yaml key is read", "snake_case_name is unchanged in the diff"):
            with mock.patch.object(e, "diff_text", return_value="+ snake_case_name = 1\n"):
                self.assertEqual(e.routing.resolve_kind({"what": what, "kind": "taste"}, {})[0], "checkable", what)
        with mock.patch.object(e, "diff_text", return_value=""):  # a symbol not in the diff is no code of this task
            self.assertEqual(e.routing.resolve_kind({"what": "the MakeHuman licence is CC0", "kind": "external_fact"},
                                            {"source": SOURCE})[0], "external_fact")

    def test_an_external_fact_without_a_source_is_checkable(self):
        e = self.unit()
        item = {"what": "the dread pack costs 12 dollars", "kind": "external_fact"}
        self.assertEqual(e.routing.resolve_kind(item, {"kind": "external_fact", "source": ""})[0], "checkable")
        self.assertEqual(e.routing.resolve_kind(item, {"kind": "external_fact", "source": SOURCE})[0], "external_fact")
        self.assertEqual(e.routing.resolve_kind(dict(item, source=SOURCE), {})[0], "external_fact")

    def test_a_kind_only_moves_toward_a_stricter_route(self):
        e = self.unit()
        fact = {"what": "the dread pack costs 12 dollars", "kind": "checkable"}
        self.assertEqual(e.routing.resolve_kind(fact, {"kind": "external_fact", "source": SOURCE})[0], "checkable")  # never looser
        self.assertEqual(e.routing.resolve_kind(fact, {"kind": "owner_decision"})[0], "owner_decision")
        for legacy in ("requirement", "case", "number", "tooling"):
            for loose in ("taste", "external_fact", "engine_step"):
                u = {"what": "the menu reads well", "kind": legacy}
                self.assertEqual(e.routing.resolve_kind(u, {"kind": loose, "source": SOURCE})[0], legacy)
        taste = {"what": "the menu reads well", "kind": "taste"}
        self.assertEqual(e.routing.resolve_kind(taste, {"kind": "checkable"})[0], "checkable")  # stricter is allowed

    def test_the_schemas_and_briefs_name_the_kinds(self):
        for node in ("write", "review"):
            sch = answers.schema_for(node)["properties"]["unchecked"]["items"]["properties"]["kind"]["enum"]
            self.assertTrue(set(answers.ROUTED_KINDS) <= set(sch))
        item = answers.schema_for("verify")["properties"]["items"]["items"]
        self.assertIn("kind", item["required"])
        self.assertIn("source", item["required"])
        for k in answers.ROUTED_KINDS:
            self.assertIn(k + ":", vp.VERIFY_PROMPT)
            self.assertIn(k + ":", cp.UNCHECKED_TEXT)

    def filed(self, bead_id, title, existing):
        """file_owner_look for one more bead of epic t-0 while `existing` (a row) is the epic's review bead."""
        eng = make_engine(self.wt, bead=bead_id, store=self.store, attrs={
            "bead_title": title,
            "bead_parent": "t-0",
            "unverified": [{"what": "price of the pack", "kind": "external_fact", "why": ""}],
            })
        shows = (
            {"t-0": {"id": "t-0", "issue_type": "epic"}, existing["id"]: existing}
            if existing
            else {"t-0": {"id": "t-0", "issue_type": "epic"}}
        )
        self.bd_calls.clear()
        with self.store.stub(find_fn=lambda q: [{"id": existing["id"]}] if existing else []), \
                self.store.stub(show_fn=lambda i, **k: shows.get(i, {})):
            eng.owner_look.file_owner_look()
        return eng

    def test_the_owner_review_bead_of_an_epic_is_reused_and_appended_to(self):
        self.filed("t-1", "First", None)
        (c,) = self.creates()
        first = c[c.index("--description") + 1]
        self.assertIn("## t-1: First", first)
        row = {"id": "t-9", "parent": "t-0", "status": "open", "description": first, "dependencies": []}
        self.filed("t-2", "Second", row)
        self.assertEqual(self.creates(), [])  # no second bead for the epic
        (u,) = [c for c in self.bd_calls if c[0] == "update"]
        self.assertEqual(u[1], "t-9")
        self.assertIn("## t-1: First", u[3])
        self.assertIn("## t-2: Second", u[3])
        row["description"] = u[3]
        self.filed("t-2", "Second", row)  # a re-land replaces its own section, never doubles it
        (u2,) = [c for c in self.bd_calls if c[0] == "update"]
        self.assertEqual(u2[3].count("## t-2: Second"), 1)
        self.assertEqual(u2[3].count("## t-1: First"), 1)

    @T.NO_FCNTL
    def test_three_beads_of_one_epic_landing_together_file_one_review_bead_with_all_sections(self):
        store, lock = {}, threading.Lock()
        epic = {"id": "t-0", "issue_type": "epic"}

        def bd(*a, **kw):
            self.bd_calls.append(a)
            out = mock.Mock(returncode=0, stdout="", stderr="")
            if a[0] == "create":
                time.sleep(0.05)  # the window a race needs: list is done, create is not
                with lock:
                    store[f"t-9{len(store)}"] = {"id": f"t-9{len(store)}", "parent": a[a.index("--parent") + 1], "status": "open",
                                                   "description": a[a.index("--description") + 1], "dependencies": []}
            elif a[0] == "update":
                with lock:
                    store[a[1]]["description"] = a[a.index("--description") + 1]
            return out

        def show(i, **kw):
            with lock:
                return epic if i == "t-0" else dict(store.get(i, {}))

        def land(n):
            eng = make_engine(self.wt, bead=f"t-{n}", store=self.store, attrs={
                "bead_title": f"Bead {n}",
                "bead_parent": "t-0",
                "unverified": [{"what": f"price {n}", "kind": "external_fact", "why": "", "source": SOURCE}],
                })
            eng.owner_look.file_owner_look()

        def found(query):
            with lock:
                return [{"id": r["id"]} for r in store.values()]

        with self.store.stub(bd_fn=bd, find_fn=found), self.store.stub(show_fn=show):
            threads = [threading.Thread(target=land, args=(n,)) for n in (1, 2, 3)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        self.assertEqual(len(store), 1)  # exactly one review bead for the epic
        (row,) = store.values()
        for n in (1, 2, 3):
            self.assertIn(f"## t-{n}: Bead {n}", row["description"])
            self.assertIn(f"price {n}", row["description"])

    def test_a_bead_with_no_epic_files_its_review_bead_under_itself(self):
        eng = make_engine(self.wt, store=self.store, attrs={
            "bead_title": "Lone",
            "unverified": [{"what": "price", "kind": "external_fact", "why": "", "source": SOURCE}],
            })
        with self.store.stub(show={}):
            eng.owner_look.file_owner_look()
        (c,) = self.creates()
        self.assertEqual(c[c.index("--parent") + 1], "t-1")


if __name__ == "__main__":
    unittest.main()
