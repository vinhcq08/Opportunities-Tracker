"""The weekly digest: one message each Monday morning (Vietnam time) with what closes soon and what is new.

It is sent on the first run on or after Monday 07:00 in Vietnam. The week it was sent is stored in
opportunities.json, so a week is never sent twice, and a missed Monday is sent by the next run.
If no channel is set up, nothing is stored, so the digest goes out as soon as one is added.
"""

from __future__ import annotations

import datetime as dt
import html
import re

ICT = dt.timezone(dt.timedelta(hours=7))
SEND_FROM_HOUR = 7          # Monday 07:00 Vietnam time
CLOSING_DAYS = 14
SHOWN = ("eligible", "likely", "check")
LIMITS = {"closing": 12, "new": 10, "updates": 8}

LABEL_TEXT = {"eligible": "eligible", "likely": "likely open to you", "check": "check the rules"}
KIND_TEXT = {
    "summer_research": "Summer research", "summer_school": "Summer school", "hackathon": "Hackathon",
    "challenge": "Innovation challenge", "business_comp": "Business competition", "underclassmen": "Year 1–2 program",
    "insight": "Insight program", "open_source": "Open source", "scholarship": "Scholarship",
    "travel_grant": "Travel grant", "contest": "Contest", "internship": "Internship",
}
# The dashboard's colours, as Discord embed colours.
COLORS = {"closing": 0xFF6A4D, "new": 0xC6F432, "updates": 0xB9C6FF, "health": 0xFFC23D, "quiet": 0x2B3BFF}

# Discord limits: 4096 characters per embed description, 6000 across a message's embeds.
DESC_LIMIT = 3800
TOTAL_LIMIT = 5600
TELEGRAM_LIMIT = 3900


def week_key(day: dt.date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def is_due(now: dt.datetime, state: dict | None) -> bool:
    local = now.astimezone(ICT)
    if (state or {}).get("week") == week_key(local.date()):
        return False
    return local.weekday() > 0 or local.hour >= SEND_FROM_HOUR


def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _when(value: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _is_noise(item: dict) -> bool:
    # Same rule as the dashboard's Overview: small Devpost hackathons stay on the Compete tab.
    return item.get("source") == "devpost" and not item.get("featured")


def _shown(item: dict) -> bool:
    return item.get("eligible_for_me") in SHOWN


def _rank(item: dict) -> tuple:
    deadline = _date(item.get("deadline")) or dt.date.max
    return (not item.get("featured"), SHOWN.index(item["eligible_for_me"]), deadline, item["name"].lower())


def _short_date(d: dt.date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _until(days: int) -> str:
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"


def _week_title(day: dt.date) -> str:
    start = day - dt.timedelta(days=day.weekday())
    end = start + dt.timedelta(days=6)
    if start.month == end.month:
        span = f"{start.day}–{end.day} {end:%b %Y}"
    elif start.year == end.year:
        span = f"{start.day} {start:%b} – {end.day} {end:%b %Y}"
    else:
        span = f"{start.day} {start:%b %Y} – {end.day} {end:%b %Y}"
    return f"Weekly digest · {span}"


def _line(item: dict, *, lead: str = "", extra: tuple[str, ...] = ()) -> dict:
    bits = [KIND_TEXT.get(item["kind"], item["kind"]), *extra, LABEL_TEXT[item["eligible_for_me"]]]
    return {"lead": lead, "name": item["name"], "url": item.get("url") or "", "bits": [b for b in bits if b]}


def build(items: list[dict], changes: list[dict], problems: list[str], now: dt.datetime, site_url: str = "") -> dict:
    today = now.astimezone(ICT).date()
    week_ago = now - dt.timedelta(days=7)
    shown = [i for i in items if _shown(i)]
    listed: set[str] = set()
    sections: list[dict] = []

    # 1. Closing within two weeks.
    closing, small_hacks = [], 0
    for item in shown:
        d = _date(item.get("deadline"))
        if d is None or item.get("status") == "closed" or not 0 <= (d - today).days <= CLOSING_DAYS:
            continue
        if _is_noise(item):
            small_hacks += 1
            continue
        closing.append((d, item))
    closing.sort(key=lambda p: (p[0], _rank(p[1])))
    lines = []
    for d, item in closing[:LIMITS["closing"]]:
        days = (d - today).days
        lead = f"{_short_date(d)} ({_until(days)})"
        extra = () if item.get("deadline_confirmed") else ("date unconfirmed",)
        lines.append(_line(item, lead=lead, extra=extra))
        listed.add(item["id"])
    more = []
    if len(closing) > LIMITS["closing"]:
        more.append(f"…and {len(closing) - LIMITS['closing']} more on the tracker")
    if small_hacks:
        more.append(f"{small_hacks} smaller Devpost hackathon{'s' if small_hacks != 1 else ''} also close; see Compete")
    if lines or more:
        sections.append({"key": "closing", "title": f"Closing in the next {CLOSING_DAYS} days", "lines": lines,
                         "more": " · ".join(more)})

    # 2. New this week.
    fresh = [i for i in shown if not _is_noise(i) and i["id"] not in listed
             and (_when(i.get("first_seen")) or now) >= week_ago and i.get("status") != "closed"]
    fresh.sort(key=_rank)
    lines = [_line(i, extra=("Online",) if i.get("format") == "online" else (i.get("country") or "",))
             for i in fresh[:LIMITS["new"]]]
    listed.update(i["id"] for i in fresh[:LIMITS["new"]])
    if lines:
        more = f"…and {len(fresh) - LIMITS['new']} more on the tracker" if len(fresh) > LIMITS["new"] else ""
        sections.append({"key": "new", "title": "New this week", "lines": lines, "more": more})

    # 3. Programs that opened or got a new deadline this week.
    by_id = {i["id"]: i for i in shown if not _is_noise(i)}
    lines, seen = [], set()
    for c in changes:  # newest first
        if c.get("type") not in ("opened", "deadline") or c["id"] in listed or c["id"] in seen:
            continue
        at = _when(c.get("at"))
        item = by_id.get(c["id"])
        if item is None or at is None or at < week_ago:
            continue
        if c["type"] == "opened":
            if item.get("status") != "open":
                continue
            lead = "Now open"
        else:
            d = _date(item.get("deadline"))
            if d is None or d < today:
                continue
            lead = f"Deadline {d.day} {d:%b %Y}" + ("" if item.get("deadline_confirmed") else " (unconfirmed)")
        seen.add(c["id"])
        lines.append(_line(item, lead=lead))
    updates = len(lines)
    if lines:
        more = f"…and {updates - LIMITS['updates']} more on the tracker" if updates > LIMITS["updates"] else ""
        sections.append({"key": "updates", "title": "Opened or dated this week", "lines": lines[:LIMITS["updates"]],
                         "more": more})

    # 4. Sources that need fixing (the dashboard footer shows the same).
    if problems:
        sections.append({"key": "health", "title": "Sources needing attention",
                         "lines": [{"lead": "", "name": p, "url": "", "bits": []} for p in problems], "more": ""})

    if not any(s["key"] in ("closing", "new", "updates") for s in sections):
        sections.insert(0, {"key": "quiet", "title": "A quiet week",
                            "lines": [{"lead": "", "name": f"Nothing new and nothing closing in the next {CLOSING_DAYS} days.",
                                       "url": "", "bits": []}], "more": ""})

    summary = " · ".join(t for t in (
        f"{len(closing)} closing within 2 weeks" if closing else "",
        f"{len(fresh)} new" if fresh else "",
        f"{updates} opened or dated" if updates else "",
    ) if t) or "Nothing urgent this week"
    return {"title": _week_title(today), "summary": summary, "sections": sections, "site_url": site_url}


# ---------- rendering ----------

def _discord_escape(text: str) -> str:
    # Titles come from other websites: keep them from forming links or formatting.
    # (Mentions cannot ping: every message sets allowed_mentions to nothing.)
    text = text.replace("[", "(").replace("]", ")")
    return re.sub(r"([\\*_~`|])", r"\\\1", text)


def _safe_url(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29") if url.startswith(("http://", "https://")) else ""


def _discord_line(line: dict) -> str:
    name = _discord_escape(line["name"])
    url = _safe_url(line["url"])
    parts = [f"**{_discord_escape(line['lead'])}**"] if line["lead"] else []
    parts.append(f"[{name}]({url})" if url else name)
    parts += [_discord_escape(b) for b in line["bits"]]
    return "- " + " · ".join(parts)


def _section_text(section: dict, render) -> str:
    rows = [render(line) for line in section["lines"]]
    if section.get("more"):
        rows.append(f"*{section['more']}*")
    return "\n".join(rows)


def to_discord(digest: dict) -> dict:
    site = digest["site_url"]
    embeds = []
    for section in digest["sections"]:
        desc = _section_text(section, _discord_line)
        while len(desc) > DESC_LIMIT and section["lines"]:
            section = {**section, "lines": section["lines"][:-1], "more": "…more on the tracker"}
            desc = _section_text(section, _discord_line)
        embed = {"title": section["title"], "description": desc, "color": COLORS[section["key"]]}
        if site:
            embed["url"] = site
        embeds.append(embed)
    # Keep the whole message under Discord's limit by shortening the longest section.
    while sum(len(e["title"]) + len(e["description"]) for e in embeds) > TOTAL_LIMIT:
        longest = max(embeds, key=lambda e: len(e["description"]))
        rows = longest["description"].split("\n")
        longest["description"] = "\n".join(rows[:-2] + ["*…more on the tracker*"]) if len(rows) > 2 else rows[0][:500]
    content = f"**{digest['title']}**\n{digest['summary']}"
    if site:
        content += f"\n<{site}>"
    payload = {"username": "Opportunity Tracker", "content": content, "embeds": embeds[:10],
               "allowed_mentions": {"parse": []}}
    if site:
        payload["avatar_url"] = site.rstrip("/") + "/icons/icon-192.png"
    return payload


def _tg_line(line: dict) -> str:
    name = html.escape(line["name"])
    url = _safe_url(line["url"])
    parts = [f"<b>{html.escape(line['lead'])}</b>"] if line["lead"] else []
    parts.append(f'<a href="{html.escape(url, quote=True)}">{name}</a>' if url else name)
    parts += [html.escape(b) for b in line["bits"]]
    return "• " + " · ".join(parts)


def to_telegram(digest: dict) -> list[str]:
    """Telegram HTML messages, split at line breaks to stay under its length limit."""
    blocks = [f"<b>{html.escape(digest['title'])}</b>\n{html.escape(digest['summary'])}"]
    for section in digest["sections"]:
        rows = [_tg_line(line) for line in section["lines"]]
        if section.get("more"):
            rows.append(f"<i>{html.escape(section['more'])}</i>")
        blocks.append(f"<b>{html.escape(section['title'])}</b>\n" + "\n".join(rows))
    if digest["site_url"]:
        blocks.append(html.escape(digest["site_url"]))
    messages, current = [], ""
    for row in "\n\n".join(blocks).split("\n"):
        if current and len(current) + len(row) + 1 > TELEGRAM_LIMIT:
            messages.append(current)
            current = ""
        current = f"{current}\n{row}" if current else row[:TELEGRAM_LIMIT]
    if current:
        messages.append(current)
    return messages


def to_text(digest: dict) -> str:
    """Plain text, for the run log."""
    out = [digest["title"], digest["summary"]]
    for section in digest["sections"]:
        out.append(f"\n{section['title']}")
        for line in section["lines"]:
            out.append("- " + " · ".join([p for p in (line["lead"], line["name"], *line["bits"]) if p]))
        if section.get("more"):
            out.append(f"  {section['more']}")
    if digest["site_url"]:
        out.append(f"\n{digest['site_url']}")
    return "\n".join(out)
