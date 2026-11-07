"""An ADR as a file (`docs/adr/NNNN-title.md`): rendered, parsed back, and what the cache does with the files at the base commit."""
import support.paths  # noqa: F401
from support import homes

from tlkernel import adrfiles, adrs
from tlkernel.adrs import AdrStore
from tlkernel.ledger import Adr

REPO = "/r/adr-files"


def adr(n: int = 1, retired_t: float | None = None, retired_by: str = "") -> Adr:
    return Adr(id=f"ADR-{n}", n=n, repo=REPO, text="Saves stay in format v1.", question="Which format?", answer="v1", ask="x-1",
               bead="t-1", key="k", t=1234.5, by="denis", retired_t=retired_t, retired_by=retired_by)


def test_a_rendered_adr_parses_back_to_itself():
    for one in (adr(), adr(2, retired_t=99.5, retired_by="denis")):
        assert adrfiles.parse(adrfiles.file_name(one.n, adrfiles.title_of(one.text)), adrfiles.render(one), REPO) == one


def test_the_file_name_is_the_number_and_a_slug_of_the_title():
    assert adrfiles.file_name(7, "Saves stay: in format v1!") == "0007-saves-stay-in-format-v1.md"


def test_a_file_without_a_number_in_its_name_is_not_an_adr():
    assert adrfiles.parse("README.md", "# x") is None
    assert adrfiles.parse("docs/adr/12-short.md", "# x") is None
    assert [a.id for a in adrfiles.parse_all({"docs/adr/0002-b.md": adrfiles.render(adr(2)), "docs/adr/0001-a.md": adrfiles.render(adr()),
                                              "docs/adr/index.md": "x"}, REPO)] == ["ADR-1", "ADR-2"]


def test_the_template_carries_the_ask_and_the_decision_for_the_lane_that_lands_it():
    body = adrfiles.template("x-1", "t-1", "k", "Which format?", "v1", "Saves stay in format v1.", "denis", 5.0)
    assert "docs/adr/NNNN-" in body and "- Ask: x-1\n" in body and "Saves stay in format v1." in body


def test_sync_makes_the_cache_say_what_the_files_say():
    store = AdrStore.at(homes.cfg(), REPO)
    store.sync([adr(), adr(2)])
    assert [a.id for a in store.all()] == ["ADR-1", "ADR-2"]
    store.sync([adr(retired_t=9.0, retired_by="denis")])
    assert [(a.id, a.retired_t) for a in store.all()] == [("ADR-1", 9.0)]
    assert store.in_force() == []


def test_the_cache_rows_are_work_doc_rows():
    AdrStore.at(homes.cfg(), REPO).sync([adr()])
    docs = adrs.rows(homes.cfg(), REPO)
    assert docs.table == "work_doc"
    assert [k for (k,) in docs.rows.select("SELECT k FROM work_doc")][-1].endswith(":ADR-1")
