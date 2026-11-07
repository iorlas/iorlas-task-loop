"""The slot count's git read is kept while the profile's source files are unchanged, however old; the slot folders are listed again."""
from typing import Any, cast

from support.case import Case

from taskloop_dash.env import Env, Ports
from taskloop_dash.readers.world import Worlds
from tlkernel.slottable import SlotSource


class SlotSourceCache(Case):
    def setup_method(self):
        self.now, self.reads, self.stamp, self.dirs = 0.0, 0, ("s", 1), frozenset({"s1"})

        def read(repo):
            self.reads += 1
            return SlotSource(host="h", count=4, source="origin/main", sha="abc", dirs=self.dirs, root="/r/.slots")

        ports = Ports(slot_source=read, slot_dirs=lambda root: self.dirs, profile_stamp=lambda repo: self.stamp)
        env = Env(config=".", ports=ports, clock=lambda: self.now)
        self.worlds = Worlds(*[cast(Any, x) for x in (env, None, None, None)])

    def test_a_stamped_source_is_read_once_across_the_ttl_and_again_when_it_changes(self):
        self.worlds.slot_source("/r")
        self.now += 3600
        self.worlds.slot_source("/r")
        assert self.reads == 1
        self.stamp = ("s", 2)
        self.worlds.slot_source("/r")
        assert self.reads == 2

    def test_the_folders_are_listed_again_without_a_read(self):
        self.worlds.slot_source("/r")
        self.dirs = frozenset({"s1", "s2"})
        assert self.worlds.slot_source("/r").dirs == self.dirs
        assert self.reads == 1

    def test_an_unstamped_source_is_read_again_after_thirty_seconds(self):
        self.stamp = None
        self.worlds.slot_source("/r")
        self.now += 29
        self.worlds.slot_source("/r")
        self.now += 2
        self.worlds.slot_source("/r")
        assert self.reads == 2
