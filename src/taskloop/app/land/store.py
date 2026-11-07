"""What the land keeps in factory.db: the follow-up outbox, one row per bead (the follow-ups its close has not filed yet).

The land is the one writer (app/land/followups.py files them and drops the row); the part registers when this module is imported, which
the writer does, so a process that never files a follow-up never creates the table. docs/design/stage-isolation.md 3.1."""
from taskloop.contracts.dbparts import Part, register
from taskloop.contracts.followups import FollowupOutbox

TABLE = "followup"

LAND = register(Part(
    name="land", version=1, tables=(TABLE,),
    records=(FollowupOutbox,),
    ddl="""
CREATE TABLE followup (bead TEXT PRIMARY KEY, t REAL NOT NULL, body TEXT NOT NULL);
"""))
