"""Always compare delegate's vendored contract with the records that task-loop reads.

The schema is copied from delegate 0.56.0. The engine reads a projection of its answer, tolerating unmodeled keys.
StatusSnapshot is a projection of status, so its renamed and joined fields are mapped back to their wire paths below.
"""
import json
import sys
from pathlib import Path
from typing import get_args, get_type_hints

from any_contract import diff_schema, undeclared

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from tlkernel import delegate, schema
from tlkernel.snapshots import StatusSnapshot

CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "src/delegate/data/contract.json").read_text(
    encoding="utf-8"))

# Exact projection differences, never wildcards; a resolved exception fails until removed.
# Each entry is (upstream-only values, mirror-only values, reason).
KNOWN_DRIFT = {
    "answer.stop.fields": ((), ("producer",), "engine-only provenance of a synthesized stop"),
    "answer.stop.producer.enum": ((), ("delegate", "engine"), "engine-only provenance of a synthesized stop"),
    "answer.fields": (("ask_user", "attempts", "brief_prefix", "cwd", "fallback_reason", "needs_input", "notice", "rung",
                        "transcript", "transcript_info", "transcript_status"), (),
                      "These delegate routing and interactive fields are outside the engine answer projection."),
    "answer.attempts[].fields": (("kind", "lane", "model", "outcome", "secs", "tokens"), (),
                                 "The engine does not read delegate's attempt list yet (tl-7i9k.45)."),
    "answer.attempts[].kind.enum": (("canary", "first", "lane_poll", "lane_wait", "network_rerun", "new_thread", "reroute",
                                     "schema_reask", "worker_retry"), (),
                                    "The engine does not read delegate's attempt list yet (tl-7i9k.45)."),
    "answer.attempts[].tokens.fields": (("cached", "in", "out"), (),
                                        "The engine does not read delegate's attempt list yet (tl-7i9k.45)."),
    "answer.ask_kind.enum": (("decision",), (), "The engine keeps ask_kind as an open string."),
    "answer.ask_user.fields": (("options", "question", "then"), (), "The engine does not consume delegate's interactive ask."),
    "answer.context.fields": (("env_keys", "instructions"), (), "The engine keeps context as an open dictionary."),
    "answer.transcript_info.fields": (("bytes", "from", "kind", "path", "to"), (),
                                                "The engine does not consume transcript metadata."),
    "answer.transcript_info.kind.enum": (("claude", "codex", "opencode_export"), (),
                                                  "The engine does not consume transcript metadata."),
    "answer.transcript_status.enum": (("died_before_session_id", "not_launched", "ok", "ref_unresolvable", "unsupported", None), (),
                                      "The engine does not consume transcript metadata."),
    "answer.usage.tokens.anyOf[0].fields": (("cache_read", "cache_write", "cache_write_by_ttl", "cached", "in", "in_fresh", "out"), (),
                                          "The engine projects usage tokens into one typed accounting record."),
    "answer.usage.tokens.anyOf[1].fields": (("cached", "in", "out"), (),
                                          "The engine does not model delegate's legacy token variant."),
    "answer.usage.tokens.fields": ((), ("cache_read", "cache_write", "cache_write_by_ttl", "in_fresh", "out"),
                                   "The engine projects usage tokens into one typed accounting record."),
    "reasons.engine_codes": ((), ("overrun",), "overrun is synthesized by the engine."),
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


class DelegateContract(Case):
    def test_run_and_status_struct_fields_and_literals_match_the_vendored_contract(self):
        assert CONTRACT["contract"] == 4
        drift = diff_schema(CONTRACT["answer_schema"], schema.of(delegate.DelegateResult), "answer")
        drift.update(diff_schema(CONTRACT["status_schema"], status_projection(), "status"))
        engine_reasons = {value for name, value in vars(delegate).items() if name.startswith("REASON_")}
        missing_reasons = engine_reasons - set(CONTRACT["reasons"])
        if missing_reasons:
            drift["reasons.engine_codes"] = ((), tuple(sorted(missing_reasons)))
        assert all(reason for _, _, reason in KNOWN_DRIFT.values())
        assert undeclared(drift, KNOWN_DRIFT) == ([], [])

    def test_closed_stop_vocabularies_and_open_reasons_match(self):
        for name, literal in (("scopes", delegate.Scope), ("permanences", delegate.Permanence),
                              ("retry_kinds", delegate.RetryKind), ("denied_kinds", delegate.DenialKind)):
            with self.subTest(name=name):
                assert set(CONTRACT[name]) == set(get_args(literal))
        assert get_type_hints(delegate.StopFacts)["reason"] is str
        # Reasons are explicitly open; only unknown engine constants are ratcheted above.
        for reason, facts in CONTRACT["reasons"].items():
            for field, vocabulary in (("scope", "scopes"), ("permanence", "permanences"), ("retry", "retry_kinds")):
                with self.subTest(reason=reason, field=field):
                    assert facts[field] in CONTRACT[vocabulary]

    def test_diff_detects_new_literals_inside_an_unmapped_subtree(self):
        upstream = {"properties": {"ignored": {"items": {"properties": {"state": {"enum": ["new"]}}}}}}
        assert diff_schema(upstream, {}, "status") == {
            "status.fields": (("ignored",), ()),
            "status.ignored[].fields": (("state",), ()),
            "status.ignored[].state.enum": (("new",), ()),
        }


def test_product_request_fields_match_delegate_schema():
    properties = CONTRACT["request_schema"]["properties"]
    for name in ("prefer", "writer_exec", "reviewer_other_family"):
        assert properties[name] == schema.of(delegate.RunRequest)["properties"][name]
