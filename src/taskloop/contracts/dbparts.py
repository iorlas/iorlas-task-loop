"""The parts of factory.db: what a stage registers (its tables, its records, its upgrade steps) and the check every open makes.

A `Part` is one stage's share of the database: the tables it owns (`ddl`), the records it stores in them, and `steps` that take the
part from one version to the next (keyed by the version upgraded FROM, as sqlite_store's are). `register` is called when the stage's store
module is imported. `launch` runs on every open of factory.db, before anything else uses the connection, and compares each registered
part with its row in `schema_part`:

- no row: the part's tables are created, or adopted when they all exist and equal the code's; the row is written.
- db version below the code's: the part's steps run, in order, in one transaction, and the row moves to the code's version.
- db version above the code's: refused, this code is older than the data.
- same version, the tables differ from the code's DDL, or a record's `V` differs from the stored one: refused, the change needs a
  version bump (and a step). The golden test (tests/contracts/test_dbparts_golden.py) holds the same line before a change reaches main.

A read-only open writes nothing: it refuses a part newer than the code, or older than the part's `read_from`, and skips a part that has
no row yet (the writer has not launched it).
"""
import functools
import hashlib
import json
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from sqlite_store import SchemaError, Step, begin_immediate

from taskloop.contracts import schema
from taskloop.contracts.wire import Rec

PART_TABLE = "schema_part"
PART_DDL = (f"CREATE TABLE IF NOT EXISTS {PART_TABLE} (name TEXT PRIMARY KEY, version INTEGER NOT NULL, "
            "ddl_fingerprint TEXT NOT NULL, record_fingerprint TEXT NOT NULL)")


@dataclass(frozen=True)
class Prune:
    """How one table of a part ages: the `where` of its DELETE (`?` is the cutoff time, bound `cutoffs` times), and the tables whose
    rows go first (`after`: a parent row goes only once its children are pruned)."""

    table: str
    where: str
    cutoffs: int = 1
    after: tuple[str, ...] = ()


@dataclass(frozen=True, eq=False)
class Part:
    """One stage's tables and records in factory.db; `read_from` is the oldest version a read-only open accepts (None: only `version`)."""

    name: str
    version: int
    tables: tuple[str, ...]
    ddl: str
    records: tuple[type[Rec], ...] = ()
    steps: dict[int, Step] = field(default_factory=dict)
    read_from: int | None = None
    prune: tuple[Prune, ...] = ()


_REGISTRY: dict[str, Part] = {}


def register(part: Part) -> Part:
    """Add a part; a name or a table that is already claimed is a bug in the registering module."""
    if part.name in _REGISTRY:
        raise ValueError(f"part {part.name!r} is registered twice")
    for table in part.tables:
        owner = next((p.name for p in _REGISTRY.values() if table in p.tables), None)
        if owner is not None:
            raise ValueError(f"table {table!r} of part {part.name!r} already belongs to part {owner!r}")
    for rule in part.prune:
        if rule.table not in part.tables:
            raise ValueError(f"part {part.name!r} prunes {rule.table!r}, which is not its table")
    _REGISTRY[part.name] = part
    return part


def registered() -> tuple[Part, ...]:
    """The registered parts, in registration order."""
    return tuple(_REGISTRY.values())


def prune_order(parts: Iterable[Part] | None = None) -> tuple[Prune, ...]:
    """Every part's prune rules in an order that honours `after` (the first ready rule goes first, so declaration order breaks ties)."""
    todo = [rule for p in (registered() if parts is None else parts) for rule in p.prune]
    names = {rule.table for rule in todo}
    for rule in todo:
        if missing := set(rule.after) - names:
            raise ValueError(f"prune of {rule.table!r} waits for {sorted(missing)}, which no part prunes")
    ordered: list[Prune] = []
    while todo:
        done = {rule.table for rule in ordered}
        ready = next((rule for rule in todo if set(rule.after) <= done), None)
        if ready is None:
            raise ValueError(f"prune rules wait for each other: {sorted(rule.table for rule in todo)}")
        todo.remove(ready)
        ordered.append(ready)
    return tuple(ordered)


def doc_table(table: str) -> str:
    """The DDL of a stage's own table of typed documents (`k` the key with the record's name as prefix, `v` its JSON, `t` the write time):
    what `kv` was for every stage at once, now one per owner (read and written by docrows.RowDocs with `table=`)."""
    return f"CREATE TABLE {table} (k TEXT PRIMARY KEY, v TEXT NOT NULL, t REAL NOT NULL);"


def ddl() -> str:
    """The DDL of every registered part: what a fresh database is created from."""
    return "\n".join(p.ddl.strip() for p in _REGISTRY.values())


def _statements(text: str) -> list[str]:
    return [s for s in text.split(";") if s.strip()]


def _normal(sql: str) -> str:
    return "".join(sql.lower().split())


def tables_fingerprint(con: sqlite3.Connection, tables: Collection[str]) -> str:
    """A hash of the normalised DDL (tables and their indexes, whitespace and case aside) of the named tables in `con`."""
    marks = ",".join("?" * len(tables))
    rows = con.execute(
        f"SELECT type, name, tbl_name, sql FROM sqlite_master WHERE tbl_name IN ({marks}) AND sql IS NOT NULL ORDER BY type, name",
        tuple(tables)).fetchall()
    return hashlib.sha256(json.dumps([[r[0], r[1], r[2], _normal(r[3])] for r in rows]).encode()).hexdigest()


@functools.cache
def ddl_fingerprint(part: Part) -> str:
    """The fingerprint of `part.ddl` as sqlite stores it: the DDL is applied to an empty in-memory database and read back."""
    con = sqlite3.connect(":memory:", isolation_level=None)
    try:
        for statement in _statements(part.ddl):
            con.execute(statement)
        return tables_fingerprint(con, part.tables)
    finally:
        con.close()


def record_versions(part: Part) -> dict[str, int | None]:
    """Each stored record of the part and its wire version."""
    return {cls.__qualname__: cls.V for cls in sorted(part.records, key=lambda c: c.__qualname__)}


def record_fingerprint(part: Part) -> str:
    """A hash of the part's records and their `V`: it moves when a record's version does; a change of fields is the golden test's."""
    return hashlib.sha256(json.dumps(record_versions(part)).encode()).hexdigest()


def _bare(node: object) -> object:
    if isinstance(node, dict):
        return {k: _bare(v) for k, v in node.items() if k not in ("description", "title")}
    if isinstance(node, list):
        return [_bare(v) for v in node]
    return node


def schema_hash(cls: type[Rec]) -> str:
    """A hash of a record's contract schema without descriptions and titles (the golden test's)."""
    return hashlib.sha256(json.dumps(_bare(schema.of(cls)), sort_keys=True).encode()).hexdigest()


def golden(parts: Iterable[Part] | None = None) -> dict[str, dict[str, object]]:
    """What the golden file holds per part: its version, DDL fingerprint and each record's `V` and schema hash."""
    return {p.name: {"version": p.version, "ddl": ddl_fingerprint(p), "records": _shapes(p)}
            for p in (registered() if parts is None else parts)}


def _shapes(part: Part) -> dict[str, dict[str, object]]:
    return {c.__qualname__: {"v": c.V, "schema": schema_hash(c)} for c in sorted(part.records, key=lambda c: c.__qualname__)}


def _stored(con: sqlite3.Connection) -> dict[str, tuple[int, str, str]]:
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (PART_TABLE,)).fetchone() is None:
        return {}
    return {r[0]: (r[1], r[2], r[3]) for r in con.execute(f"SELECT name, version, ddl_fingerprint, record_fingerprint FROM {PART_TABLE}")}


def _present(con: sqlite3.Connection, part: Part) -> list[str]:
    marks = ",".join("?" * len(part.tables))
    return [r[0] for r in con.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({marks})", part.tables)]


def _adopt(con: sqlite3.Connection, part: Part) -> None:
    present = _present(con, part)
    if not present:
        for statement in _statements(part.ddl):
            con.execute(statement)
    elif len(present) != len(part.tables):
        raise SchemaError(f"factory.db part {part.name}: only {sorted(present)} of {sorted(part.tables)} exist")
    _same_tables(con, part)


def _same_tables(con: sqlite3.Connection, part: Part) -> None:
    if tables_fingerprint(con, part.tables) != ddl_fingerprint(part):
        raise SchemaError(f"factory.db part {part.name} v{part.version}: its tables {sorted(part.tables)} changed without a bump")


def _upgrade(con: sqlite3.Connection, part: Part, found: int) -> None:
    for version in range(found, part.version):
        step = part.steps.get(version)
        if step is None:
            raise SchemaError(f"factory.db part {part.name} is missing the upgrade step v{version} -> v{version + 1}")
        try:
            step(con)
        except Exception as error:
            raise SchemaError(f"factory.db part {part.name} upgrade step v{version} -> v{version + 1} failed: {error}") from error
    _same_tables(con, part)


def _write_row(con: sqlite3.Connection, part: Part) -> None:
    con.execute(f"INSERT OR REPLACE INTO {PART_TABLE}(name, version, ddl_fingerprint, record_fingerprint) VALUES (?,?,?,?)",
                (part.name, part.version, ddl_fingerprint(part), record_fingerprint(part)))


def _launch_part(con: sqlite3.Connection, part: Part, row: tuple[int, str, str] | None) -> None:
    if row is None:
        _adopt(con, part)
    elif row[0] > part.version:
        raise SchemaError(f"factory.db part {part.name} is v{row[0]}, this code knows v{part.version}: update it")
    elif row[0] < part.version:
        _upgrade(con, part, row[0])
    else:
        _same_tables(con, part)
        if row[2] != record_fingerprint(part):
            raise SchemaError(f"factory.db part {part.name} v{part.version}: a record changed its V without a version bump")
    _write_row(con, part)


def launch(con: sqlite3.Connection, *, readonly: bool, parts: Iterable[Part] | None = None) -> None:
    """The check every open of factory.db makes; raises SchemaError (the open then fails) and leaves the database as it was."""
    todo = registered() if parts is None else tuple(parts)
    if readonly:
        _launch_readonly(con, todo)
        return
    with begin_immediate(con):
        con.execute(PART_DDL)
        stored = _stored(con)
        for part in todo:
            _launch_part(con, part, stored.get(part.name))


def _launch_readonly(con: sqlite3.Connection, parts: Iterable[Part]) -> None:
    stored = _stored(con)
    for part in parts:
        row = stored.get(part.name)
        if row is None:
            continue
        if row[0] > part.version:
            raise SchemaError(f"factory.db part {part.name} is v{row[0]}, this code knows v{part.version}: update it")
        if row[0] < (part.version if part.read_from is None else part.read_from):
            raise SchemaError(
                f"factory.db part {part.name} is v{row[0]}, this code knows v{part.version}: the writer has not upgraded it yet")
