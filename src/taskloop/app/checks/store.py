"""What the gate keeps in factory.db: the green results of repo checks (and the base's reds) and one body per check round.

The part is a plain value; app/parts.py lists it (tests/rules/test_stage_parts.py fails until it does).
docs/design/stage-isolation.md 3.1."""
from tlkernel.checks import BaseRedRecord, PassRecord
from tlkernel.dbparts import Part, Prune
from tlkernel.factoryparts import ELIGIBLE

GATE = Part(
    name="gate", version=1, tables=("check_pass", "check_round"),
    records=(PassRecord, BaseRedRecord),
    ddl="""
CREATE TABLE check_pass (repo_key TEXT NOT NULL, check_id TEXT NOT NULL, digest TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('pass','base_red')), tree TEXT, base TEXT, run TEXT, host TEXT, ts REAL NOT NULL,
  body TEXT NOT NULL,
  PRIMARY KEY (repo_key, check_id, digest, kind));
CREATE INDEX check_tree ON check_pass(repo_key, tree, base);
CREATE TABLE check_round (run TEXT NOT NULL, round INTEGER NOT NULL, ts REAL, body TEXT NOT NULL, PRIMARY KEY (run, round));
""",
    prune=(Prune("check_round", f"""ts < ? AND NOT EXISTS (
        SELECT 1 FROM run AS parent WHERE parent.run=check_round.run AND parent.run NOT IN ({ELIGIBLE}))""", cutoffs=2),))
