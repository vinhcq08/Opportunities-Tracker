"""Write deadlines as an iCalendar feed that Google Calendar, Apple Calendar or Outlook can subscribe to."""

from __future__ import annotations

import datetime as dt

SHOWN = {"eligible", "likely", "check"}
REMINDERS = (14, 3)  # days before the deadline


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold to 75 octets per RFC 5545, continuing lines with a leading space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 75:
            out.append(cur.decode("utf-8"))
            cur = b" " + b
        else:
            cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def build(items: list[dict], today: dt.date, now: dt.datetime, site_url: str = "") -> str:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Opportunity Tracker//Deadlines//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:Opportunity deadlines", "X-WR-TIMEZONE:Asia/Ho_Chi_Minh",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
    ]
    dated = [i for i in items if i.get("deadline") and i.get("eligible_for_me") in SHOWN]
    for item in sorted(dated, key=lambda i: (i["deadline"], i["name"])):
        try:
            day = dt.date.fromisoformat(item["deadline"])
        except ValueError:
            continue
        if day < today:
            continue
        label = {"eligible": "Eligible", "likely": "Likely eligible", "check": "Check rules"}[item["eligible_for_me"]]
        desc = f"{item.get('org', '')}. {label}. {item.get('summary', '')}\n{item.get('url', '')}"
        if site_url:
            desc += f"\nTracker: {site_url}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{item['id']}@opportunity-tracker",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(day + dt.timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_esc(('Deadline: ' if item.get('deadline_confirmed') else 'Deadline (unconfirmed): ') + item['name'])}",
            f"DESCRIPTION:{_esc(desc)}",
            f"URL:{item.get('url', '')}",
            "TRANSP:TRANSPARENT",
        ]
        for days in REMINDERS:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(item['name'] + f' closes in {days} days')}",
                      f"TRIGGER:-P{days}D", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
