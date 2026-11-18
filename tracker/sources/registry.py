"""Tier A: the hand-curated registry in programs.yaml, refreshed by watching each official page."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import requests
import urllib3
import yaml

from ..models import normalize
from . import http

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Fields in programs.yaml that tune the watcher but are not part of the record.
WATCH_KEYS = ("watch_open", "watch_closed", "tls_fallback")


def load(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("programs", [])
    seen: set[str] = set()
    for entry in entries:
        if entry["id"] in seen:
            raise ValueError(f"duplicate id in {path}: {entry['id']}")
        seen.add(entry["id"])
    return entries


def fetch(entries: list[dict], today: dt.date, *, offline: bool = False) -> list[dict]:
    items = []
    for entry in entries:
        watch = {k: entry.get(k) or [] for k in WATCH_KEYS}
        watch["tls_fallback"] = bool(entry.get("tls_fallback"))
        rec = normalize({k: v for k, v in entry.items() if k not in WATCH_KEYS} | {"source": "registry"})
        rec["last_checked"] = None if offline else dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

        if not offline and rec["url"] and not rec["manual_check"]:
            _watch(rec, watch)

        # A passed deadline beats whatever the page says.
        if rec["deadline"] and dt.date.fromisoformat(rec["deadline"]) < today:
            rec["status"] = "closed"
        # Outside its usual window and nothing found on the page: say "upcoming" when the window is ahead.
        if rec["status"] == "unknown" and rec["window"] and today.month not in rec["window"]:
            rec["status"] = "upcoming"
        items.append(rec)
    return items


def _watch(rec: dict, watch: dict) -> None:
    try:
        resp = http.get(rec["url"], allow_redirects=True)
    except requests.exceptions.SSLError:
        if not watch["tls_fallback"]:
            rec["fetch_error"] = "SSLError"
            return
        # Some sites send an incomplete certificate chain that browsers repair but Python does not.
        # We only read public page text, so for entries marked tls_fallback we retry unverified.
        try:
            resp = http.get(rec["url"], allow_redirects=True, verify=False)
        except Exception as exc:
            rec["fetch_error"] = f"{type(exc).__name__}"
            return
    except Exception as exc:  # network errors are recorded, never fatal
        rec["fetch_error"] = f"{type(exc).__name__}"
        return
    if resp.status_code >= 400:
        rec["fetch_error"] = f"HTTP {resp.status_code}"
        return
    text = http.page_text(resp.text)
    rec["page_hash"] = http.text_hash(text)
    rec["_page_text"] = text  # read by claude_reader; never written to the published data
    found = http.detect_status(text, watch["watch_open"], watch["watch_closed"])
    if found != "unknown":
        rec["status"] = found
