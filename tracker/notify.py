"""Turn this run's changes into a short digest and send it to Discord when a webhook is configured."""

from __future__ import annotations

import os

from .sources import http

LABELS = {
    "new": "New",
    "opened": "Now open",
    "closed": "Closed",
    "deadline": "Deadline changed",
    "eligibility": "Eligibility changed",
    "page_updated": "Page updated",
    "broken_link": "Broken link (check registry)",
}
# The digest only covers changes worth acting on.
WORTH_SENDING = {"new", "opened", "deadline", "eligibility", "broken_link"}


def digest(changes: list[dict], site_url: str = "") -> str:
    relevant = [c for c in changes if c["type"] in WORTH_SENDING and c.get("eligible_for_me") != "not_eligible"]
    if not relevant:
        return ""
    lines = [f"**Opportunity Tracker: {len(relevant)} update(s)**"]
    for c in relevant[:20]:
        detail = f" ({c['detail']})" if c.get("detail") else ""
        lines.append(f"- {LABELS.get(c['type'], c['type'])}: {c['name']}{detail}")
    if len(relevant) > 20:
        lines.append(f"- …and {len(relevant) - 20} more")
    if site_url:
        lines.append(site_url)
    return "\n".join(lines)


def send(text: str) -> bool:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not text or not url:
        return False
    resp = http.session().post(url, json={"content": text[:1900]}, timeout=http.TIMEOUT)
    resp.raise_for_status()
    return True
