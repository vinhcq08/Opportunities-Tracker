"""Tier C: opportunity sites and Vietnamese sources via RSS/Atom, sent to the Review queue."""

from __future__ import annotations

import datetime as dt
import email.utils
import re
import xml.etree.ElementTree as ET

from ..models import normalize, slug
from . import http

MAX_AGE_DAYS = 45
PER_FEED_LIMIT = 15
MAX_BYTES = 3_000_000

RELEVANT = re.compile(
    r"summer|research|intern|hackathon|competition|challenge|contest|olympiad|fellowship|scholarship|"
    r"exchange|bootcamp|award|mentorship|thực tập|học bổng|cuộc thi|hackathon|giải thưởng", re.I)
STUDENT = re.compile(r"undergrad|student|university|college|youth|bachelor|sinh viên|đại học", re.I)
GRAD_ONLY = re.compile(r"\b(phd|ph\.d|doctoral|postdoc|post-doc|master'?s?|mba|llm|postgraduate|"
                       r"erasmus mundus|joint master|graduate program(?:me)?|thạc sĩ|tiến sĩ|cao học)\b", re.I)
UNDERGRAD = re.compile(r"undergrad|bachelor|cử nhân|sinh viên năm", re.I)
OPEN_TEXT = re.compile(
    r"(open to (?:students |applicants )?(?:from )?(?:all|any) (?:nationalit\w+|countries)|"
    r"(?:students|applicants) (?:from )?(?:all over the world|worldwide|around the world)|"
    r"all nationalities|international students|vietnam\w*)", re.I)
DEADLINE = re.compile(r"deadline[:\s–-]*(?:is\s*)?([A-Z][a-z]+ \d{1,2},? \d{4}|\d{1,2} [A-Z][a-z]+,? \d{4})", re.I)

NOISE = re.compile(r"^\s*(danh sách|kết quả|thông báo kết quả|results?\b|winners?\b)", re.I)
INTERNSHIP = re.compile(r"\bintern(ship)?s?\b|thực tập", re.I)
# Full-time jobs and recruitment drives (kept only when they are internships).
JOB = re.compile(r"tuyển dụng|\btuyển\b|recruit|hiring|vacanc|full[- ]time|phỏng vấn|job opening|career fair|ngày hội việc làm", re.I)
# Talks, seminars and gatherings rather than programs to apply to.
EVENT = re.compile(r"seminar|webinar|workshop|\btalk\b|lecture|hội thảo|tọa đàm|chia sẻ|khám phá|office tour|"
                   r"\bsummit\b|conference|\bforum\b|meetup|open day|ngày hội", re.I)
# Limited to the students of one university (or its dormitory).
ONE_UNIVERSITY = re.compile(
    r"\bUIT\b|\bKTX\b|ký túc xá|\bĐHQG\b|sinh viên (?:của )?trường|sinh viên (?:đang học tại|thuộc)|"
    r"thư mời sinh viên|(?:only|exclusively) (?:for|open to) (?:current )?students (?:of|at|from) (?:the )?[A-Z]|"
    r"must be (?:currently )?enrolled at (?:the )?[A-Z][\w ]*Universit|students of [A-Z][\w ]*University only", re.I)
STOP = {"the", "and", "for", "program", "programme", "2026", "2027", "2028", "fully", "funded", "in", "of", "at", "a",
        "summer", "internship", "internships", "scholarship", "scholarships", "fellowship", "student", "students"}

KIND_RULES = [
    (re.compile(r"hackathon", re.I), "hackathon"),
    (re.compile(r"olympiad|contest|cuộc thi", re.I), "contest"),
    (re.compile(r"scholarship|fellowship|học bổng", re.I), "scholarship"),
    (re.compile(r"summer (?:\w+ )?(?:school|program|programme|course|camp)", re.I), "summer_school"),
    (re.compile(r"research|internship|thực tập", re.I), "summer_research"),
    (re.compile(r"competition|challenge|award|prize", re.I), "challenge"),
]

_ATOM = "{http://www.w3.org/2005/Atom}"


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9@]+", text.lower()) if len(t) > 2 and t not in STOP}


PROGRAM_WORD = re.compile(r"intern|fellowship|scholarship|summer|research|hackathon|challenge|award|prize|competition|olympiad", re.I)


def _program_words(text: str) -> set[str]:
    return {m.group(0).lower() for m in PROGRAM_WORD.finditer(text)}


def duplicate_of(title: str, curated: list[dict]) -> str | None:
    """The curated program a feed post is about, if any.

    The organisation's name must appear in the title, plus either a distinctive word from the program's
    name or the same kind of program word ("OIST Internship" vs "OIST Research Internship").
    """
    words = _tokens(title)
    kinds = _program_words(title)
    for c in curated:
        org = _tokens(c.get("org", ""))
        if not org or not org <= words:
            continue
        name = c.get("name", "")
        if (_tokens(name) - org) & words or kinds & _program_words(name):
            return c["id"]
    return None


def fetch(feeds: list[dict], today: dt.date, curated: list[dict] | None = None) -> tuple[list[dict], dict[str, str]]:
    items, report = [], {}
    for feed in feeds:
        try:
            resp = http.get(feed["url"], retries=1)
            resp.raise_for_status()
            got = parse(resp.content[:MAX_BYTES], feed, today, curated or [])
            items.extend(got)
            report[feed["name"]] = f"{len(got)} items"
        except Exception as exc:
            report[feed["name"]] = f"FAILED: {type(exc).__name__}"
    return items, report


def _entries(root: ET.Element) -> list[dict]:
    out = []
    for it in root.iter("item"):
        out.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "date": it.findtext("pubDate") or "",
            "body": (it.findtext("description") or "") + " " +
                    (it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""),
        })
    for it in root.iter(f"{_ATOM}entry"):
        link = it.find(f"{_ATOM}link")
        out.append({
            "title": (it.findtext(f"{_ATOM}title") or "").strip(),
            "link": (link.get("href") if link is not None else "") or "",
            "date": it.findtext(f"{_ATOM}updated") or it.findtext(f"{_ATOM}published") or "",
            "body": (it.findtext(f"{_ATOM}summary") or "") + " " + (it.findtext(f"{_ATOM}content") or ""),
        })
    return out


def _date(text: str) -> dt.date | None:
    text = text.strip()
    if not text:
        return None
    try:
        return email.utils.parsedate_to_datetime(text).date()
    except (TypeError, ValueError):
        pass
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _deadline(text: str) -> str | None:
    m = DEADLINE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse(xml: bytes | str, feed: dict, today: dt.date, curated: list[dict] | None = None) -> list[dict]:
    root = ET.fromstring(xml)
    items = []
    for e in _entries(root):
        if not e["title"] or not e["link"].startswith("http"):
            continue
        published = _date(e["date"])
        if published and (today - published).days > MAX_AGE_DAYS:
            continue
        body = http.page_text(e["body"])
        text = f"{e['title']} {body}"
        if not RELEVANT.search(text):
            continue
        title = e["title"]
        # Skip graduate-only calls unless they also mention undergraduates.
        if GRAD_ONLY.search(title) and not UNDERGRAD.search(text):
            continue
        if not feed.get("vietnamese") and not STUDENT.search(text):
            continue
        is_internship = bool(INTERNSHIP.search(title))
        if NOISE.search(title) or EVENT.search(title) or (JOB.search(title) and not is_internship):
            continue
        if ONE_UNIVERSITY.search(text):
            continue
        if curated and duplicate_of(title, curated):
            continue
        local_job = bool(feed.get("vietnamese") and is_internship)
        if local_job:
            kind = "internship"
        else:
            kind = (next((k for rx, k in KIND_RULES if rx.search(title)), None)
                    or next((k for rx, k in KIND_RULES if rx.search(text)), "challenge"))
        deadline = _deadline(text)
        if deadline and deadline < today.isoformat():
            continue
        found = OPEN_TEXT.search(text)
        snippet = ""
        if found:
            start = max(0, found.start() - 60)
            snippet = "…" + text[start:found.end() + 60].strip() + "…"
        items.append(normalize({
            "id": f"rss-{slug(e['link'])}",
            "source": f"feed: {feed['name']}",
            "kind": kind,
            "org": feed["name"],
            "name": e["title"][:140],
            "url": e["link"],
            "summary": body[:220] + ("…" if len(body) > 220 else ""),
            "region": "asia" if feed.get("vietnamese") else "global",
            "country": "Vietnam" if feed.get("vietnamese") else "",
            "status": "open" if deadline else "unknown",
            "deadline": deadline,
            # A Vietnamese job board post for an internship in Vietnam is open to students here by nature.
            "nationality_ok": "vn_ok" if local_job else "unknown",
            "notes": ("Internship posted on a Vietnamese university board." if local_job else
                      (f"Eligibility text found: {snippet}" if snippet else "No eligibility text found in the post.")
                      + " Read the official page before deciding."),
        }))
        if len(items) >= PER_FEED_LIMIT:
            break
    return items
