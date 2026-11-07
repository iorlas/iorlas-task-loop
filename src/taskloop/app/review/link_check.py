"""The links a task adds to a text file, opened from the engine's host (the writer's sandbox has no network)."""
from typing import Any

from taskloop.adapters import links
from taskloop.app.review.host import ReviewHost
from taskloop.domain.matchers import clip
from taskloop.domain.review.findings import engine_finding
from taskloop.domain.review.matchers import Wording

Answer = dict[str, Any]  # a review answer: the dict the reviewer wrote

LINK_CAP = 200  # links opened per review


class LinkCheck:
    def __init__(self, host: ReviewHost) -> None:
        self.host = host

    def link_judged(self, review: Answer) -> None:
        """tl-bxk.7: every link the task adds to a text file is opened from the engine's host (the writer's sandbox has no network,
        and 'verified' there means nothing). One that does not open is a finding for the writer: replace it, or write `unverified` on
        its line; a link marked unverified lands as an item for the owner with the claim it carries (a bot-blocking site answers
        403 from here and opens for a person). Opened links are not asked again."""
        e = self.host
        if not e.cfg.check_links:
            return
        try:
            found = links.added_urls(e.checkout.task_diff())
        except Exception as err:  # no diff to read is no check, never a failed run
            e.warn(f"link check skipped: {err}")
            return
        todo = [u for _, _, u in found if u not in e.review.link_ok]
        if not todo:
            return
        todo = [u for u in todo if e.review.link_tries.get(u, 0) < 2][:LINK_CAP]  # each link is opened twice at most, 200 per review
        try:
            got = links.check_all(todo, fn=e.review.link_fn or links.check)
        except Exception as err:  # opening links must never stop a run
            e.warn(f"link check skipped: {err}")
            return
        if len(got) >= 3 and all(not ok and links.network_down(why) for ok, why in got.values()):
            first = next(iter(got.values()))[1]
            e.warn(f"link check skipped: none of {len(got)} links could be reached at all ({first}): this host looks offline")
            return
        self.remember(got)
        self.report(found, review)

    def remember(self, got: dict[str, tuple[bool, str]]) -> None:
        e = self.host
        for url, (ok, why) in got.items():
            e.review.link_tries[url] = e.review.link_tries.get(url, 0) + 1
            if ok:
                e.review.link_ok.add(url)
                e.review.link_bad.pop(url, None)
            elif why != links.UNKNOWN:  # out of time is no verdict
                e.review.link_bad[url] = why

    def report(self, found: list[tuple[str, str, str]], review: Answer) -> None:
        e = self.host
        seen: set[tuple[str, str]] = set()
        for path, line, url in found:
            why = e.review.link_bad.get(url)
            if url in e.review.link_ok or not why or (path, url) in seen:
                continue
            seen.add((path, url))
            if Wording.marked_unverified(line):
                e.routing.add_unverified({"what": f"{clip(line, 200)} (link: {url})", "kind": "external_fact", "source": url},
                                 f"the engine could not open {url} ({why}); the owner checks it")
                continue
            review["findings"].append(engine_finding(path, 0, (
                f"the link {url} did not open from the engine's host ({why}). Replace it with a source that opens. If the site only blocks "
                "bots, keep it and write `unverified` on the same line, so the owner is asked about the claim it carries. Never "
                "call a link verified that you could not open."), f"a reader who follows {url} gets an error ({why})"))
