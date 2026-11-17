"""Compare this run with the previous snapshot and record what changed."""

from __future__ import annotations

HISTORY_LIMIT = 150

TRACKED = ("status", "deadline", "eligible_for_me")


def diff(prev_items: list[dict], items: list[dict], now: str) -> list[dict]:
    """Return change events and carry first_seen/last_changed over from the previous run.

    Mutates ``items`` in place.
    """
    prev = {p["id"]: p for p in prev_items}
    changes: list[dict] = []

    for item in items:
        old = prev.get(item["id"])
        if old is None:
            item["first_seen"] = now
            item["last_changed"] = now
            changes.append(_event("new", item, now))
            continue

        item["first_seen"] = old.get("first_seen") or now
        item["last_changed"] = old.get("last_changed") or now
        changed = False

        if old.get("status") != item["status"] and item["status"] != "unknown":
            kind = {"open": "opened", "closed": "closed"}.get(item["status"], "status")
            changes.append(_event(kind, item, now, f"{old.get('status')} → {item['status']}"))
            changed = True
        if old.get("deadline") != item["deadline"] and item["deadline"]:
            changes.append(_event("deadline", item, now, f"{old.get('deadline') or 'none'} → {item['deadline']}"))
            changed = True
        if old.get("eligible_for_me") != item["eligible_for_me"]:
            changes.append(_event("eligibility", item, now, f"{old.get('eligible_for_me')} → {item['eligible_for_me']}"))
            changed = True
        if item.get("page_hash") and old.get("page_hash") and old["page_hash"] != item["page_hash"]:
            changes.append(_event("page_updated", item, now))
            changed = True
        if item.get("fetch_error") and not old.get("fetch_error"):
            changes.append(_event("broken_link", item, now, item["fetch_error"]))
            changed = True
        if changed:
            item["last_changed"] = now

    current = {i["id"] for i in items}
    for pid, old in prev.items():
        if pid not in current and old.get("source") != "registry":
            changes.append(_event("removed", old, now))
    return changes


def _event(kind: str, item: dict, now: str, detail: str = "") -> dict:
    return {
        "type": kind,
        "id": item["id"],
        "name": item["name"],
        "kind": item["kind"],
        "eligible_for_me": item.get("eligible_for_me"),
        "detail": detail,
        "at": now,
    }


def merge_history(old_history: list[dict], new_changes: list[dict]) -> list[dict]:
    return (new_changes + old_history)[:HISTORY_LIMIT]
