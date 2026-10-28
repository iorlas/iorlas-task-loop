"""python3 tests/feature_tests.py FEATURE: run only that feature's tests (`just test FEATURE`); no argument runs the whole suite.

A feature's tests are the modules listed below (the flat tests as they are today) plus every test_*.py under tests/FEATURE/ once
an extraction bead moves them there. A feature not in FEATURES is an error, never an empty green run.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
FEATURES = {
    "core": ["test_trace_records", "test_tl"],
    "lanes": ["test_opencode", "test_write_idle", "test_worker_calls", "test_lane_policy", "test_call_state", "test_procs", "test_kill_tree"],
    "checks": ["test_checks_speed", "test_check_trim"],
    "plan": [],
    "adapters": [],
    "slots": ["test_slots", "test_slot_git"],
    "review": ["test_verify_noblock"],
    "loop": ["test_loop", "test_loop_more", "test_race_invariants"],
    "release": ["test_release"],
    "land": ["test_land_lock", "test_held_branch"],
    "look": ["test_look", "test_looks"],
    "write": ["test_stages", "test_stages_visual", "test_stages_land"],
    "asks": ["test_dash_asks"],  # plus every test under tests/asks/ (lint, specs, intake, sweeps, the single ask store)
    "dash": sorted(p.stem for p in HERE.glob("test_dash*.py")),
}


def suite(feature):
    s = unittest.TestSuite()
    for name in FEATURES[feature]:
        s.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    folder = HERE / feature
    if folder.is_dir():
        s.addTests(unittest.defaultTestLoader.discover(str(folder), top_level_dir=str(HERE)))
    return s


def main(argv):
    if not argv:
        s = unittest.defaultTestLoader.discover(str(HERE), top_level_dir=str(HERE))
    elif argv[0] in FEATURES:
        s = suite(argv[0])
    else:
        print("unknown feature %r; known: %s" % (argv[0], ", ".join(FEATURES)), file=sys.stderr)
        return 2
    if not s.countTestCases():
        print("feature %r has no tests yet" % (argv[0] if argv else ""), file=sys.stderr)
        return 0 if not argv else 1
    return 0 if unittest.TextTestRunner(verbosity=1).run(s).wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
