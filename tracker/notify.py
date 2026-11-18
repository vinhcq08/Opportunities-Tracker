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


def health_digest(alerts: list[str]) -> str:
    if not alerts:
        return ""
    return "**Source health**\n" + "\n".join(f"- {a}" for a in alerts)


def send(text: str) -> list[str]:
    """Send to every configured channel; return the channels that accepted it."""
    if not text:
        return []
    sent, errors = [], []
    discord = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if discord:
        try:
            resp = http.session().post(discord, json={"content": text[:1900]}, timeout=http.TIMEOUT)
            resp.raise_for_status()
            sent.append("discord")
        except Exception as exc:
            errors.append(f"discord: {type(exc).__name__}")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        try:
            resp = http.session().post(f"https://api.telegram.org/bot{token}/sendMessage",
                                       json={"chat_id": chat, "text": text.replace("**", "")[:4000],
                                             "disable_web_page_preview": True}, timeout=http.TIMEOUT)
            resp.raise_for_status()
            sent.append("telegram")
        except Exception as exc:  # never print the URL: it contains the bot token
            errors.append(f"telegram: {type(exc).__name__}")
    if errors:
        raise RuntimeError("; ".join(errors) + (f" (sent: {', '.join(sent)})" if sent else ""))
    return sent
