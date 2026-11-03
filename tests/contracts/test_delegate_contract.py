"""Always compare delegate's vendored contract with the records that task-loop reads.

The upstream contract 3 is not a superset: it drops --failed and agent_model. Keep the existing run contract;
only its missing status_schema was copied from iorlas-delegate/skills/delegate/contract.json on 2026-11-03.
StatusSnapshot is a projection of status, so its renamed and joined fields are mapped back to their wire paths below.
"""
import copy
import json
import sys
import unittest
from pathlib import Path
from typing import get_args, get_type_hints

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import delegate, schema
from taskloop.contracts.snapshots import StatusSnapshot

CONTRACT = json.loads((Path(__file__).resolve().parents[1] / "fixtures/delegate3/skills/delegate/contract.json").read_text(
    encoding="utf-8"))

# Exact exceptions, never wildcards. May only shrink; a resolved exception fails until removed.
# Each entry is (upstream-only values, mirror-only values, reason).
KNOWN_DRIFT = {
    "answer.fields": ((), (
        "ask_kind", "context", "effort", "exit_code", "fallback", "family", "first_error", "first_lane", "flag",
        "transcript_status", "warning", "warnings", "worker",
    ), "The retained older fixture predates fields already read by the engine; removing them changes runtime behavior."),
    "answer.tokens.fields": ((), ("cached", "in", "out"),
                             "The retained fixture requires tokens but does not describe its fields."),
    "answer.usage.tokens.fields": ((), ("cache_write_by_ttl",),
                                   "The retained fixture predates the per-TTL accounting already read by the engine."),
    "answer.worker.fields": ((), (
        "end", "kill_sent", "pgid", "pid", "start", "stopped", "survivors", "term_sent", "waited_s",
    ), "The retained run fixture predates the worker lifecycle record."),
    "answer.worker.end.enum": ((), ("error", "ok", "timeout", "worker_survived"),
                               "The retained run fixture predates the worker lifecycle vocabulary."),
    "answer.worker.survivors[].fields": ((), ("pid", "start"),
                                        "The retained run fixture predates surviving-worker identities."),
    "reasons.engine_codes": ((), ("engine_only_unenforced", "only_family_unready", "overrun"),
                             "The retained fixture lacks two newer delegate reasons; overrun is created by the engine itself."),
    "status.fields": (("age_s", "asks", "auth", "cheap", "health", "holds", "network", "roles", "running"), (),
                      "StatusSnapshot deliberately persists only the lane cards and requests for input."),
    "status.lanes{}.fields": (("burn", "pace"), (), "The snapshot does not persist delegate's pace display."),
    "status.cockpit.fields": (("at", "legend", "next_worker", "v"), (),
                              "The snapshot uses the top-level timestamp and version and does not persist cockpit routing."),
    "status.cockpit.v.enum": ((1,), (), "The snapshot keeps the top-level version instead."),
    "status.cockpit.next_worker.fields": (("action", "effort", "fallback", "lane", "model", "pass", "say", "why"), (),
                                          "The snapshot does not persist cockpit routing."),
    "status.cockpit.lanes[].fields": (("detail", "login", "low_tokens", "meter", "running"), (),
                                      "These cockpit display fields have no snapshot representation."),
    "status.cockpit.lanes[].state.enum": (("logged_out", "off", "ready", "resting", "slow", "spend", "unknown"), (),
                                          "LaneStatus.state is an open string; narrowing it changes decoding behavior."),
    "status.cockpit.lanes[].unlock.fields": (("in_s", "known", "locked", "text", "why"), (),
                                            "The snapshot keeps only the unlock timestamp."),
    "status.cockpit.lanes[].windows[].fields": (("age_s", "resets_in_s", "source"), (),
                                               "The snapshot keeps window names, percentages and reset timestamps."),
    "status.cockpit.lanes[].login.fields": (("checked_at", "ok", "why"), (),
                                           "The snapshot does not persist cockpit login diagnostics."),
    "status.cockpit.lanes[].low_tokens[].fields": (("limit", "limit_name", "over", "used_pct", "window"), (),
                                                  "The snapshot does not persist cockpit token gates."),
    "status.cockpit.lanes[].low_tokens[].over.enum": (("ceiling", "gate"), (),
                                                     "The snapshot does not persist cockpit token gates."),
    "status.asks[].fields": (("answer", "id", "kind", "lane", "raised_at", "say", "used_pct"), (),
                             "The snapshot persists needs_input rather than delegate's ask ledger."),
    "status.auth{}.fields": (("age_s", "ok", "why"), (), "The snapshot does not persist cached authentication diagnostics."),
    "status.health[].fields": ((
        "canary", "evidence", "kind", "lane", "last_failures", "leases", "model", "needs_login", "rung", "source", "state",
        "until", "usage",
    ), (), "The snapshot does not persist delegate's health ledger."),
    "status.health[].leases.fields": (("live", "suspect"), (), "The snapshot does not persist health leases."),
    "status.health[].last_failures[].fields": (("outcome", "say", "ts"), (),
                                              "The snapshot does not persist health failure history."),
    "status.health[].usage.fields": (("known", "text"), (), "The snapshot does not persist health usage diagnostics."),
    "status.holds[].fields": (("ends_in_s", "id", "lane", "reason", "roles", "set_at", "set_by", "stale", "stale_at", "until"), (),
                              "The snapshot does not persist delegate's hold ledger."),
    "status.network.fields": (("age_s", "since", "up", "why"), (), "The snapshot does not persist network diagnostics."),
    "status.roles{}.fields": (("due", "hosts", "lane", "model", "net", "until", "usable", "why"), (),
                              "The snapshot does not persist role routing."),
    "status.roles{}.net.fields": (("age_s", "since", "up"), (), "The snapshot does not persist role network diagnostics."),
    "status.running[].fields": (("age_s", "lane", "pid", "role", "run_id", "started", "suspect", "task", "worker_pid"), (),
                                "The snapshot does not persist delegate's running-worker ledger."),
}


def node(value: object) -> dict:
    """A missing schema branch has no fields or Literals."""
    return value if isinstance(value, dict) else {}


def differences(want: dict, have: dict, path: str) -> dict[str, tuple[tuple, tuple]]:
    """Diff every named field and Literal, including nested rows, dictionaries and renamed wire fields."""
    out = {}
    wanted = set(want.get("properties", {})) | set(want.get("required", []))
    actual = set(have.get("properties", {})) | set(have.get("required", []))
    for facet, left, right in (("fields", wanted, actual),
                               ("enum", set(want.get("enum", [])), set(have.get("enum", [])))):
        if left != right:
            out[f"{path}.{facet}"] = (tuple(sorted(left - right, key=repr)), tuple(sorted(right - left, key=repr)))
    for name in wanted | actual:
        out.update(differences(want.get("properties", {}).get(name, {}), have.get("properties", {}).get(name, {}),
                               f"{path}.{name}"))
    for key, suffix in (("items", "[]"), ("additionalProperties", "{}")):
        left, right = want.get(key), have.get(key)
        if isinstance(left, dict) or isinstance(right, dict):
            out.update(differences(node(left), node(right), path + suffix))
    for key in ("anyOf", "oneOf"):
        left, right = want.get(key, []), have.get(key, [])
        for index in range(max(len(left), len(right))):
            out.update(differences(left[index] if index < len(left) else {}, right[index] if index < len(right) else {},
                                   f"{path}.{key}[{index}]"))
    return out


def status_projection() -> dict:
    """Undo snapshot_of's renames and join without inventing fields or Literals absent from its output records."""
    snapshot = schema.of(StatusSnapshot)["properties"]
    lane = dict(snapshot["lanes"]["items"]["properties"])
    flat = {name: lane[name] for name in ("family", "kind", "five", "week", "out", "out_until", "notes")}
    flat["reason"] = lane["out_reason"]
    for name in ("five", "week", "out", "out_until", "out_reason", "notes"):
        del lane[name]
    lane["unlock"] = {"properties": {"at": lane.pop("unlock_at")}}
    return {"properties": {
        "v": snapshot["v"], "ts": snapshot["at"], "needs_input": snapshot["needs_input"],
        "lanes": {"additionalProperties": {"properties": flat}},
        "cockpit": {"properties": {"lanes": {"items": {"properties": lane}}}},
    }}


class DelegateContract(unittest.TestCase):
    def test_run_and_status_struct_fields_and_literals_match_the_vendored_contract(self):
        self.assertEqual(CONTRACT["contract"], 3)
        drift = differences(CONTRACT["answer_schema"], schema.of(delegate.DelegateResult), "answer")
        drift.update(differences(CONTRACT["status_schema"], status_projection(), "status"))
        engine_reasons = {value for name, value in vars(delegate).items() if name.startswith("REASON_")}
        missing_reasons = engine_reasons - set(CONTRACT["reasons"])
        if missing_reasons:
            drift["reasons.engine_codes"] = ((), tuple(sorted(missing_reasons)))
        self.assertTrue(all(reason for _, _, reason in KNOWN_DRIFT.values()))
        self.assertEqual(drift, {path: (left, right) for path, (left, right, _) in KNOWN_DRIFT.items()})

    def test_closed_stop_vocabularies_and_open_reasons_match(self):
        for name, literal in (("scopes", delegate.Scope), ("permanences", delegate.Permanence),
                              ("retry_kinds", delegate.RetryKind), ("denied_kinds", delegate.DenialKind)):
            with self.subTest(name=name):
                self.assertEqual(set(CONTRACT[name]), set(get_args(literal)))
        self.assertIs(get_type_hints(delegate.StopFacts)["reason"], str)
        # Reasons are explicitly open; only unknown engine constants are ratcheted above.
        for reason, facts in CONTRACT["reasons"].items():
            for field, vocabulary in (("scope", "scopes"), ("permanence", "permanences"), ("retry", "retry_kinds")):
                with self.subTest(reason=reason, field=field):
                    self.assertIn(facts[field], CONTRACT[vocabulary])

    def test_diff_detects_nested_added_removed_and_renamed_fields_and_enum_values(self):
        base = {"properties": {"rows": {"items": {"properties": {"state": {"enum": ["ready", "off"]}}}}}}
        changed = copy.deepcopy(base)
        props = changed["properties"]["rows"]["items"]["properties"]
        props["new_state"] = props.pop("state")
        self.assertEqual(differences(base, changed, "status"), {
            "status.rows[].fields": (("state",), ("new_state",)),
            "status.rows[].state.enum": (("off", "ready"), ()),
            "status.rows[].new_state.enum": ((), ("off", "ready")),
        })
        props["state"] = props.pop("new_state")
        props["state"]["enum"] = ["ready", "new"]
        self.assertEqual(differences(base, changed, "status"), {
            "status.rows[].state.enum": (("off",), ("new",)),
        })

    def test_diff_walks_dictionary_values_and_uses_encoded_field_names(self):
        self.assertEqual(differences(
            {"additionalProperties": {"properties": {"from": {"enum": [1]}}}},
            {"additionalProperties": {"properties": {"from": {"enum": [2]}}}}, "rows"),
            {"rows{}.from.enum": ((1,), (2,))})
        self.assertIn("from", schema.of(delegate.TranscriptInfo)["properties"])
        self.assertNotIn("from_", schema.of(delegate.TranscriptInfo)["properties"])

    def test_diff_detects_new_literals_inside_an_unmapped_subtree(self):
        upstream = {"properties": {"ignored": {"items": {"properties": {"state": {"enum": ["new"]}}}}}}
        self.assertEqual(differences(upstream, {}, "status"), {
            "status.fields": (("ignored",), ()),
            "status.ignored[].fields": (("state",), ()),
            "status.ignored[].state.enum": (("new",), ()),
        })
