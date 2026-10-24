"""Cited links of a research task, opened from the engine's host (tl-bxk.7).

lifesim-ggi: 7 of 19 links answered 403 from the host, and the writer said "verified" from a sandbox with no network. So the
engine opens every link the task adds to a text file, outside any sandbox; one that does not open goes back to the writer
(replace it, or write `unverified` on its line), and a link the writer marks unverified goes to the owner with the claim it carries.
Standard library only; the check is injectable for tests.
"""

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

TEXT_EXT = (".md", ".markdown", ".txt", ".rst", ".adoc")
URL = re.compile(r"https?://[^\s<>\"'`\]\)]+")
SKIP_HOSTS = ("localhost", "example.com", "example.org", "example.net")
SKIP_SUFFIX = (".invalid", ".test", ".local", ".localhost", ".example")
AGENT = "Mozilla/5.0 (compatible; task-loop link check; +https://github.com/iorlas)"


def skipped(url):
    """A link that points nowhere to check: this machine, a private address, a placeholder domain."""
    host = (urlparse(url).hostname or "").lower()
    if not host or host in SKIP_HOSTS or host.endswith(SKIP_SUFFIX) or any(host.endswith("." + h) for h in SKIP_HOSTS):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def added_urls(diff, exts=TEXT_EXT):
    """[(path, the line that cites it, url)] from the lines a unified diff adds to text files, each url once per line."""
    out, path = [], ""
    for ln in (diff or "").splitlines():
        if ln.startswith("+++ "):
            path = ln[4:].strip()[2:] if ln[4:6] in ("b/", "a/") else ln[4:].strip()
            path = "" if path == "/dev/null" else path
        elif ln.startswith("+") and path.lower().endswith(exts):
            seen = set()
            for m in URL.finditer(ln[1:]):
                url = m.group(0).rstrip(".,;:!?*_")
                if url not in seen and not skipped(url):
                    seen.add(url)
                    out.append((path, ln[1:].strip(), url))
    return out


def check(url, timeout=15):
    """(True, '') when the link opens, else (False, why). HEAD first, GET when a server will not answer a HEAD."""
    last = "no answer"
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status < 400:
                    return True, ""
                last = "HTTP %d" % r.status
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            if e.code not in (400, 403, 405, 406, 429, 501):  # these may only be the HEAD or the bot: GET tells
                return False, last
        except urllib.error.URLError as e:
            reason = e.reason
            return False, "no such host" if isinstance(reason, socket.gaierror) else "timeout" if isinstance(reason, socket.timeout) else str(reason)[:80]
        except (socket.timeout, TimeoutError):
            return False, "timeout"
        except (OSError, ValueError) as e:
            return False, str(e)[:80]
    return False, last


def check_all(urls, fn=check, workers=8):
    """{url: (ok, why)} for the distinct urls, opened side by side."""
    urls = sorted(set(urls))
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(urls))) as ex:
        return dict(zip(urls, ex.map(lambda u: fn(u), urls)))
