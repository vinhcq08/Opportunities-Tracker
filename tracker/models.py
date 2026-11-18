"""The normalized opportunity record shared by every source."""

from __future__ import annotations

import hashlib
import re

KINDS = {
    "underclassmen", "insight", "internship", "open_source", "summer_research", "summer_school",
    "scholarship", "travel_grant", "hackathon", "challenge", "business_comp", "contest",
}

# Every record carries all of these keys; sources fill what they know.
DEFAULTS = {
    "id": None,
    "source": "registry",
    "kind": "internship",
    "org": "",
    "org_type": "other",          # big_tech|government_space|university|nonprofit|local_company|other
    "featured": False,
    "name": "",
    "url": "",
    "summary": "",
    "region": "",                 # asia|europe|north_america|middle_east|global
    "country": "",
    "city": "",
    "format": "in_person",        # online|in_person|hybrid
    "class_years": [1, 2, 3, 4],
    "nationality_ok": "unknown",  # global|vn_ok|us_only|eu_only|other_restriction|unknown
    "enrollment_req": "any",      # any|vn_university_ok|us_canada_only|host_university_only|local_only
    "funding": "",                # fully_funded|stipend|travel_covered|free|fee_required|""
    "prize": "",
    "team_size": "",
    "themes": [],
    "status": "unknown",          # open|upcoming|closed|unknown
    "window": [],                 # months (1-12) the application window usually covers
    "deadline": None,             # YYYY-MM-DD, interpreted as 23:59 Vietnam time
    "verified": False,            # True once a human checked eligibility on the official page
    "manual_check": False,        # True for sites that block automatic checks; status is never scraped
    "notes": "",
    # Filled by the pipeline:
    "eligible_for_me": "check",   # eligible|likely|check|not_eligible
    "elig_reasons": [],
    "page_hash": None,
    "fetch_error": None,
    "first_seen": None,
    "last_changed": None,
    "last_checked": None,
}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or hashlib.sha1(text.encode()).hexdigest()[:10]


def normalize(raw: dict) -> dict:
    rec = {**DEFAULTS, **{k: v for k, v in raw.items() if v is not None}}
    # Copy mutable defaults so records never share a list.
    for key in ("class_years", "themes", "window", "elig_reasons"):
        rec[key] = list(rec[key])
    if not rec["id"]:
        rec["id"] = f"{rec['source']}-{slug(rec['org'] + ' ' + rec['name'])}"
    if rec["kind"] not in KINDS:
        raise ValueError(f"{rec['id']}: unknown kind {rec['kind']!r}")
    if rec["deadline"] is not None:
        rec["deadline"] = str(rec["deadline"])
    return rec
