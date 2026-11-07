"""What the land keeps in factory.db: the follow-up outbox, one row per bead (the follow-ups its close has not filed yet).

The part is listed in app/parts.py (STAGE_PARTS). docs/design/stage-isolation.md 3.1."""
from tlkernel.dbparts import Part
from tlkernel.followups import FollowupOutbox

TABLE = "followup"

LAND = Part(
    name="land", version=1, tables=(TABLE,),
    records=(FollowupOutbox,),
    ddl="""
CREATE TABLE followup (bead TEXT PRIMARY KEY, t REAL NOT NULL, body TEXT NOT NULL);
""")
