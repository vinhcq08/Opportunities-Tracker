"""Decide whether a student in the profile's country can enter an opportunity.

Labels, from best to worst:
  eligible      rules say yes and a human verified it on the official page
  likely        rules say yes but nobody verified it yet
  check         not enough information; shown with a warning and in the review queue
  not_eligible  a rule rules it out; hidden by default with the reason shown
"""

from __future__ import annotations

NOT_ELIGIBLE_ENROLLMENT = {
    "us_canada_only": "Requires enrollment at a US or Canadian university",
    "host_university_only": "Only for students of the host university (or teams with an affiliated member)",
}

NATIONALITY_RULES = {
    "us_only": ("US", "US citizens or permanent residents only"),
    "eu_only": ("EU", "EU/EEA citizens only"),
}


def assess(item: dict, profile: dict, overrides: dict | None = None) -> tuple[str, list[str]]:
    overrides = overrides or {}
    country = profile.get("country", "VN")
    year = profile.get("year")

    override = overrides.get(item["id"])
    if override:
        label = override.get("eligible_for_me", "check")
        reason = override.get("reason", "Decided by you in the review queue")
        return label, [reason]

    reasons: list[str] = []
    nat = item.get("nationality_ok", "unknown")
    enr = item.get("enrollment_req", "any")

    if enr in NOT_ELIGIBLE_ENROLLMENT:
        return "not_eligible", [NOT_ELIGIBLE_ENROLLMENT[enr]]
    if nat in NATIONALITY_RULES:
        allowed, why = NATIONALITY_RULES[nat]
        if country != allowed:
            return "not_eligible", [why]
    if nat == "other_restriction":
        return "check", [item.get("notes") or "Has nationality restrictions; check the list"]

    if year and item.get("class_years") and year not in item["class_years"]:
        reasons.append(f"Listed for years {', '.join(map(str, item['class_years']))}, you are in year {year}")
        return "check", reasons

    if nat == "unknown":
        return "check", ["Eligibility text not confirmed yet"]

    if nat in ("global", "vn_ok") and enr in ("any", "vn_university_ok"):
        if item.get("verified"):
            return "eligible", ["Open to students in Vietnam (verified)"]
        return "likely", ["Rules look open to students in Vietnam; not verified yet"]

    return "check", ["Could not decide from the rules"]


def apply(items: list[dict], profile: dict, overrides: dict | None = None) -> list[dict]:
    for item in items:
        item["eligible_for_me"], item["elig_reasons"] = assess(item, profile, overrides)
    return items
