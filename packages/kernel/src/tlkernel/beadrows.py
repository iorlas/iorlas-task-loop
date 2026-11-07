"""The index-owned bd projection and its per-repository observation in factory.db."""

import json
import sqlite3
from pathlib import Path

from tlkernel import factorydb
from tlkernel.bead import Bead

type Row = dict[str, object]


def row_of(bead: Bead) -> Row:
    """Preserve the dashboard row shape, including its abbreviated dependencies."""
    row = bead.to_dict()
    row["dependencies"] = [{k: dep.get(k) for k in ("id", "type", "title", "status")} for dep in row["dependencies"]]
    return row


def observation(con: sqlite3.Connection, repo_key: str) -> tuple[int | None, float | None, str, float | None]:
    """Marker, last success, error and last attempt, including a successful empty list."""
    found = con.execute("SELECT v,t FROM kv WHERE k=?", ("beads." + repo_key,)).fetchone()
    if found is None:
        return None, None, "", None
    record = json.loads(found[0])
    return record["marker"], record["ok_at"], record["error"], found[1]


def _record(con: sqlite3.Connection, repo_key: str, marker: int | None, ok_at: float | None, error: str, now: float) -> None:
    con.execute("INSERT INTO kv(k,v,t) VALUES (?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v,t=excluded.t",
                ("beads." + repo_key, json.dumps({"marker": marker, "ok_at": ok_at, "error": error}), now))


def replace_repo(con: sqlite3.Connection, repo_key: str, rows: list[Row], marker: int | None, now: float) -> None:
    """Replace a listing; the storage id is repo-qualified, while body preserves bd's id."""
    ids = json.dumps([json.dumps([repo_key, row["id"]]) for row in rows])
    con.execute("DELETE FROM bead WHERE repo_key=? AND id NOT IN (SELECT value FROM json_each(?))", (repo_key, ids))
    for row in rows:
        body = json.dumps(row, sort_keys=True, ensure_ascii=False)
        con.execute(
            "INSERT INTO bead(id,repo_key,title,status,priority,type,parent,assignee,labels,updated,fetched,body) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "repo_key=excluded.repo_key,title=excluded.title,status=excluded.status,priority=excluded.priority,"
            "type=excluded.type,parent=excluded.parent,assignee=excluded.assignee,labels=excluded.labels,"
            "updated=CASE WHEN bead.body<>excluded.body THEN excluded.updated ELSE bead.updated END,"
            "fetched=excluded.fetched,body=excluded.body,rev=bead.rev+(bead.body<>excluded.body)",
            (json.dumps([repo_key, row["id"]]), repo_key, row.get("title", ""), row["status"], row.get("priority"),
             row.get("issue_type", ""),
             row.get("parent", ""), row.get("assignee", ""), json.dumps(row.get("labels", [])), now, now, body))
    _record(con, repo_key, marker, now, "", now)


def set_error(con: sqlite3.Connection, repo_key: str, error: str, now: float) -> None:
    """A failed attempt changes neither the last listing nor its successful observation time."""
    marker, ok_at, _, _ = observation(con, repo_key)
    _record(con, repo_key, marker, ok_at, error, now)


def marker_of(con: sqlite3.Connection, repo_key: str) -> int | None:
    """The marker of the last successful listing."""
    return observation(con, repo_key)[0]


def read_repo(path: Path, repo_key: str) -> tuple[list[Row], float | None, str]:
    """Read only the DB; database availability is reported by factorydb.database_error."""
    con = None
    try:
        con = factorydb.open_ro(path)
        if con is None:
            return [], None, ""
        con.execute("BEGIN")
        _, ok_at, error, _ = observation(con, repo_key)
        rows = con.execute("SELECT body FROM bead WHERE repo_key=? AND body<>'{}' ORDER BY rowid", (repo_key,))
        return [json.loads(row[0]) for row in rows], ok_at, error
    except (sqlite3.Error, ValueError, KeyError, TypeError):
        return [], None, ""
    finally:
        if con is not None:
            con.close()
