"""QueueKey (merge-queue.md section 4): a build is reusable only under an equal key; each invalidation event changes one input."""
import pytest

from taskloop.domain.land.queue_key import CHECK_SET_FIELDS, OTHER_FIELDS, QueueKey, check_set_hash
from tlkernel.ids import CheckId, TreeSha
from tlkernel.runkey import BaseSha, Digest, RunKey


def run_key(**kw: str) -> RunKey:
    """A key whose fields are all "d" but the ones in `kw`."""
    d = Digest("d")
    key = RunKey(check=CheckId("d"), cmd=d, config=d, toolchain=d, tree=TreeSha("d"), base=BaseSha("d"), inputs=d, selected=d, env=d)
    return key.replace(**kw)


def key(base: str = "m0", ahead: tuple[str, ...] = ("a", "b"), head: str = "c", check_set: Digest | None = None) -> QueueKey:
    return QueueKey(base=BaseSha(base), ahead=ahead, head=head, check_set=check_set or check_set_hash([run_key()]))


def test_every_runkey_field_is_in_the_check_set_or_accounted_for_elsewhere():
    assert set(RunKey.__struct_fields__) == set(CHECK_SET_FIELDS) | set(OTHER_FIELDS)
    assert not set(CHECK_SET_FIELDS) & set(OTHER_FIELDS)


@pytest.mark.parametrize("event, other", [
    ("main moved", key(base="m1")),
    ("head of a PR ahead changed", key(ahead=("a2", "b"))),
    ("own head changed", key(head="c2")),
    ("PR ahead ejected", key(ahead=("b",))),
    ("queue reordered", key(ahead=("b", "a"))),
    ("check set changed: the command", key(check_set=check_set_hash([run_key(cmd=Digest("other"))]))),
    ("check set changed: a check added", key(check_set=check_set_hash([run_key(), run_key(check="lint")]))),
])
def test_an_invalidation_event_changes_the_key_so_the_build_misses(event, other):
    assert key() != other, event


def test_an_equal_state_is_a_hit():
    assert key() == key()


@pytest.mark.parametrize("field", CHECK_SET_FIELDS)
def test_each_check_set_field_changes_the_hash(field):
    changed = run_key(**{field: "x"})
    assert check_set_hash([changed]) != check_set_hash([run_key()])


@pytest.mark.parametrize("field", sorted(OTHER_FIELDS))
def test_a_field_of_the_build_not_the_check_set_leaves_the_hash(field):
    assert check_set_hash([run_key(**{field: "x"})]) == check_set_hash([run_key()])


def test_the_check_set_hash_does_not_depend_on_the_order():
    a, b = run_key(), run_key(check="lint")
    assert check_set_hash([a, b]) == check_set_hash([b, a])
