"""Follow-up identity, unfiltered batches and checkpoint list replacement."""
from dataclasses import dataclass, field

from tlkernel.stagefacts import LeftoverSink
from tlkernel.wire import Open
from tlpipeline.leftover_queue import LeftoverQueue


@dataclass
class Fields:
    leftovers: list[Open] = field(default_factory=list)


def queue(fields: Fields) -> LeftoverSink:
    return LeftoverQueue(fields)


def test_title_duplicates_leave_the_list_unchanged():
    fields = Fields()
    sink = queue(fields)
    first = {"title": "same", "why": "first"}
    assert sink.add_titled(first)
    assert not sink.add_titled({"title": "same", "why": "second"})
    assert fields.leftovers == [first]


def test_key_uses_file_and_category_instead_of_title():
    fields = Fields()
    sink = queue(fields)
    first = {"title": "first", "category": "bug", "file": "a.py"}
    assert sink.add_keyed("t-1", first)
    assert not sink.add_keyed("t-1", dict(first, title="different"))
    other = dict(first, category="test")
    assert sink.add_keyed("t-1", other)
    assert fields.leftovers == [first, other]


def test_extend_keeps_duplicates_and_order():
    fields = Fields([{"title": "first"}])
    sink = queue(fields)
    items = [{"title": "first"}, {"title": "last"}]
    sink.extend(items)
    assert fields.leftovers == [{"title": "first"}, *items]


def test_every_verb_reads_the_rebound_list():
    fields = Fields([{"title": "old"}])
    sink = queue(fields)
    old = fields.leftovers
    fields.leftovers = [{"title": "new"}]
    assert sink.add_titled({"title": "old"})
    assert not sink.add_titled({"title": "new"})
    assert sink.add_keyed("t-1", {"title": "keyed"})
    sink.extend([{"title": "last"}])
    assert fields.leftovers == [{"title": t} for t in ("new", "old", "keyed", "last")]
    assert old == [{"title": "old"}]
