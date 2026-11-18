"""Tier G: Major League Hacking season events, kept to online events and events in Asia.

MLH lists events at mlh.com/seasons/<year>/events. Each event card is an
``<a ... itemType="https://schema.org/Event">`` element with schema.org microdata
(<meta itemProp="startDate" content="...">, eventAttendanceMode, addressCountry, ...).
"""

from __future__ import annotations

import datetime as dt
import html
import re
from urllib.parse import parse_qs, urlparse

from ..models import normalize, slug
from . import http

BASE = "https://www.mlh.com/seasons/{season}/events"

# ISO country codes treated as "near Vietnam".
ASIA_COUNTRIES = {"VN", "SG", "TH", "MY", "ID", "PH", "KH", "LA", "MM", "JP", "KR", "TW", "HK"}


def season(today: dt.date) -> int:
    # MLH seasons are named after the spring they end in: Aug 2026 – Jul 2027 is "2027".
    return today.year + 1 if today.month >= 8 else today.year


def fetch(today: dt.date) -> list[dict]:
    resp = http.get(BASE.format(season=season(today)))
    resp.raise_for_status()
    return parse(resp.text, today)


_CARD = re.compile(r'<a\s+href="([^"]+)"[^>]*itemtype="https://schema\.org/Event"[^>]*>(.*?)</a>', re.S | re.I)
_PLACE = re.compile(r'<div[^>]*itemprop="location".*?</div>\s*</div>', re.S | re.I)


def _meta(prop: str, text: str) -> str:
    m = re.search(rf'itemprop="{prop}"\s+content="([^"]*)"', text, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def _name(url: str, body: str) -> str:
    without_place = _PLACE.sub(" ", body)
    m = re.search(r'itemprop="name"[^>]*>(.*?)</', without_place, re.S | re.I) or \
        re.search(r"<h[2-4][^>]*>(.*?)</h[2-4]>", without_place, re.S | re.I)
    if m and http.page_text(m.group(1)):
        return http.page_text(m.group(1))
    # MLH tags every outbound link with the event name.
    content = parse_qs(urlparse(html.unescape(url)).query).get("utm_content", [""])[0]
    return content.strip()


def parse(markup: str, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    items, seen = [], set()
    for href, body in _CARD.findall(markup):
        url = _meta("url", body) or html.unescape(href).split("?")[0]
        name = _name(href, body)
        if not name or url in seen:
            continue
        seen.add(url)
        start = _meta("startDate", body)[:10]
        end = _meta("endDate", body)[:10]
        if end and end < today.isoformat():
            continue
        mode = _meta("eventAttendanceMode", body)
        online = "Online" in mode
        hybrid = "Mixed" in mode
        country = _meta("addressCountry", body).upper()
        city = _meta("addressLocality", body)
        if not (online or hybrid) and country not in ASIA_COUNTRIES:
            continue
        items.append(normalize({
            "id": f"mlh-{slug(name)}",
            "source": "mlh",
            "kind": "hackathon",
            "org": "MLH member event",
            "name": name,
            "url": url,
            "format": "online" if online else "hybrid" if hybrid else "in_person",
            "city": "" if online else city,
            "country": "" if online else country,
            "region": "asia" if country in ASIA_COUNTRIES else "global",
            "status": "upcoming",
            "deadline": start or None,
            "deadline_confirmed": True,  # MLH's own listing (event start date)
            "nationality_ok": "unknown",
            "notes": f"Event runs {start} to {end}. Check the event's own rules.",
        }))
    return items
