"""tl-bxk.10.28: a verify item never parks a bead unless it is a real owner decision. The fixtures are the five asks that
parked lifesim on 2026-10-22 (~/.config/task-loop/asks/lifesim-*.json), each item with the kind the engine now routes by."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engine as T  # noqa: E402
from test_engine import BEAD, CLEAN, PLAN, WRITE, engine, tl, verdict  # noqa: E402

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


def open_as(*kinds):
    """The verifier leaves every item open, with its own kind (n counts from 1)."""
    return {"items": [verdict(n, "open", why="cannot check here", kind=k) for n, k in enumerate(kinds, 1)]}


class NoBlock(unittest.TestCase):
    setUp, tearDown, commit_base_cfg, fake_bd, run_engine, ask = (
        T.EngineTest.setUp, T.EngineTest.tearDown, T.EngineTest.commit_base_cfg, T.EngineTest.fake_bd,
        T.EngineTest.run_engine, T.EngineTest.ask)

    def go(self, items, verify=None, extra_reviews=(), bead=BEAD, writes=1, **cfg):
        answers = {"plan": [PLAN], "write": [WRITE] * writes, "review": [dict(CLEAN, unchecked=items)] + list(extra_reviews)}
        if verify:
            answers["verify"] = verify
        with mock.patch.object(tl, "show", return_value=bead):
            return self.run_engine(answers, **cfg)

    def comments(self):
        return [c[3] for c in self.bd_calls if c[:2] == ("comments", "add")]

    def creates(self):
        return [c for c in self.bd_calls if c[0] == "create"]

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

    def test_an_engine_step_the_verifier_reclassifies_is_settled_too(self):
        item = dict(YXBB_7, kind="tooling")
        rc, _ = self.go([item], verify=[open_as("engine_step")])
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual(self.eng.verified[0]["why"], "the engine does this at land")

    def test_a_checkable_item_goes_back_to_the_writer_once_for_a_test_never_to_the_owner(self):
        rc, s = self.go([IQAD], verify=[open_as("checkable")], extra_reviews=[CLEAN], writes=2)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)  # the fix round
        self.assertTrue(any("add a test or check that proves: " + IQAD["what"] in p for p in s.prompts))
        self.assertEqual(self.eng.unverified, [])  # the round proved it (its review lists nothing)

    def test_a_checkable_item_the_round_leaves_unproven_lands_unverified(self):
        again = dict(CLEAN, unchecked=[IQAD])
        rc, s = self.go([IQAD], verify=[open_as("checkable")], extra_reviews=[again], writes=2)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)  # once, not again
        self.assertEqual([u["what"] for u in self.eng.unverified], [IQAD["what"]])

    def test_a_checkable_item_with_no_fix_round_left_lands_unverified_without_a_round(self):
        rc, s = self.go([IQAD], verify=[open_as("checkable")], max_fix_rounds=0)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)
        self.assertEqual(len(self.eng.unverified), 1)

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
        a = self.ask()
        self.assertEqual(a["kind"], "verify")
        self.assertIn("needs.R2", a["question"])

    def test_one_owner_decision_among_unverified_items_asks_only_for_it(self):
        rc, _ = self.go([FLD_25_19, IQAD_R2], verify=[open_as("external_fact", "owner_decision")])
        self.assertEqual(rc, 2)
        q = self.ask()["question"]
        self.assertIn("needs.R2", q)
        self.assertNotIn("mirror.mat", q)

    def test_an_old_kind_that_stays_open_is_still_asked(self):
        rc, _ = self.go([{"what": "the menu reads well", "kind": "requirement"}], verify=[open_as("other")])
        self.assertEqual(rc, 2)
        self.assertIn("menu reads well", self.ask()["question"])

    def test_the_schemas_and_briefs_name_the_kinds(self):
        for node in ("write", "review"):
            sch = engine.SCHEMAS[node]["properties"]["unchecked"]["items"]["properties"]["kind"]["enum"]
            self.assertTrue(set(engine.ROUTED_KINDS) <= set(sch))
        self.assertIn("kind", engine.SCHEMAS["verify"]["properties"]["items"]["items"]["required"])
        for k in engine.ROUTED_KINDS:
            self.assertIn(k + ":", engine.VERIFY_PROMPT)
            self.assertIn(k + ":", engine.UNCHECKED_TEXT)

    def filed(self, bead_id, title, existing):
        """file_owner_look for one more bead of epic t-0 while `existing` (a row) is the epic's review bead."""
        eng = engine.Engine(bead_id, str(self.wt), engine.load_cfg(str(self.wt)))
        eng.bead_title, eng.bead_parent = title, "t-0"
        eng.unverified = [{"what": "price of the pack", "kind": "external_fact", "why": ""}]
        real = self.fake_bd

        def bd(*a, **kw):
            r = real(*a, **kw)
            if a[0] == "list":
                r.stdout = json.dumps([{"id": existing["id"]}] if existing else [])
            return r
        shows = {"t-0": {"id": "t-0", "issue_type": "epic"}, existing["id"]: existing} if existing else {"t-0": {"id": "t-0", "issue_type": "epic"}}
        self.bd_calls.clear()
        with mock.patch.object(tl, "bd", side_effect=bd), mock.patch.object(tl, "show", side_effect=lambda i, **k: shows.get(i, {})):
            eng.file_owner_look()
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


if __name__ == "__main__":
    unittest.main()
