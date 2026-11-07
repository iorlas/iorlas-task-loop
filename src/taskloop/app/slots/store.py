"""What the slots keep in factory.db: the leases (run, loop, resource and slot holders), one row per kind and name.

The part is a plain value; app/parts.py lists it (tests/rules/test_stage_parts.py fails until it does).
docs/design/stage-isolation.md 3.1."""
from taskloop.contracts.dbparts import Part
from taskloop.contracts.locks import EngineLock

SLOTS = Part(
    name="slots", version=1, tables=("lease",),
    records=(EngineLock,),
    ddl="""
CREATE TABLE lease (kind TEXT NOT NULL CHECK (kind IN ('run','loop','resource','slot')), name TEXT NOT NULL,
  holder TEXT NOT NULL, run TEXT, host TEXT, pid INTEGER, start_id TEXT, since REAL NOT NULL, beat REAL, until REAL,
  body TEXT, PRIMARY KEY (kind, name));
""")
