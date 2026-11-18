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
from . import calendar_ics, claude_reader, eligibility, health, notify
from .sources import aggregators, ats, devpost, mlh, prizes, registry, simplify

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

    config = load_yaml(ROOT / "sources.yaml")
    single = [("devpost", devpost.fetch), ("mlh", lambda: mlh.fetch(today)), ("simplify", simplify.fetch)]
    if config.get("kaggle"):
        if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
            single.append(("kaggle", prizes.fetch_kaggle))
        else:
            report["kaggle"] = "skipped (add KAGGLE_USERNAME and KAGGLE_KEY secrets to turn on)"
    if config.get("challenge_gov"):
        single.append(("challenge.gov", prizes.fetch_challenge_gov))
    for name, fn in single:
        try:
            got = fn()
            items.extend(got)
            report[name] = f"{len(got)} items"
        except Exception as exc:  # one broken source must not stop the run
            report[name] = f"FAILED: {type(exc).__name__}: {exc}"[:200]

    # Multi-feed sources report each feed or board on its own line.
    curated = [i for i in items if i["source"] == "registry"]
    for fetcher, arg in ((aggregators.fetch, (config.get("feeds") or [], today, curated)), (ats.fetch, (config.get("job_boards") or {},))):
        try:
            got, sub = fetcher(*arg)
            items.extend(got)
            report.update(sub)
        except Exception as exc:
            report[fetcher.__module__.rsplit(".", 1)[-1]] = f"FAILED: {type(exc).__name__}"
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
    override_file = load_yaml(ROOT / "overrides.yaml")
    overrides = override_file.get("overrides") or {}
    field_overrides = override_file.get("fields") or {}

    items, report = collect(today, args.offline)
    # Drop duplicates (the same event can come from two sources); first source wins.
    unique: dict[str, dict] = {}
    for item in items:
        unique.setdefault(item["id"], item)
    items = list(unique.values())
    # Accepted suggestions (from the Review tab) overwrite fields of the curated entries.
    for item in items:
        for key, value in (field_overrides.get(item["id"]) or {}).items():
            if key in item and not key.startswith("_"):
                item[key] = value
    items = eligibility.apply(items, profile, overrides)

    prev = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    proposals, report["claude"] = claude_reader.run(items, prev.get("proposals", {}), profile, today)
    for pid in field_overrides:  # an accepted suggestion is done
        proposals.pop(pid, None)
    for item in items:
        item.pop("_page_text", None)
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

    source_health, health_alerts = health.update(prev.get("health", {}), report, stamp)
    for line in health_alerts:
        print(f"health     {line}")

    out = {
        "generated_at": stamp,
        "profile": profile,
        "sources": report,
        "items": sorted(items, key=lambda i: (i["kind"], i["name"].lower())),
        "changes": diffing.merge_history(prev.get("changes", []), changes),
        "proposals": proposals,
        "health": source_health,
        "source_problems": health.problems(source_health),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ics = calendar_ics.build(items, today, now, os.environ.get("SITE_URL", ""))
    (args.out.parent / "deadlines.ics").write_text(ics, encoding="utf-8", newline="")

    text = notify.digest(changes, os.environ.get("SITE_URL", "")) if prev else ""  # no digest on the very first run
    extra = notify.health_digest(health_alerts)
    message = "\n\n".join(t for t in (text, extra) if t)
    if message:
        print(message)
        try:
            sent = notify.send(message)
            print("sent to", ", ".join(sent) if sent else "no channel (none configured)")
        except Exception as exc:
            print(f"digest not fully sent: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
