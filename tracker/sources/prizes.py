"""Tier H: Kaggle competitions (needs an API key) and Challenge.gov prize challenges."""

from __future__ import annotations

import os
import re

from ..models import normalize, slug
from . import http

KAGGLE = "https://www.kaggle.com/api/v1/competitions/list"
CHALLENGE_GOV = [
    "https://api.challenge.gov/api/challenges?status=active",
    "https://www.challenge.gov/api/challenges?status=active",
]
US_ONLY = re.compile(r"citizen|permanent resident|united states|u\.s\.|\bUS\b", re.I)
OPEN = re.compile(r"open to (?:all|anyone|individuals worldwide)|international|global|any country", re.I)


def fetch_kaggle() -> list[dict]:
    user, key = os.environ.get("KAGGLE_USERNAME", ""), os.environ.get("KAGGLE_KEY", "")
    if not (user and key):
        raise RuntimeError("no KAGGLE_USERNAME/KAGGLE_KEY secrets")
    resp = http.get(KAGGLE, auth=(user, key), params={"page": 1, "sortBy": "latestDeadline"})
    resp.raise_for_status()
    return parse_kaggle(resp.json())


def parse_kaggle(comps: list[dict]) -> list[dict]:
    items = []
    for c in comps or []:
        ref = str(c.get("ref") or c.get("url") or "")
        if not ref:
            continue
        url = ref if ref.startswith("http") else f"https://www.kaggle.com/competitions/{ref.rsplit('/', 1)[-1]}"
        category = (c.get("category") or "").lower()
        if category in {"gettingstarted", "playground", "inclass"}:
            continue
        deadline = (c.get("deadline") or "")[:10] or None
        items.append(normalize({
            "id": f"kaggle-{slug(ref)}",
            "source": "kaggle",
            "kind": "challenge",
            "org": c.get("organizationName") or "Kaggle",
            "org_type": "big_tech",
            "featured": bool(c.get("reward")) and "usd" in str(c.get("reward", "")).lower(),
            "name": c.get("title") or ref,
            "url": url,
            "summary": c.get("description") or "",
            "region": "global",
            "format": "online",
            "prize": str(c.get("reward") or ""),
            "status": "open",
            "deadline": deadline,
            "deadline_confirmed": True,  # Kaggle's own listing
            "nationality_ok": "global",
            "notes": "Prize eligibility can exclude some countries; check the competition rules.",
        }))
    return items


def fetch_challenge_gov() -> list[dict]:
    last: Exception | None = None
    for url in CHALLENGE_GOV:
        try:
            resp = http.get(url, retries=1)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                rows = data
            else:
                rows = data.get("collection") or data.get("challenges") or data.get("data") or []
            return parse_challenge_gov(rows)
        except Exception as exc:
            last = exc
    raise last or RuntimeError("no endpoint answered")


def parse_challenge_gov(rows: list[dict]) -> list[dict]:
    items = []
    for c in rows or []:
        if not isinstance(c, dict):
            continue
        title = c.get("title") or c.get("name")
        cid = c.get("id") or slug(title or "")
        if not title:
            continue
        rules = " ".join(str(c.get(k) or "") for k in ("eligibility", "rules", "terms_and_conditions"))
        nat = "us_only" if US_ONLY.search(rules) and not OPEN.search(rules) else "unknown"
        end = str(c.get("end_date") or c.get("submission_end_date") or "")[:10] or None
        items.append(normalize({
            "id": f"challengegov-{cid}",
            "source": "challenge.gov",
            "kind": "challenge",
            "org": c.get("agency_name") or c.get("agency") or "US federal agency",
            "org_type": "government_space",
            "featured": bool(re.search(r"nasa", str(c.get("agency_name") or ""), re.I)),
            "name": title,
            "url": c.get("external_url") or f"https://www.challenge.gov/?challenge={cid}",
            "summary": http.page_text(str(c.get("tagline") or c.get("brief_description") or ""))[:220],
            "region": "north_america",
            "format": "online",
            "prize": str(c.get("prize_total") or ""),
            "status": "open",
            "deadline": end,
            "nationality_ok": nat,
            "notes": "Federal prize challenges usually require US citizenship or residency; check the rules.",
        }))
    return items
