import datetime as dt

import pytest

from tracker import diff, eligibility, notify
from tracker.models import normalize
from tracker.sources import devpost, http, mlh, registry, simplify

VN = {"country": "VN", "year": 2}


def item(**kw):
    return normalize({"name": "X", "org": "Y", **kw})


# ---------------------------------------------------------------- eligibility
@pytest.mark.parametrize("fields, label", [
    ({"nationality_ok": "us_only"}, "not_eligible"),                       # NSF REU style
    ({"nationality_ok": "global", "enrollment_req": "host_university_only"}, "not_eligible"),  # MIT $100K
    ({"nationality_ok": "global", "enrollment_req": "us_canada_only"}, "not_eligible"),        # Microsoft Explore
    ({"nationality_ok": "global"}, "likely"),                              # MIT Solve, unverified
    ({"nationality_ok": "global", "verified": True}, "eligible"),
    ({"nationality_ok": "vn_ok", "verified": True}, "eligible"),
    ({"nationality_ok": "unknown"}, "check"),                              # aggregator item, no text
    ({"nationality_ok": "other_restriction"}, "check"),                    # CERN non-member list
    ({"nationality_ok": "global", "class_years": [3, 4]}, "check"),        # wrong year
])
def test_eligibility_rules(fields, label):
    assert eligibility.assess(item(**fields), VN)[0] == label


def test_override_wins():
    it = item(id="devpost-1", nationality_ok="unknown")
    label, reasons = eligibility.assess(it, VN, {"devpost-1": {"eligible_for_me": "eligible", "reason": "ok"}})
    assert (label, reasons) == ("eligible", ["ok"])


def test_us_only_is_fine_for_us_profile():
    assert eligibility.assess(item(nationality_ok="us_only"), {"country": "US"})[0] == "check"


# ---------------------------------------------------------------- diff
def test_diff_detects_new_opened_deadline_and_keeps_first_seen():
    old = [item(id="a", status="upcoming", first_seen="t0", last_changed="t0")]
    new = [item(id="a", status="open", deadline="2027-01-10"), item(id="b")]
    changes = diff.diff(old, new, "t1")
    kinds = sorted(c["type"] for c in changes)
    assert kinds == ["deadline", "new", "opened"]
    assert new[0]["first_seen"] == "t0" and new[0]["last_changed"] == "t1"
    assert new[1]["first_seen"] == "t1"


def test_diff_ignores_unknown_status_and_flags_broken_link():
    old = [item(id="a", status="open")]
    new = [item(id="a", status="unknown", fetch_error="HTTP 404")]
    assert [c["type"] for c in diff.diff(old, new, "t1")] == ["broken_link"]


def test_history_is_capped():
    hist = diff.merge_history([{"n": i} for i in range(200)], [{"n": -1}])
    assert len(hist) == diff.HISTORY_LIMIT and hist[0] == {"n": -1}


# ---------------------------------------------------------------- page watching
@pytest.mark.parametrize("text, status", [
    ("Applications are now open for 2027!", "open"),
    ("Apply now before the deadline", "open"),
    ("Applications closed. See you next year.", "closed"),
    ("We are no longer accepting applications", "closed"),
    ("Applications are open ... registration has closed", "unknown"),
    ("Learn about our research", "unknown"),
])
def test_detect_status(text, status):
    assert http.detect_status(text) == status


def test_page_text_strips_scripts_and_hash_ignores_numbers():
    assert http.page_text("<p>Hi <b>there</b></p><script>x=1</script>") == "Hi there"
    assert http.text_hash("Visitors: 101 Apply") == http.text_hash("Visitors: 102 Apply")


def test_registry_passed_deadline_closes_and_window_sets_upcoming(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("""
programs:
  - {id: a, kind: hackathon, name: A, deadline: 2026-01-01}
  - {id: b, kind: hackathon, name: B, window: [6, 7]}
  - {id: c, kind: hackathon, name: C, window: [11]}
""")
    items = {i["id"]: i for i in registry.fetch(registry.load(f), dt.date(2026, 11, 17), offline=True)}
    assert items["a"]["status"] == "closed"
    assert items["b"]["status"] == "upcoming"
    assert items["c"]["status"] == "unknown"


def test_registry_rejects_duplicate_ids(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("programs:\n  - {id: a, kind: hackathon, name: A}\n  - {id: a, kind: hackathon, name: B}\n")
    with pytest.raises(ValueError):
        registry.load(f)


def test_real_registry_is_valid():
    from tracker.run import ROOT
    items = registry.fetch(registry.load(ROOT / "programs.yaml"), dt.date(2026, 11, 17), offline=True)
    assert len(items) >= 20
    assert all(i["url"].startswith("https://") for i in items)


# ---------------------------------------------------------------- sources
DEVPOST_SAMPLE = [
    {"id": 1, "title": "Space Hack", "url": "https://space.devpost.com/", "organization_name": "NASA Ames",
     "displayed_location": {"location": "Online"}, "open_state": "open",
     "submission_period_dates": "Nov 01 - Dec 15, 2026", "prize_amount": "$<span>10,000</span>",
     "themes": [{"name": "Space"}], "registrations_count": 900, "invite_only": False},
    {"id": 2, "title": "Berlin Hack", "url": "https://b.devpost.com/", "organization_name": "Club",
     "displayed_location": {"location": "Berlin, Germany"}, "open_state": "open",
     "submission_period_dates": "Dec 01 - 03, 2026"},
    {"id": 3, "title": "Saigon AI Hack", "url": "https://s.devpost.com/", "organization_name": "Club",
     "displayed_location": {"location": "Ho Chi Minh City, Vietnam"}, "open_state": "upcoming",
     "submission_period_dates": "Jan 10 - 12, 2027"},
    {"id": 4, "title": "Private", "url": "https://p.devpost.com/", "invite_only": True,
     "displayed_location": {"location": "Online"}},
]


def test_devpost_keeps_online_and_vietnam_only():
    items = {i["id"]: i for i in devpost.parse(DEVPOST_SAMPLE)}
    assert set(items) == {"devpost-1", "devpost-3"}
    nasa = items["devpost-1"]
    assert nasa["featured"] and nasa["format"] == "online" and nasa["deadline"] == "2026-12-15"
    assert nasa["prize"] == "$ 10,000" or nasa["prize"] == "$10,000"
    assert items["devpost-3"]["deadline"] == "2027-01-12" and items["devpost-3"]["status"] == "upcoming"


def _mlh_card(name, url, start, end, mode, city, country):
    return (f'<a href="{url}?utm_source=mlh&amp;utm_content={name.replace(" ", "+")}" target="_blank" '
            f'class="block rounded-card" itemScope="" itemType="https://schema.org/Event">'
            f'<meta itemProp="url" content="{url}"/>'
            f'<meta itemProp="eventAttendanceMode" content="https://schema.org/{mode}EventAttendanceMode"/>'
            f'<meta itemProp="startDate" content="{start}T23:00:00Z"/><meta itemProp="endDate" content="{end}T20:00:00Z"/>'
            f'<div itemProp="location" itemScope="" itemType="https://schema.org/Place" style="display:none">'
            f'<span itemProp="name">{city}</span><div itemProp="address" itemScope="">'
            f'<meta itemProp="addressLocality" content="{city}"/><meta itemProp="addressCountry" content="{country}"/></div></div>'
            f'<div class="rounded-card"><h3 class="font-bold">{name}</h3></div></a>')


MLH_SAMPLE = "<main>" + "".join([
    _mlh_card("Hack Western 13", "https://hackwestern.com", "2026-11-20", "2026-11-22", "Offline", "London", "CA"),
    _mlh_card("HackSG", "https://hack.sg", "2027-02-01", "2027-02-02", "Offline", "Singapore", "SG"),
    _mlh_card("Global Hack Week", "https://ghw.mlh.io", "2027-01-10", "2027-01-16", "Online", "", ""),
    _mlh_card("Old Hack", "https://old.example", "2026-09-01", "2026-09-02", "Online", "", ""),
]) + "</main>"


def test_mlh_parses_cards_and_filters_region():
    items = {i["name"]: i for i in mlh.parse(MLH_SAMPLE, dt.date(2026, 11, 17))}
    assert set(items) == {"HackSG", "Global Hack Week"}
    sg = items["HackSG"]
    assert sg["url"] == "https://hack.sg" and sg["deadline"] == "2027-02-01" and sg["country"] == "SG"
    assert items["Global Hack Week"]["format"] == "online"
    assert mlh.season(dt.date(2026, 11, 17)) == 2027 and mlh.season(dt.date(2027, 3, 1)) == 2027


def test_mlh_falls_back_to_link_name():
    card = _mlh_card("Name From Link", "https://x.example", "2027-01-01", "2027-01-02", "Online", "", "").replace(
        '<h3 class="font-bold">Name From Link</h3>', "")
    assert [i["name"] for i in mlh.parse(card, dt.date(2026, 11, 17))] == ["Name From Link"]


def test_registry_manual_check_skips_fetch(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(registry.http, "get", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError))
    f = tmp_path / "p.yaml"
    f.write_text("programs:\n  - {id: a, kind: hackathon, name: A, url: 'https://a.example', manual_check: true}\n")
    [item] = registry.fetch(registry.load(f), dt.date(2026, 11, 17))
    assert called == [] and item["manual_check"] and item["fetch_error"] is None


def test_registry_tls_fallback_retries_unverified(tmp_path, monkeypatch):
    import requests

    class Resp:
        status_code = 200
        text = "<p>Registration is now open</p>"

    calls = []

    def fake_get(url, **kw):
        calls.append(kw.get("verify", True))
        if kw.get("verify", True):
            raise requests.exceptions.SSLError("incomplete chain")
        return Resp()

    monkeypatch.setattr(registry.http, "get", fake_get)
    f = tmp_path / "p.yaml"
    f.write_text("programs:\n  - {id: a, kind: hackathon, name: A, url: 'https://a.example', tls_fallback: true}\n"
                 "  - {id: b, kind: hackathon, name: B, url: 'https://b.example'}\n")
    a, b = registry.fetch(registry.load(f), dt.date(2026, 11, 17))
    assert a["status"] == "open" and a["fetch_error"] is None
    assert b["fetch_error"] == "SSLError"
    assert calls == [True, False, True]


def test_simplify_keeps_nearby_roles():
    listings = [
        {"id": "1", "active": True, "is_visible": True, "category": "Software", "company_name": "Grab",
         "title": "SWE Intern", "url": "https://x", "locations": ["Ho Chi Minh City, Vietnam"], "date_posted": 1794925226},
        {"id": "2", "active": True, "category": "Software", "company_name": "A", "title": "SWE Intern",
         "url": "https://y", "locations": ["NYC"]},
        {"id": "3", "active": False, "category": "Software", "company_name": "B", "title": "Old",
         "url": "https://z", "locations": ["Hanoi"]},
    ]
    items = simplify.parse(listings)
    assert [i["id"] for i in items] == ["simplify-1"]
    assert items[0]["nationality_ok"] == "vn_ok"


# ---------------------------------------------------------------- digest
def test_digest_skips_ineligible_and_noise():
    changes = [
        {"type": "opened", "name": "A", "eligible_for_me": "likely", "detail": "upcoming → open"},
        {"type": "new", "name": "B", "eligible_for_me": "not_eligible", "detail": ""},
        {"type": "page_updated", "name": "C", "eligible_for_me": "likely", "detail": ""},
    ]
    text = notify.digest(changes)
    assert "Now open: A" in text and "B" not in text and "C" not in text
    assert notify.digest([]) == ""
