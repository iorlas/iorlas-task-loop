"""The look stage on its fake ports (tests/support/look_host.py): the shots, the before pictures and the owner-look epic, no Engine."""
from types import SimpleNamespace

from support.look_host import FakeLook

from taskloop.app.look import shots
from tlartifacts import store
from tlkernel.artifact import ArtifactSlot


def test_the_epic_is_found_by_walking_the_parents(workdir):
    look = FakeLook(workdir)
    look.hand.bead_parent = "t-3"
    shows = {"t-3": SimpleNamespace(issue_type="feature", parent="t-2"), "t-2": SimpleNamespace(issue_type="epic", parent="t-0")}
    look.ports.store = SimpleNamespace(show=lambda bead, **kw: shows.get(bead))
    assert look.owner_look.look_epic() == "t-2"
    look.ports.store = SimpleNamespace(show=lambda bead, **kw: None)
    assert look.owner_look.look_epic() == "t-3"


def test_shots_are_images_capped_and_sized(workdir):
    look = FakeLook(workdir)
    d = look.facts.evidence_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.png").write_bytes(b"x")
    (d / "b.gif").write_bytes(b"x")
    (d / "big.jpg").write_bytes(b"x" * (shots.MAX_SHOT_BYTES + 1))
    assert look.pictures.shots() == ["a.png"]
    for i in range(25):
        (d / f"m{i:02d}.png").write_bytes(b"x")
    assert len(look.pictures.shots()) == shots.MAX_SHOTS


def test_before_pictures_are_the_ones_the_worker_registered_as_before_in_this_run(workdir):
    look = FakeLook(workdir)
    png = workdir / "pic.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    root = look.facts.home.artifact_store()
    look.hand.artifact_repo = "repo"
    for role, name in (("before", "home-before.png"), ("after", "home-after.png"), ("progress", "half.png")):
        store.add(root, ArtifactSlot(repo="repo", bead="t-1", run=look.facts.run_id, stage="write", attempt=1), png, name=name,
                  caption="c", role=role, now=1.0)
    store.add(root, ArtifactSlot(repo="repo", bead="t-1", run="other-run", stage="write", attempt=1), png, name="old.png",
              caption="c", role="before", now=1.0)
    assert [m.name for _, m in look.pictures.before_pictures()] == ["home-before.png"]
