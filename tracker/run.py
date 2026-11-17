"""Run every source, apply eligibility, diff against the last run and write web/data/opportunities.json.

    python -m tracker.run              # full run (network)
    python -m tracker.run --offline    # registry only, no network (for local design work)
    python -m tracker.run --dry-run    # print counts, write nothing, send nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

from . import diff as diffing
from . import eligibility, notify
from .sources import devpost, mlh, registry, simplify

ROOT = Path(__file__).resolve().parent.parent
ICT = dt.timezone(dt.timedelta(hours=7))


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}


def collect(today: dt.date, offline: bool) -> tuple[list[dict], dict[str, str]]:
    report: dict[str, str] = {}
    items = registry.fetch(registry.load(ROOT / "programs.yaml"), today, offline=offline)
    report["registry"] = f"{len(items)} items"
    if offline:
        return items, report

    for name, fn in (("devpost", devpost.fetch), ("mlh", lambda: mlh.fetch(today)), ("simplify", simplify.fetch)):
        try:
            got = fn()
            items.extend(got)
            report[name] = f"{len(got)} items"
        except Exception as exc:  # one broken source must not stop the run
            report[name] = f"FAILED: {type(exc).__name__}: {exc}"[:200]
    return items, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "web" / "data" / "opportunities.json")
    args = ap.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ICT).date()
    profile = load_yaml(ROOT / "profile.yaml")
    overrides = load_yaml(ROOT / "overrides.yaml").get("overrides", {})

    items, report = collect(today, args.offline)
    # Drop duplicates (the same event can come from two sources); first source wins.
    unique: dict[str, dict] = {}
    for item in items:
        unique.setdefault(item["id"], item)
    items = eligibility.apply(list(unique.values()), profile, overrides)

    prev = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    if args.offline:
        # Offline runs keep what the last online run learned from the pages.
        old = {p["id"]: p for p in prev.get("items", [])}
        for item in items:
            if item["id"] in old:
                for key in ("status", "page_hash", "fetch_error", "last_checked"):
                    if item[key] in (None, "unknown") and old[item["id"]].get(key):
                        item[key] = old[item["id"]][key]
    stamp = now.isoformat(timespec="seconds")
    changes = diffing.diff(prev.get("items", []), items, stamp)

    for name, line in report.items():
        print(f"{name:10} {line}")
    counts: dict[str, int] = {}
    for item in items:
        counts[item["eligible_for_me"]] = counts.get(item["eligible_for_me"], 0) + 1
    print("eligibility", counts)
    print(f"changes    {len(changes)}")

    if args.dry_run:
        return 0

    out = {
        "generated_at": stamp,
        "profile": profile,
        "sources": report,
        "items": sorted(items, key=lambda i: (i["kind"], i["name"].lower())),
        "changes": diffing.merge_history(prev.get("changes", []), changes),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    text = notify.digest(changes, os.environ.get("SITE_URL", ""))
    if text and prev:  # no digest for the very first run, which would list everything as new
        print(text)
        try:
            notify.send(text)
        except Exception as exc:
            print(f"digest not sent: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
