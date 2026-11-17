"""Shared HTTP helpers: one polite session, page-to-text, and status detection."""

from __future__ import annotations

import hashlib
import html
import re
import time

import requests

USER_AGENT = "OpportunityTrackerBot/1.0 (personal student tracker; checks pages every 6h)"
TIMEOUT = 25

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en,vi;q=0.8"})
    return _session


def get(url: str, *, retries: int = 2, **kwargs) -> requests.Response:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = session().get(url, timeout=TIMEOUT, **kwargs)
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return resp
        except requests.RequestException as exc:
            last = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    assert last is not None
    raise last


_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def page_text(markup: str) -> str:
    text = _SCRIPT_STYLE.sub(" ", markup)
    text = _TAGS.sub(" ", text)
    return _SPACE.sub(" ", html.unescape(text)).strip()


def text_hash(text: str) -> str:
    # Drop digits-only tokens such as view counters and copyright years so they do not cause noise.
    stable = re.sub(r"\b\d+\b", "", text.lower())
    return hashlib.sha256(stable.encode()).hexdigest()[:16]


OPEN_PATTERNS = [
    r"applications? (?:are|is) (?:now )?open",
    r"now accepting applications",
    r"registration (?:is )?(?:now )?open",
    r"apply now",
    r"register now",
    r"submissions? (?:are|is) (?:now )?open",
]
CLOSED_PATTERNS = [
    r"applications? (?:are|is) (?:now )?closed",
    r"(?:registration|applications?|submissions?) (?:has|have) (?:now )?closed",
    r"no longer accepting",
    r"applications? closed",
    r"registration closed",
]


def detect_status(text: str, extra_open: list[str] | None = None, extra_closed: list[str] | None = None) -> str:
    low = text.lower()
    is_open = any(re.search(p, low) for p in OPEN_PATTERNS + (extra_open or []))
    is_closed = any(re.search(p, low) for p in CLOSED_PATTERNS + (extra_closed or []))
    if is_open and not is_closed:
        return "open"
    if is_closed and not is_open:
        return "closed"
    return "unknown"
