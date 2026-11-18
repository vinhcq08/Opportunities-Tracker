import datetime as dt
import json
import types

from tracker import calendar_ics, claude_reader, health, notify
from tracker.models import normalize
from tracker.sources import aggregators, ats, prizes

TODAY = dt.date(2026, 11, 18)


# ---------------------------------------------------------------- opportunity-site feeds
RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>ETH Summer Research Fellowship 2027 (Fully Funded)</title><link>https://ex.org/eth</link>
<pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate>
<description><![CDATA[<p>Undergraduate students from all nationalities can apply. Deadline: December 16, 2026.</p>]]></description></item>
<item><title>PhD Scholarship in Germany</title><link>https://ex.org/phd</link>
<pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate><description>For PhD students.</description></item>
<item><title>Old Hackathon for students</title><link>https://ex.org/old</link>
<pubDate>Mon, 01 Jun 2026 10:00:00 +0000</pubDate><description>Students worldwide.</description></item>
<item><title>Global Case Competition for university students</title><link>https://ex.org/case</link>
<pubDate>Tue, 10 Nov 2026 10:00:00 +0000</pubDate><description>Deadline: October 1, 2026.</description></item>
</channel></rss>"""


def test_feed_keeps_recent_undergrad_items_and_reads_deadline():
    items = aggregators.parse(RSS, {"name": "Test Feed", "url": "x"}, TODAY)
    assert [i["url"] for i in items] == ["https://ex.org/eth"]
    eth = items[0]
    assert eth["kind"] == "scholarship"  # "Fellowship" in the title
    assert eth["deadline"] == "2026-12-16" and eth["status"] == "open"
    assert eth["nationality_ok"] == "unknown"  # never eligible without a human decision
    assert "all nationalities" in eth["notes"]


def test_atom_feed_and_vietnamese_source():
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Cuộc thi lập trình sinh viên 2026</title>
    <link href="https://vn.example/olp"/><updated>2026-11-15T00:00:00Z</updated><summary>Dành cho sinh viên đại học</summary></entry></feed>"""
    items = aggregators.parse(atom, {"name": "VN", "url": "x", "vietnamese": True}, TODAY)
    assert items[0]["kind"] == "contest" and items[0]["country"] == "Vietnam"


# ---------------------------------------------------------------- job boards
def test_greenhouse_keeps_student_roles_near_vietnam():
    data = {"jobs": [
        {"id": 1, "title": "Software Engineer Intern", "absolute_url": "https://g/1", "location": {"name": "Ho Chi Minh City, Vietnam"}, "updated_at": "2026-11-10T00:00:00Z"},
        {"id": 2, "title": "Software Engineer Intern", "absolute_url": "https://g/2", "location": {"name": "New York"}},
        {"id": 3, "title": "Senior Engineer", "absolute_url": "https://g/3", "location": {"name": "Singapore"}},
        {"id": 4, "title": "Quant Trader Internship", "absolute_url": "https://g/4", "location": {"name": "Singapore"}},
    ]}
    items = {i["id"]: i for i in ats.parse_greenhouse(data, "acme")}
    assert set(items) == {"greenhouse-acme-1", "greenhouse-acme-4"}
    assert items["greenhouse-acme-1"]["nationality_ok"] == "vn_ok"
    assert items["greenhouse-acme-4"]["nationality_ok"] == "unknown"


def test_lever_uses_all_locations_and_commitment():
    data = [{"id": "a", "text": "Data Engineer", "hostedUrl": "https://l/a", "createdAt": 1794925226000,
             "categories": {"location": "Remote", "allLocations": ["Hanoi"], "commitment": "Internship"}}]
    [item] = ats.parse_lever(data, "acme")
    assert item["country"] == "Vietnam" and item["url"] == "https://l/a"


# ---------------------------------------------------------------- Kaggle, Challenge.gov
def test_kaggle_skips_playground():
    comps = [{"ref": "https://www.kaggle.com/competitions/big", "title": "Big", "deadline": "2027-02-01T23:59:00Z", "reward": "$50,000 Usd", "category": "Featured"},
             {"ref": "titanic", "title": "Titanic", "category": "Getting Started"},
             {"ref": "play", "title": "Play", "category": "Playground"}]
    items = prizes.parse_kaggle(comps)
    assert [i["name"] for i in items] == ["Big", "Titanic"] or [i["name"] for i in items] == ["Big"]
    assert items[0]["deadline"] == "2027-02-01" and items[0]["featured"]


def test_challenge_gov_marks_us_only():
    rows = [{"id": 7, "title": "Moon Prize", "agency_name": "NASA", "eligibility": "Open to U.S. citizens and permanent residents", "end_date": "2027-01-10"},
            {"id": 8, "title": "Global Water", "agency_name": "USAID", "eligibility": "Open to individuals worldwide; international teams welcome"}]
    items = {i["id"]: i for i in prizes.parse_challenge_gov(rows)}
    assert items["challengegov-7"]["nationality_ok"] == "us_only" and items["challengegov-7"]["featured"]
    assert items["challengegov-8"]["nationality_ok"] == "unknown"


# ---------------------------------------------------------------- calendar
def test_calendar_has_future_eligible_deadlines_with_reminders():
    items = [normalize({"id": "a", "name": "Prize; big, one", "org": "X", "kind": "challenge", "deadline": "2026-12-01", "url": "https://x"}),
             normalize({"id": "b", "name": "Past", "org": "X", "kind": "challenge", "deadline": "2026-01-01"}),
             normalize({"id": "c", "name": "No", "org": "X", "kind": "challenge", "deadline": "2026-12-05"})]
    items[0]["eligible_for_me"] = "likely"; items[1]["eligible_for_me"] = "likely"; items[2]["eligible_for_me"] = "not_eligible"
    ics = calendar_ics.build(items, TODAY, dt.datetime(2026, 11, 18, tzinfo=dt.timezone.utc))
    assert ics.count("BEGIN:VEVENT") == 1
    assert "DTSTART;VALUE=DATE:20261201" in ics and "TRIGGER:-P14D" in ics and "TRIGGER:-P3D" in ics
    assert "Prize\\; big\\, one" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


# ---------------------------------------------------------------- Claude page reader
class FakeClient:
    def __init__(self, payload, stop="end_turn"):
        self.payload, self.stop, self.calls = payload, stop, []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        block = types.SimpleNamespace(type="text", text=json.dumps(self.payload))
        return types.SimpleNamespace(content=[block], stop_reason=self.stop, model=kw["model"])


PAGE = "Summer research fellowship. Students of all nationalities can apply. The application deadline is 16 December 2026."


def payload(**over):
    base = {"nationality_ok": "global", "nationality_quote": "Students of all nationalities can apply.",
            "enrollment_req": "unknown", "enrollment_quote": "", "class_years": [], "class_years_quote": "",
            "deadline": "2026-12-16", "deadline_quote": "The application deadline is 16 December 2026.",
            "status": "open", "funding": "unknown", "confidence": "high", "summary": "A fellowship."}
    base.update(over)
    return base


def registry_item(**over):
    it = normalize({"id": "eth", "name": "ETH", "org": "ETH", "kind": "summer_research", "url": "https://e",
                    "nationality_ok": "unknown", "page_hash": "h1", **over})
    it["_page_text"] = PAGE
    return it


def test_reader_keeps_grounded_values_and_lists_changes():
    client = FakeClient(payload())
    p = claude_reader.read_page(client, registry_item(), {"country": "VN", "year": 2}, TODAY)
    assert p["changes"] == {"nationality_ok": "global", "deadline": "2026-12-16"}
    assert p["quotes"]["deadline"].startswith("The application deadline")
    kw = client.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"]["format"]["type"] == "json_schema"
    assert "<page_text>" in kw["messages"][0]["content"]


def test_reader_drops_invented_quotes_and_past_deadlines():
    client = FakeClient(payload(nationality_quote="Open to everyone on Earth.", deadline="2026-01-01",
                                deadline_quote="The application deadline is 16 December 2026."))
    p = claude_reader.read_page(client, registry_item(), {"country": "VN", "year": 2}, TODAY)
    assert "nationality_ok" not in p and "deadline" not in p and p["changes"] == {}


def test_reader_handles_refusal():
    assert claude_reader.read_page(FakeClient(payload(), stop="refusal"), registry_item(), {}, TODAY) is None


def test_reader_only_reads_changed_unverified_pages(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    item = registry_item()
    assert claude_reader.needs_reading(item, None)
    assert not claude_reader.needs_reading(item, {"page_hash": "h1"})
    assert claude_reader.needs_reading(item, {"page_hash": "old"})
    assert not claude_reader.needs_reading(registry_item(verified=True), None)
    proposals, line = claude_reader.run([item], {"gone": {}}, {}, TODAY)
    assert "skipped" in line and proposals == {}


# ---------------------------------------------------------------- health + alerts
def test_health_alerts_once_after_three_failures_and_on_recovery():
    h, alerts = {}, []
    for _ in range(4):
        h, a = health.update(h, {"mlh": "FAILED: HTTPError"}, "t")
        alerts += a
    assert len(alerts) == 1 and "failed 3 runs" in alerts[0]
    assert health.problems(h) == ["mlh: failing"]
    h, a = health.update(h, {"mlh": "5 items"}, "t2")
    assert a == ["mlh is working again"] and health.problems(h) == []


def test_health_quiet_alert_only_for_sources_that_had_items():
    h, alerts = health.update({}, {"feed": "3 items", "never": "0 items"}, "t")
    for _ in range(8):
        h, a = health.update(h, {"feed": "0 items", "never": "0 items"}, "t")
        alerts += a
    assert alerts == ["feed has returned nothing for 2 days; its page or feed may have changed"]


def test_send_posts_to_telegram_without_leaking_token(monkeypatch):
    posts = []

    class Resp:
        def raise_for_status(self):
            pass

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(notify.http.session(), "post", lambda url, json, timeout: posts.append((url, json)) or Resp())
    assert notify.send("**Hello**") == ["telegram"]
    assert posts[0][1] == {"chat_id": "42", "text": "Hello", "disable_web_page_preview": True}
    assert notify.send("") == []


def test_job_filter_rejects_international_recruiter_and_phd_roles():
    data = {"jobs": [{"id": n, "title": t, "absolute_url": "u", "location": {"name": "Singapore"}} for n, t in enumerate([
        "Product Manager I - International", "Campus Recruiter", "Quant Researcher Intern, PhD or Postdoc",
        "Software Engineer, New Grad", "Software Engineer Intern"])]}
    items = ats.parse_greenhouse(data, "wehrtyou")
    assert [i["name"] for i in items] == ["Software Engineer Intern"] and items[0]["org"] == "Hudson River Trading"


def test_vietnamese_board_internships_and_noise():
    rss = """<rss><channel>
    <item><title>[Bosch] Data Engineer Intern</title><link>https://f/1</link><pubDate>Mon, 16 Nov 2026 10:00:00 +0000</pubDate><description>Sinh viên năm 3</description></item>
    <item><title>Danh sách sinh viên nhận học bổng tháng 10</title><link>https://f/2</link><pubDate>Mon, 16 Nov 2026 10:00:00 +0000</pubDate><description>học bổng</description></item>
    </channel></rss>"""
    items = aggregators.parse(rss, {"name": "UIT", "url": "x", "vietnamese": True}, TODAY)
    assert len(items) == 1 and items[0]["kind"] == "internship" and items[0]["nationality_ok"] == "vn_ok"
