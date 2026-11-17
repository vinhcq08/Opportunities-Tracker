"""Tier G: hackathons from Devpost's public listing API, kept to online or Asia-based events."""

from __future__ import annotations

import datetime as dt
import re

from ..models import normalize
from . import http

API = "https://devpost.com/api/hackathons"
MAX_PAGES = 6
KEEP_LIMIT = 40

ASIA = re.compile(r"vietnam|viet nam|hanoi|ho chi minh|da nang|singapore|thailand|malaysia|indonesia|philippines|"
                  r"cambodia|japan|korea|taiwan|hong kong", re.I)
FEATURED_ORGS = re.compile(r"nasa|mit\b|stanford|harvard|google|microsoft|meta|amazon|aws|ibm|nvidia|intel|"
                           r"openai|anthropic|un\b|united nations|world bank|esa\b", re.I)


def fetch() -> list[dict]:
    raw: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        resp = http.get(API, params={"status[]": ["open", "upcoming"], "page": page})
        resp.raise_for_status()
        batch = resp.json().get("hackathons", [])
        if not batch:
            break
        raw.extend(batch)
    return parse(raw)


def parse(hackathons: list[dict]) -> list[dict]:
    items = []
    for h in hackathons:
        if h.get("invite_only"):
            continue
        location = ((h.get("displayed_location") or {}).get("location") or "").strip()
        online = location.lower() == "online"
        if not online and not ASIA.search(location):
            continue
        org = h.get("organization_name") or ""
        regs = h.get("registrations_count") or 0
        items.append(normalize({
            "id": f"devpost-{h['id']}",
            "source": "devpost",
            "kind": "hackathon",
            "org": org,
            "org_type": "other",
            "featured": bool(FEATURED_ORGS.search(org + " " + h.get("title", ""))) or regs >= 2000,
            "name": h.get("title", "").strip(),
            "url": h.get("url", ""),
            "format": "online" if online else "in_person",
            "country": "" if online else location,
            "region": "global" if online else "asia",
            "status": "open" if h.get("open_state") == "open" else "upcoming",
            "deadline": _end_date(h.get("submission_period_dates", "")),
            "prize": http.page_text(h.get("prize_amount") or ""),
            "themes": [t.get("name", "") for t in h.get("themes") or []][:4],
            "nationality_ok": "unknown",
            "notes": f"{regs} registered on Devpost. Check the official rules for country restrictions.",
        }))
    items.sort(key=lambda i: (not i["featured"], i["deadline"] or "9999"))
    return items[:KEEP_LIMIT]


_DATE = re.compile(r"([A-Z][a-z]{2}) (\d{1,2})(?:, (\d{4}))?")
_SAME_MONTH_END = re.compile(r"-\s*(\d{1,2}),?\s*(\d{4})?\s*$")


def _end_date(period: str) -> str | None:
    """'Nov 01 - Dec 15, 2026' -> '2026-12-15'; 'Jan 10 - 12, 2027' -> '2027-01-12'. None if unparseable."""
    parts = _DATE.findall(period)
    if not parts:
        return None
    mon, day, year = parts[-1]
    same_month = _SAME_MONTH_END.search(period)
    if same_month:  # the end has only a day number, so it shares the start's month
        mon, day = parts[0][0], same_month.group(1)
    if not year:
        years = re.findall(r"\d{4}", period)
        if not years:
            return None
        year = years[-1]
    try:
        return dt.datetime.strptime(f"{mon} {day} {year}", "%b %d %Y").date().isoformat()
    except ValueError:
        return None
