## Direction (to add to packages/sqlite-store/README.md)

This package is the seed of a database library, and it will grow into an ORM-shaped one. It is not one yet.

Rules for growth, so it never grows by shortcut:
- Absorb, do not invent. Each addition is a pattern a real caller needed twice (a second slice or a second app). The README names the pattern and the problem it removes.
- Explicit SQL stays first-class. Guarded writes (`cas_update`, UPDATE ... WHERE the precondition still holds) are the safety mechanism and are never hidden behind magic.
- Typed in, typed out. Rows map to models (pydantic v2) through one helper; no tuple indexing in callers.
- Transactions are values (`Tx`) passed by the caller; one writer at a time, so transactions stay short and never wrap external calls.
- Backends later. SQLite stays the only backend until a second is real; every addition names its backend-specific part so another database can follow.
- No dual readers, no compatibility layers: a schema change is a version bump and a drain (see the schema-upgrade rule).
Open: whether factory.db may ever become a golden source (today it is disposable by the 2026-11-08 rule).
