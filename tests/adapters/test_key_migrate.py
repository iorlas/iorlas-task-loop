"""One repo key (tl-19hr): old spellings in repos/, artifacts/, shared/ and factory.db become loop_key; a rerun is a no-op."""
import json

from support.fakegit import ScriptedGit

from taskloop.adapters import key_migrate as km
from taskloop.adapters import layout_migrate as lm
from tlkernel import check_files, factorydb
from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir
from tlkernel.rowstores import ReposStore
from tlkernel.rundocs import Durations, durations
from tlkernel.snapshots import RepoEntry, ReposIndex

ORIGIN = "git@example.com:acme/widget.git"


class Git(ScriptedGit):
    """One repo whose origin and common dir are known."""

    def common_dir(self, d: str) -> str:
        return f"{d}/.git"

    def config_get(self, d: str, key: str) -> str:
        return ORIGIN

    def remote_url(self, d: str, remote: str) -> str:
        return ORIGIN


def test_the_checks_name_a_repo_as_its_loop_does(workdir):
    repo = workdir / "widget"
    repo.mkdir()
    assert check_files.repo_key(Git(), str(repo)) == loop_key(repo)


def test_old_spellings_are_the_three_hashed_names_an_older_tl_wrote(workdir):
    repo = str(workdir / "widget")
    assert len(km.old_spellings(Git(), repo)) == 3
    assert all(km.stale(k) for k in km.old_spellings(Git(), repo))
    assert not km.stale(loop_key(repo))


def test_every_old_key_moves_to_the_one_key_in_files_and_rows_and_a_second_run_changes_nothing(workdir):
    cfg = ConfigDir(workdir / "cfg")
    repo = workdir / "widget"
    repo.mkdir()
    checks, state, short = km.old_spellings(Git(), str(repo))
    one = loop_key(repo)
    ReposStore(cfg).write(ReposIndex(repos={"acme/widget": RepoEntry(path=str(repo), added=1.0)}))
    for rel, text in {f"repos/{checks}/durations.json": "{}", f"repos/{state}/slot-state/s1/scratch": "t", f"repos/{short}/slots/seq": "1",
                      f"artifacts/{checks}/bd-1/run-1/ask-1/shot.png": "png", f"repos/{one}/loop/state.json": "{}",
                      "repos/gone-0123456789/slots/seq": "9", f"shared/{short}.json": "{}"}.items():
        (cfg.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (cfg.root / rel).write_text(text)
    docs = durations(cfg)
    docs.of(checks).write(Durations())
    con = factorydb.open_rw(cfg.factory_db())
    assert con is not None
    with con:
        con.execute("INSERT INTO check_pass (repo_key,check_id,digest,kind,tree,base,run,host,ts,body) "
                    "VALUES (?,'unit','d1','pass','t','b','r','h',1.0,'{}')", (checks,))
    con.close()
    assert lm.old_layout(cfg)
    said: list[str] = []
    assert lm.migrate(cfg, said.append, 5.0, Git()) == 0
    files = sorted(p.relative_to(cfg.root).as_posix() for p in cfg.root.rglob("*") if p.is_file() and p.suffix != ".jsonl"
                   and "factory.db" not in p.name)
    assert [f for f in files if f.startswith(("repos/", "artifacts/", "retired/", "shared/"))] == sorted([
        f"artifacts/{one}/bd-1/run-1/ask-1/shot.png", f"repos/{one}/durations.json", f"repos/{one}/loop/state.json",
        f"repos/{one}/slot-state/s1/scratch", f"repos/{one}/slots/seq", "retired/repos/gone-0123456789/slots/seq", f"shared/{one}.json"])
    con = factorydb.open_rw(cfg.factory_db())
    assert con is not None
    assert [r[0] for r in con.execute("SELECT repo_key FROM check_pass")] == [one]
    assert [r[0] for r in con.execute("SELECT k FROM duration_doc WHERE k LIKE 'durations:%'")] == [f"durations:{one}"]
    con.close()
    journal = (cfg.root / "layout-migrate.jsonl").read_text()
    assert json.loads(journal.splitlines()[-1])["rows"] == 2
    assert not lm.old_layout(cfg)
    assert lm.migrate(cfg, said.append, 6.0, Git()) == 0
    assert (cfg.root / "layout-migrate.jsonl").read_text() == journal
    assert said[-1].startswith("nothing to migrate")
