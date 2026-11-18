"""Remember how each source did across runs and raise an alert when one breaks or goes quiet."""

from __future__ import annotations

import re

FAIL_ALERT_RUNS = 3    # 3 failed runs in a row = 18 hours at the 6-hour schedule
QUIET_ALERT_RUNS = 8   # 8 empty runs in a row = 2 days, only for sources that used to return items
NOT_TRACKED = {"claude"}


def update(previous: dict, report: dict[str, str], now: str) -> tuple[dict, list[str]]:
    health = {k: dict(v) for k, v in previous.items()}
    alerts: list[str] = []
    for name, line in report.items():
        if name in NOT_TRACKED:
            continue
        h = health.setdefault(name, {"fail_runs": 0, "zero_runs": 0, "ever_nonzero": False, "last_ok": None})
        if line.startswith("FAILED"):
            h["fail_runs"] += 1
            h["last_error"] = line[:160]
            if h["fail_runs"] == FAIL_ALERT_RUNS:
                alerts.append(f"{name} has failed {FAIL_ALERT_RUNS} runs in a row ({line[:80]})")
            continue
        m = re.match(r"(\d+) items", line)
        count = int(m.group(1)) if m else 0
        if h["fail_runs"] >= FAIL_ALERT_RUNS:
            alerts.append(f"{name} is working again")
        h["fail_runs"] = 0
        h.pop("last_error", None)
        h["last_ok"] = now
        h["last_count"] = count
        if count > 0:
            h["ever_nonzero"] = True
            h["zero_runs"] = 0
        else:
            h["zero_runs"] += 1
            if h["ever_nonzero"] and h["zero_runs"] == QUIET_ALERT_RUNS:
                alerts.append(f"{name} has returned nothing for 2 days; its page or feed may have changed")
    return health, alerts


def problems(health: dict) -> list[str]:
    """Sources currently in trouble, for the dashboard footer."""
    out = []
    for name, h in sorted(health.items()):
        if h.get("fail_runs", 0) >= FAIL_ALERT_RUNS:
            out.append(f"{name}: failing")
        elif h.get("ever_nonzero") and h.get("zero_runs", 0) >= QUIET_ALERT_RUNS:
            out.append(f"{name}: quiet")
    return out
