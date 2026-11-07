"""Step cursors use the recorded run and checkpoint without opening a run."""
from pathlib import Path

import pytest

from taskloop.app.pipeline.cursor import checkpoint_next, manifest_next, parse_step, stage_kind
from tlkernel.checkpoint import Checkpoint, EndRec
from tlkernel.enums import Step
from tlkernel.kinds import Kind
from tlkernel.locator import RunBundle
from tlkernel.run import RunManifest, RunState


@pytest.mark.parametrize("step", list(Step))
def test_parse_step_accepts_valid_names(step):
    assert parse_step(step.value) is step


@pytest.mark.parametrize("name", ["unknown", "", "PLAN"])
def test_parse_step_reports_choices_for_unknown_names(name):
    with pytest.raises(ValueError) as error:
        parse_step(name)
    assert str(error.value) == f"unknown stage {name!r}; choose from: {', '.join(Step)}"


@pytest.mark.parametrize(("step", "expected"), [
    (step, Kind.LANDED if step is Step.LAND else Kind.DONE if step in (Step.CLOSE, Step.REFLECT) else Kind.STAGE)
    for step in Step
])
def test_stage_kind(step, expected):
    assert stage_kind(step) is expected


@pytest.mark.parametrize(("step", "ended", "expected"), [
    ("write", EndRec(run="r1", kind="landed", fingerprint="", detail=""), Step.CLOSE),
    ("gate-red", None, Step.REPLAN),
    ("land-verify-red", None, Step.REPLAN),
    ("write", None, Step.WRITE),
    ("", None, Step.PLAN),
])
def test_checkpoint_next(step, ended, expected):
    ck = Checkpoint(bead="t-1", run="r1", t=1500.0, step=step, ended=ended)
    assert checkpoint_next(ck) is expected


@pytest.mark.parametrize(("has_last", "checkpoint_run", "checkpoint_time", "expected"), [
    (False, "r1", 1500.0, None),
    (True, None, 1500.0, Step.GATE),
    (True, "r1", 1500.0, Step.GATE),
    (True, "r2", 1500.0, None),
    (True, "r0", 999.0, Step.GATE),
    (True, "r0", 1000.0, Step.GATE),
])
def test_manifest_next(has_last, checkpoint_run, checkpoint_time, expected):
    manifest = RunManifest(run="r1", repo="/r", bead="t-1", started=1000.0, state=RunState.LOST, next_step=Step.GATE)
    path = Path("/none")
    last = RunBundle(manifest=manifest, log=path, err=path, live=path, dir=path) if has_last else None
    ck = Checkpoint(bead="t-1", run=checkpoint_run, t=checkpoint_time, step="write") if checkpoint_run is not None else None
    assert manifest_next(last, ck) is expected
