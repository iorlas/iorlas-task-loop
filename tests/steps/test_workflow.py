"""The workflow loader: a valid file loads frozen; every refusal is a typed reason, found from bytes alone."""

import pytest

from taskloop import discussion, earlier_input, input_context
from taskloop.frame_markers import RESERVED
from taskloop.harness_choice import HarnessKind
from taskloop.workflow import MAX_BYTES, Reason, Renderer, Workflow, WorkflowRefused, load

VALID = b"""
[step.plan.agent]
harness = "codex"
model = "gpt-6.1-sol"
effort = "high"
[[step.plan.prompt]]
text = \"\"\"\\
First assess depth.
Then plan.\"\"\"
[[step.plan.prompt]]
use = "task"
[[step.plan.prompt]]
use = "input_context"
[step.implement.agent]
compaction_token_limit = 1000
[[step.implement.prompt]]
use = "input_context"
[[step.feedback]]
text = "The check failed."
"""
CONTEXT_ONLY = b'[[step.%b.prompt]]\nuse = "input_context"\n'
PLAN = CONTEXT_ONLY % b"plan"
FEEDBACK = b'[[step.feedback]]\ntext = "The check failed."\n'
IMPLEMENT = CONTEXT_ONLY % b"implement" + FEEDBACK


def refused(data: bytes) -> WorkflowRefused:
    result = load(data)
    assert isinstance(result, WorkflowRefused)
    return result


def test_a_valid_file_loads_with_its_agent_choice_sections_and_order() -> None:
    result = load(VALID)
    assert isinstance(result, Workflow)
    plan, implement = result.step.plan, result.step.implement
    assert (plan.agent.harness, plan.agent.model, plan.agent.effort) == (HarnessKind.CODEX, "gpt-6.1-sol", "high")
    assert implement.agent.model is None and implement.agent.compaction_token_limit == 1000
    assert [(each.text, each.use) for each in plan.prompt] == [
        ("First assess depth.\nThen plan.", None),
        (None, Renderer.TASK),
        (None, Renderer.INPUT_CONTEXT),
    ]
    assert result.model_config["frozen"]


@pytest.mark.parametrize(
    ("data", "reason", "where"),
    [
        (b"#" * (MAX_BYTES + 1), Reason.TOO_LARGE, ""),
        (b"= =", Reason.NOT_TOML, ""),
        (b"\xff\xfe", Reason.NOT_TOML, ""),
        (PLAN + IMPLEMENT + b"[step.check]\nx = 1\n", Reason.UNKNOWN_KIND, "step.check"),
        (b"name = 'x'\n" + PLAN + IMPLEMENT, Reason.UNKNOWN_KEY, "name"),
        (PLAN + IMPLEMENT + b"[step.plan.agent]\nsandbox = 'x'\n", Reason.UNKNOWN_KEY, "step.plan.agent.sandbox"),
        (
            PLAN + b'[[step.implement.prompt]]\nuse = "task"\n[[step.implement.prompt]]\nuse = "input_context"\n[[step.implement.prompt]]\n'
            b'use = "diff"\n',
            Reason.UNKNOWN_RENDERER,
            "step.implement.prompt.2.use",
        ),
    ],
)
def test_a_refusal_is_a_typed_reason_with_the_offending_path(data: bytes, reason: Reason, where: str) -> None:
    assert refused(data) == WorkflowRefused(reason, where)


@pytest.mark.parametrize("name", RESERVED)
def test_a_text_section_may_not_hold_a_factory_block_name(name: str) -> None:
    data = PLAN + IMPLEMENT + f'[[step.plan.prompt]]\ntext = "see BEGIN {name}"\n'.encode()
    assert refused(data) == WorkflowRefused(Reason.RESERVED_MARKER, "step.plan.prompt.1")


@pytest.mark.parametrize(
    "data",
    [
        PLAN,  # the implement step is missing
        IMPLEMENT,  # the plan step is missing
        PLAN + IMPLEMENT + CONTEXT_ONLY % b"plan",  # input_context twice
        b'[[step.plan.prompt]]\nuse = "task"\n' + IMPLEMENT,  # input_context never
        PLAN + IMPLEMENT + b'[[step.plan.prompt]]\ntext = "a"\nuse = "task"\n',  # both text and use
        PLAN + IMPLEMENT + b"[[step.plan.prompt]]\n",  # neither
        PLAN + CONTEXT_ONLY % b"implement",  # no feedback section
        PLAN + IMPLEMENT + b'[[step.feedback]]\nuse = "task"\n',  # a feedback section is verbatim text
        PLAN + IMPLEMENT + b'[[step.plan.prompt]]\ntext = "   "\n',  # empty text
        PLAN + IMPLEMENT + b"[step.plan.agent]\nharness = 'nope'\n",
        PLAN + IMPLEMENT + b"[step.plan.agent]\nmodel = 3\n",
        PLAN + IMPLEMENT + b'[step.plan.agent]\nmodel = ""\n',  # empty: refused, never silently ignored
        PLAN + IMPLEMENT + b"[step.plan.agent]\neffort = 'two words'\n",
        PLAN + IMPLEMENT + b"[step.implement.agent]\ncompaction_token_limit = 0\n",
    ],
)
def test_a_wrong_shape_or_value_is_bad_value(data: bytes) -> None:
    assert refused(data).reason in (Reason.BAD_VALUE, Reason.UNKNOWN_KEY)  # a missing kind is a missing key, not an unknown one


def test_the_block_names_a_file_may_not_use_are_the_ones_the_factory_frames_with() -> None:
    for begin in (input_context.BEGIN, discussion.BEGIN, earlier_input.BEGIN):
        assert any(begin == f"BEGIN {name}" for name in RESERVED)
