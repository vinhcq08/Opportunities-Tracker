"""Tier G: Major League Hacking season events (best effort; the page layout changes between seasons)."""

from __future__ import annotations

import datetime as dt
import re

from ..models import normalize, slug
from . import http
from .devpost import ASIA


def season(today: dt.date) -> int:
    # MLH seasons are named after the spring they end in: Aug 2026 – Jul 2027 is "2027".
    return today.year + 1 if today.month >= 8 else today.year


def fetch(today: dt.date) -> list[dict]:
    resp = http.get(f"https://mlh.io/seasons/{season(today)}/events")
    resp.raise_for_status()
    return parse(resp.text)


# Classic MLH event-card markup (schema.org microdata).
_CARD = re.compile(r'<div class="event"[^>]*>(.*?)</div>\s*</div>\s*</div>', re.S)
_NAME = re.compile(r'class="event-name"[^>]*>(.*?)<', re.S)
_LINK = re.compile(r'class="event-link"[^>]*href="([^"]+)"')
_START = re.compile(r'itemprop="startDate" content="([\d-]+)"')
_END = re.compile(r'itemprop="endDate" content="([\d-]+)"')
_CITY = re.compile(r'itemprop="addressLocality"[^>]*>(.*?)<', re.S)
_REGION = re.compile(r'itemprop="addressRegion"[^>]*>(.*?)<', re.S)
_DIGITAL = re.compile(r"digital|online", re.I)


def parse(markup: str) -> list[dict]:
    items = []
    for card in _CARD.findall(markup):
        name = _first(_NAME, card)
        url = _first(_LINK, card)
        if not name or not url:
            continue
        city = _first(_CITY, card)
        region = _first(_REGION, card)
        where = f"{city} {region}".strip()
        online = bool(_DIGITAL.search(card)) and not city
        if not online and not ASIA.search(where):
            continue
        items.append(normalize({
            "id": f"mlh-{slug(name)}",
            "source": "mlh",
            "kind": "hackathon",
            "org": "MLH member event",
            "name": http.page_text(name),
            "url": url,
            "format": "online" if online else "in_person",
            "city": city,
            "country": region,
            "region": "global" if online else "asia",
            "status": "upcoming",
            "deadline": _first(_START, card),
            "nationality_ok": "unknown",
            "notes": f"Event dates {_first(_START, card)} to {_first(_END, card)}. Check the event's own rules.",
        }))
    return items


def _first(rx: re.Pattern, text: str) -> str:
    m = rx.search(text)
    return m.group(1).strip() if m else ""
