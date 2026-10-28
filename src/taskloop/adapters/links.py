"""Cited links of a research task, opened from the engine's host (tl-bxk.7).

lifesim-ggi: 7 of 19 links answered 403 from the host, and the writer said "verified" from a sandbox with no network. So the
engine opens every link the task adds to a text file, outside any sandbox; one that does not open goes back to the writer
(replace it, or write `unverified` on its line), and a link the writer marks unverified goes to the owner with the claim it carries.
The check is injectable for tests.
"""

import functools
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, override
from urllib.parse import urlparse

TEXT_EXT = (".md", ".markdown", ".txt", ".rst", ".adoc")
URL = re.compile(r"https?://[^\s<>\"'`\]]+")
SKIP_HOSTS = ("localhost", "example.com", "example.org", "example.net")
SKIP_SUFFIX = (".invalid", ".test", ".local", ".localhost", ".example")
UNKNOWN = "not checked in time"
DEADLINE = 120  # seconds for all the links of one review
AGENT = "Mozilla/5.0 (compatible; task-loop link check; +https://github.com/iorlas)"


def trim(url: str) -> str:
    """The url without the punctuation of the sentence around it: a closing parenthesis only when it has no opener."""
    url = url.rstrip(".,;:!?*")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip(".,;:!?*")
    return url


def skipped(url: str) -> bool:
    """A link that points nowhere to check: this machine, a private address, a placeholder domain, a scheme that is not web, a
    malformed address."""
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
    except ValueError:
        return True
    if p.scheme not in ("http", "https") or not host or host in SKIP_HOSTS or host.endswith(SKIP_SUFFIX) \
            or any(host.endswith("." + h) for h in SKIP_HOSTS):
        return True
    return not public_host(host)


@functools.lru_cache(maxsize=512)
def public_host(host: str) -> bool:
    """False for a name that resolves to this machine or a private network (the check never fetches from inside), unknown names are
    left to the check itself to fail on."""
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host, None)]
        except (socket.gaierror, UnicodeError, OSError):
            return True
    return all(ip.is_global for ip in ips)


def added_urls(diff: str, exts: tuple[str, ...] = TEXT_EXT) -> list[tuple[str, str, str]]:
    """[(path, the line that cites it, url)] from the lines a unified diff adds to text files, each url once per line."""
    out: list[tuple[str, str, str]] = []
    path, prev = "", ""
    for ln in (diff or "").splitlines():
        header = ln.startswith("+++ ") and prev.startswith("--- ")  # an added line that starts with "++ " is a line, not a header
        prev = ln
        if header:
            path = ln[4:].strip()[2:] if ln[4:6] in ("b/", "a/") else ln[4:].strip()
            path = "" if path == "/dev/null" else path
        elif ln.startswith("+") and path.lower().endswith(exts):
            seen: set[str] = set()
            for m in URL.finditer(ln[1:]):
                url = trim(m.group(0))
                if url not in seen and not skipped(url):
                    seen.add(url)
                    out.append((path, ln[1:].strip(), url))
    return out


class _Public(urllib.request.HTTPRedirectHandler):
    """A redirect stays on the web and never lands on this machine or a private network."""

    @override
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if skipped(newurl):
            raise urllib.error.HTTPError(newurl, 400, "redirect to a private or non-web address", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Public)


def reason_text(reason: object) -> str:
    if isinstance(reason, socket.gaierror):
        return "no such host"
    return "timeout" if isinstance(reason, TimeoutError) else str(reason)[:80]


def check(url: str, timeout: float = 15) -> tuple[bool, str]:
    """(True, '') when the link opens, else (False, why). HEAD first, GET when a server will not answer a HEAD."""
    last = "no answer"
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": AGENT, "Accept": "*/*"})
        try:
            with _opener.open(req, timeout=timeout) as r:
                if r.status < 400:
                    return True, ""
                last = f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code not in (400, 403, 405, 406, 429, 501):  # these may only be the HEAD or the bot: GET tells
                return False, last
        except urllib.error.URLError as e:
            return False, reason_text(e.reason)
        except TimeoutError:
            return False, "timeout"
        except Exception as e:  # http.client errors (a non-HTTP server), ssl, odd addresses: a verdict, never a crash
            return False, (f"{type(e).__name__}: {e}")[:80]
    return False, last


def network_down(why: str) -> bool:
    """True for a failure that says this machine cannot reach the web, not that the link is bad."""
    return why in ("no such host", "timeout", UNKNOWN) or why.startswith(("[Errno 6", "[Errno 5", "<urlopen error"))


def check_all(urls: Any, fn: Callable[[str], tuple[bool, str]] = check, workers: int = 8,
              deadline: float = DEADLINE) -> dict[str, tuple[bool, str]]:
    """{url: (ok, why)} for the distinct urls, opened side by side, in `deadline` seconds in all: a link not done by then is UNKNOWN."""
    urls = sorted(set(urls))
    out: dict[str, tuple[bool, str]] = {}
    if not urls:
        return out
    def one(u: str) -> tuple[bool, str]:
        try:
            return fn(u)
        except Exception as e:  # a check that raises is a failed link
            return False, (f"{type(e).__name__}: {e}")[:80]
    ex = ThreadPoolExecutor(max_workers=min(workers, len(urls)))
    futs = {u: ex.submit(one, u) for u in urls}
    end = time.time() + deadline
    for u, f in futs.items():
        try:
            out[u] = f.result(timeout=max(0.0, end - time.time()))
        except Exception:
            out[u] = (False, UNKNOWN)
    ex.shutdown(wait=False)
    return out
