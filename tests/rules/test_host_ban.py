"""HOSTBAN (tl-e5t0.61, docs/design/stage-packages.md section 4): a converted stage takes ports and values, never a host.
Three guards, one list: the sources of the `converted-stages-take-no-host` contract in .importlinter.

1. imports: that contract (import-linter, `just rules`): a converted stage imports no `app.run`, `app.wire`, `app.launch`.
2. types: each converted stage has a ruff.toml that adds ANN401, so `host: Any` cannot be written in it (ruff, `just check`).
3. names: this file. In a converted stage no `__init__` has a parameter named host, e, eng or engine unless it is annotated with a
   Protocol the stage declares (`host: CheckHost`), and no class assigns `self.e`.
The list only grows: against the merge base with origin/main no stage may leave it (real/test_host_ban_list.py).
dev/hostban_mutation.py seeds one violation per guard and shows each guard fail."""

import pytest

from rules.host_ban import ROOT, converted, host_problems, ruff_file, stage_files, stage_protocols


@pytest.mark.parametrize("stage", converted())
def test_a_converted_stage_has_no_host_named_parameter_and_no_self_e(stage):
    known = stage_protocols(stage)
    bad = {f"{f.relative_to(ROOT)}": p for f in stage_files(stage)
           if (p := host_problems(f.read_text(encoding="utf-8"), known))}
    assert not bad, f"{stage} takes a host: {bad}"


@pytest.mark.parametrize("stage", converted())
def test_a_converted_stage_adds_ann401(stage):
    text = ruff_file(stage).read_text(encoding="utf-8")
    assert "extend = " in text and '"ANN401"' in text, f"{stage}: its ruff.toml must extend the shared config and select ANN401"


def test_the_name_guard_fails_on_a_seeded_violation():
    assert host_problems("class A:\n    def __init__(self, host):\n        self.e = host\n")
    assert host_problems("class A:\n    def __init__(self, engine: Engine): ...\n")
    assert host_problems("from typing import Any\nclass A:\n    def __init__(self, host: Any): ...\n")
    assert not host_problems("class H(Protocol): ...\nclass A:\n    def __init__(self, host: H): ...\n")
    assert not host_problems("class A:\n    def __init__(self, clock, git): ...\n")
    assert not host_problems("class H[T](Protocol): ...\nclass A[T]:\n    def __init__(self, host: H[T]): ...\n")
    assert host_problems("class A:\n    def __init__(self, host: list[str]): ...\n")
