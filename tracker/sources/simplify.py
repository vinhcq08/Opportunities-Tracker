"""Tier F: SimplifyJobs internship feed, kept only for roles located in Vietnam or nearby."""

from __future__ import annotations

import datetime as dt
import re

from ..models import normalize
from . import http

FEED = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
NEARBY = re.compile(r"vietnam|viet nam|hanoi|ho chi minh|hcmc|da nang|singapore|remote.*(apac|asia)", re.I)
CATEGORIES = {"Software", "AI/ML/Data", "Software Engineering", "Data Science, AI & Machine Learning", "Quant", "Product"}


def fetch() -> list[dict]:
    resp = http.get(FEED)
    resp.raise_for_status()
    return parse(resp.json())


def parse(listings: list[dict]) -> list[dict]:
    items = []
    for x in listings:
        if not (x.get("active") and x.get("is_visible", True)):
            continue
        if x.get("category") not in CATEGORIES:
            continue
        locations = x.get("locations") or []
        near = [loc for loc in locations if NEARBY.search(loc)]
        if not near:
            continue
        posted = x.get("date_posted")
        items.append(normalize({
            "id": f"simplify-{x['id']}",
            "source": "simplify",
            "kind": "internship",
            "org": x.get("company_name", ""),
            "org_type": "big_tech",
            "name": x.get("title", ""),
            "url": x.get("url", ""),
            "city": ", ".join(near),
            "country": "Vietnam" if any(re.search("viet|hanoi|ho chi minh|hcmc|da nang", n, re.I) for n in near) else "Singapore",
            "region": "asia",
            "status": "open",
            "nationality_ok": "vn_ok" if any(re.search("viet|hanoi|ho chi minh|hcmc|da nang", n, re.I) for n in near) else "unknown",
            "themes": x.get("terms") or [],
            "notes": "Posted " + (dt.datetime.fromtimestamp(posted, dt.timezone.utc).date().isoformat() if posted else "recently"),
        }))
    return items
