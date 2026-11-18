"""Tier D: company job boards (Greenhouse, Lever), kept to internships in Vietnam, Singapore or remote APAC."""

from __future__ import annotations

import datetime as dt
import re

from ..models import normalize
from . import http

VIETNAM = re.compile(r"vietnam|viet nam|ho chi minh|hcmc|saigon|hanoi|ha noi|da nang", re.I)
NEARBY = re.compile(r"vietnam|viet nam|ho chi minh|hcmc|saigon|hanoi|ha noi|da nang|singapore|remote.{0,12}(apac|asia)", re.I)
STUDENT_ROLE = re.compile(r"\bintern|internship|graduate|campus|student|new grad|fresher|trainee|apprentice|insight|discovery", re.I)

GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json"


def fetch(boards: dict) -> tuple[list[dict], dict[str, str]]:
    items, report = [], {}
    for token in boards.get("greenhouse") or []:
        _one(f"greenhouse:{token}", lambda t=token: parse_greenhouse(token_json(GREENHOUSE.format(token=t)), t), items, report)
    for slug_ in boards.get("lever") or []:
        _one(f"lever:{slug_}", lambda s=slug_: parse_lever(token_json(LEVER.format(slug=s)), s), items, report)
    return items, report


def _one(name, fn, items, report):
    try:
        got = fn()
        items.extend(got)
        report[name] = f"{len(got)} items"
    except Exception as exc:
        report[name] = f"FAILED: {type(exc).__name__}"


def token_json(url: str):
    resp = http.get(url, retries=1)
    resp.raise_for_status()
    return resp.json()


def _record(company: str, board: str, job_id, title: str, url: str, location: str, posted: str | None) -> dict:
    in_vn = bool(VIETNAM.search(location))
    return normalize({
        "id": f"{board}-{job_id}",
        "source": board.split("-")[0],
        "kind": "internship",
        "org": company,
        "org_type": "big_tech",
        "name": title.strip(),
        "url": url,
        "city": location,
        "country": "Vietnam" if in_vn else "Singapore" if "singapore" in location.lower() else "",
        "region": "asia",
        "status": "open",
        "nationality_ok": "vn_ok" if in_vn else "unknown",
        "notes": ("Posted " + posted if posted else "") +
                 ("" if in_vn else ". Outside Vietnam: check whether the role sponsors a work or training pass."),
    })


def parse_greenhouse(data: dict, token: str) -> list[dict]:
    out = []
    for job in data.get("jobs", []):
        loc = ((job.get("location") or {}).get("name") or "")
        title = job.get("title") or ""
        if NEARBY.search(loc) and STUDENT_ROLE.search(title):
            posted = (job.get("updated_at") or "")[:10] or None
            out.append(_record(token.replace("-", " ").title(), f"greenhouse-{token}", job.get("id"), title,
                               job.get("absolute_url", ""), loc, posted))
    return out


def parse_lever(data: list, slug_: str) -> list[dict]:
    out = []
    for job in data or []:
        cats = job.get("categories") or {}
        loc = cats.get("location") or ""
        all_locs = " ".join([loc] + (cats.get("allLocations") or []))
        title = job.get("text") or ""
        commitment = cats.get("commitment") or ""
        if NEARBY.search(all_locs) and (STUDENT_ROLE.search(title) or STUDENT_ROLE.search(commitment)):
            ms = job.get("createdAt")
            posted = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat() if ms else None
            near = ", ".join(x for x in [loc] + (cats.get("allLocations") or []) if NEARBY.search(x)) or loc
            out.append(_record(slug_.replace("-", " ").title(), f"lever-{slug_}", job.get("id"), title,
                               job.get("hostedUrl", ""), near, posted))
    return out
