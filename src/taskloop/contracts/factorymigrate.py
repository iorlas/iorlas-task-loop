"""Application-owned upgrade steps for authoritative factory.db schemas."""

from sqlite_store import Step

# Keys are the version upgraded FROM. For the next schema change, add its step
# here, increment factorydb.SCHEMA_VERSION, and update factorydb.DDL for new DBs.
# Steps use execute, never executescript or commit: the whole chain is atomic.
STEPS: dict[int, Step] = {}
