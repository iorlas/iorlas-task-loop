"""The artifact store's one writer and its checks: what lands, what is refused, and that a file without a sidecar is no artifact."""
import json
from pathlib import Path

import pytest

from tlartifacts import rules, store
from tlkernel.artifact import ArtifactSlot
from tlkernel.wire import Refused

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
JPG = b"\xff\xd8\xff\xe0" + b"x" * 64
SLOT = ArtifactSlot(repo="r-1", bead="r-9", run="r-9-1", stage="write", attempt=2)


def made(base: Path, rel: str, data: bytes = PNG) -> Path:
    f = base / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


def test_a_registered_file_lands_with_its_sidecar_under_the_stage_attempt(tmp_path):
    src = made(tmp_path, "wt/home.png")
    meta = store.add(tmp_path / "store", SLOT, src, name="home.png", caption="the home screen", role="before", now=12.5)
    dest = tmp_path / "store" / "r-1" / "r-9" / "r-9-1" / "write-2" / "home.png"
    assert dest.read_bytes() == PNG and src.exists()
    side = json.loads((dest.parent / "home.png.json").read_text())
    assert side == {"v": 1, "name": "home.png", "caption": "the home screen", "role": "before", "kind": "png",
                    "size": len(PNG), "sha256": meta.sha256, "created": 12.5}
    assert store.listing(dest.parent) == [meta]
    assert not list(dest.parent.glob("*.tmp"))


def test_a_file_without_a_sidecar_is_not_an_artifact(tmp_path):
    folder = store.folder(tmp_path, SLOT)
    made(folder, "torn.png")
    store.add(tmp_path, SLOT, made(tmp_path, "wt/a.png"), name="a.png", caption="c", role="result", now=1.0)
    assert [m.name for m in store.listing(folder)] == ["a.png"]


def test_a_name_registered_again_is_replaced_whole(tmp_path):
    store.add(tmp_path, SLOT, made(tmp_path, "wt/a.png"), name="a.png", caption="one", role="progress", now=1.0)
    again = store.add(tmp_path, SLOT, made(tmp_path, "wt/b.png", PNG + b"more"), name="a.png", caption="two", role="after", now=2.0)
    assert store.listing(store.folder(tmp_path, SLOT)) == [again]
    assert (store.folder(tmp_path, SLOT) / "a.png").read_bytes() == PNG + b"more"


BAD_NAMES = ["../a.png", "/etc/a.png", "d/a.png", "d\\a.png", ".hidden.png", "a..png", "", "a.png.json", "a.txt", "a:b.png"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_a_name_that_is_not_a_plain_picture_name_is_refused(tmp_path, name):
    with pytest.raises(Refused):
        store.add(tmp_path, SLOT, made(tmp_path, "wt/a.png"), name=name, caption="c", role="result", now=1.0)
    assert not (tmp_path / "r-1").exists()


def test_role_and_caption_are_checked(tmp_path):
    src = made(tmp_path, "wt/a.png")
    for role, caption in (("shot", "c"), ("result", ""), ("result", "x" * 201)):
        with pytest.raises(Refused):
            store.add(tmp_path, SLOT, src, name="a.png", caption=caption, role=role, now=1.0)


def test_empty_files_and_type_mismatches_are_refused_with_what_to_change(tmp_path):
    empty = made(tmp_path, "wt/e.png", b"")
    with pytest.raises(Refused, match="empty"):
        store.add(tmp_path, SLOT, empty, name="e.png", caption="c", role="result", now=1.0)
    with pytest.raises(Refused, match=r"rename it to a \.jpg name"):
        store.add(tmp_path, SLOT, made(tmp_path, "wt/j.png", JPG), name="j.png", caption="c", role="result", now=1.0)
    with pytest.raises(Refused, match="not a supported type"):
        store.add(tmp_path, SLOT, made(tmp_path, "wt/t.png", b"text, not a picture"), name="t.png", caption="c", role="result", now=1.0)


def test_the_run_total_cap_refuses_the_file_that_would_pass_it(tmp_path):
    store.add(tmp_path, SLOT, made(tmp_path, "wt/a.png"), name="a.png", caption="c", role="result", now=1.0, cap=400)
    with pytest.raises(Refused, match="would pass"):
        store.add(tmp_path, SLOT, made(tmp_path, "wt/b.png", PNG + b"y" * 500), name="b.png", caption="c", role="result", now=1.0, cap=400)
    assert [m.name for m in store.listing(store.folder(tmp_path, SLOT))] == ["a.png"]


def test_an_identical_picture_of_an_earlier_run_is_a_link_not_a_second_copy(tmp_path):
    src = made(tmp_path, "wt/a.png")
    store.add(tmp_path, SLOT, src, name="a.png", caption="c", role="result", now=1.0)
    later = SLOT.replace(run="r-9-2")
    store.add(tmp_path, later, src, name="a.png", caption="c", role="result", now=2.0)
    assert (store.folder(tmp_path, SLOT) / "a.png").stat().st_ino == (store.folder(tmp_path, later) / "a.png").stat().st_ino


def test_the_source_must_be_a_real_file_inside_the_working_folder(tmp_path):
    wt = tmp_path / "wt"
    ok = made(wt, "shots/a.png")
    assert rules.source(wt, "shots/a.png") == Path(wt.resolve(), "shots/a.png")
    assert rules.source(wt, str(ok)) == Path(wt.resolve(), "shots/a.png")
    outside = made(tmp_path, "other/b.png")
    (wt / "link.png").symlink_to(outside)
    (wt / "dir").symlink_to(outside.parent)
    for bad in ("../other/b.png", str(outside), "link.png", "dir/b.png", "missing.png", "shots"):
        with pytest.raises(Refused):
            rules.source(wt, bad)


def test_a_source_path_with_a_secret_looking_part_is_refused(tmp_path):
    for rel in (".env/a.png", "keys/id_rsa.png", "my_token.png", "secrets/a.png"):
        made(tmp_path, rel)
        with pytest.raises(Refused, match="secret"):
            rules.source(tmp_path, rel)
