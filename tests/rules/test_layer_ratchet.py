"""Test layers, ratchet mode (CLAUDE.md, Test layers): a directory of unit-level tests may not gain a `@real_proc` / `@real_git` test or a
real `time.sleep`. Today's offenders are the baseline (layer_baseline.json); only an increase fails, so the cleanup PRs lower it."""
import json

from rules import layer_ratchet


def test_no_new_layer_offender():
    base = json.loads(layer_ratchet.BASELINE.read_text(encoding="utf-8"))
    bad = layer_ratchet.grown(layer_ratchet.count_tree(), base)
    assert bad == [], ("a test outside real/ and e2e/ gained a real process/git mark or a time.sleep: move it to real/, or fake the spawn "
                       "(procsim / gitsim) and inject the clock (fake_clock): " + "; ".join(bad))


def test_grown_names_only_increases():
    base = {"land": {"sleep": 2}}
    assert layer_ratchet.grown({"land": {"sleep": 2}, "run": {"real_mark": 1}}, base) == ["run: real_mark 1 (baseline 0)"]
    assert layer_ratchet.grown({"land": {"sleep": 1}}, base) == []
