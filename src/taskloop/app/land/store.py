"""What the land keeps in factory.db: the follow-up outbox, one row per bead (the follow-ups its close has not filed yet).

The part registers when this module is imported, and the engine's run/state.py (the reader and writer of the outbox) uses LAND at import:
Python here loads an unused import lazily, so an import alone registers nothing, and a part must be registered before the first open of
factory.db. docs/design/stage-isolation.md 3.1."""
from taskloop.contracts.dbparts import Part, register
from taskloop.contracts.followups import FollowupOutbox

TABLE = "followup"

LAND = register(Part(
    name="land", version=1, tables=(TABLE,),
    records=(FollowupOutbox,),
    ddl="""
CREATE TABLE followup (bead TEXT PRIMARY KEY, t REAL NOT NULL, body TEXT NOT NULL);
"""))
