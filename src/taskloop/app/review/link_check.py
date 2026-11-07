"""The links a task adds to a text file, opened from the engine's host (the writer's sandbox has no network)."""
from typing import Any

from taskloop.adapters import links
from taskloop.app.review.host import ReviewHand, ReviewPorts
from taskloop.app.review.state import ReviewLive
from taskloop.contracts.stagefacts import RunFacts
from taskloop.domain.matchers import clip
from taskloop.domain.review.findings import engine_finding
from taskloop.domain.review.matchers import Wording

Answer = dict[str, Any]  # a review answer: the dict the reviewer wrote

LINK_CAP = 200  # links opened per review


class LinkCheck:
    def __init__(self, facts: RunFacts, ports: ReviewPorts, live: ReviewLive, hand: ReviewHand) -> None:
        self.facts, self.ports, self.live, self.hand = facts, ports, live, hand

    def link_judged(self, review: Answer) -> None:
        """tl-bxk.7: every link the task adds to a text file is opened from the engine's host (the writer's sandbox has no network,
        and 'verified' there means nothing). One that does not open is a finding for the writer: replace it, or write `unverified` on
        its line; a link marked unverified lands as an item for the owner with the claim it carries (a bot-blocking site answers
        403 from here and opens for a person). Opened links are not asked again."""
        if not self.facts.cfg.check_links:
            return
        try:
            found = links.added_urls(self.ports.checkout.task_diff())
        except Exception as err:  # no diff to read is no check, never a failed run
            self.ports.warn(f"link check skipped: {err}")
            return
        todo = [u for _, _, u in found if u not in self.live.link_ok]
        if not todo:
            return
        todo = [u for u in todo if self.live.link_tries.get(u, 0) < 2][:LINK_CAP]  # each link is opened twice at most, 200 per review
        try:
            got = links.check_all(todo, fn=self.live.link_fn or links.check)
        except Exception as err:  # opening links must never stop a run
            self.ports.warn(f"link check skipped: {err}")
            return
        if len(got) >= 3 and all(not ok and links.network_down(why) for ok, why in got.values()):
            first = next(iter(got.values()))[1]
            self.ports.warn(f"link check skipped: none of {len(got)} links could be reached at all ({first}): this host looks offline")
            return
        self.remember(got)
        self.report(found, review)

    def remember(self, got: dict[str, tuple[bool, str]]) -> None:
        for url, (ok, why) in got.items():
            self.live.link_tries[url] = self.live.link_tries.get(url, 0) + 1
            if ok:
                self.live.link_ok.add(url)
                self.live.link_bad.pop(url, None)
            elif why != links.UNKNOWN:  # out of time is no verdict
                self.live.link_bad[url] = why

    def report(self, found: list[tuple[str, str, str]], review: Answer) -> None:
        seen: set[tuple[str, str]] = set()
        for path, line, url in found:
            why = self.live.link_bad.get(url)
            if url in self.live.link_ok or not why or (path, url) in seen:
                continue
            seen.add((path, url))
            if Wording.marked_unverified(line):
                self.hand.routing.add_unverified({"what": f"{clip(line, 200)} (link: {url})", "kind": "external_fact", "source": url},
                                 f"the engine could not open {url} ({why}); the owner checks it")
                continue
            review["findings"].append(engine_finding(path, 0, (
                f"the link {url} did not open from the engine's host ({why}). Replace it with a source that opens. If the site only blocks "
                "bots, keep it and write `unverified` on the same line, so the owner is asked about the claim it carries. Never "
                "call a link verified that you could not open."), f"a reader who follows {url} gets an error ({why})"))
