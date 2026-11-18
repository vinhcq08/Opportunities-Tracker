"""Weekly digest: when it is due, what it lists, how it renders, and that a week is sent only once."""

import datetime as dt
import json

from tracker import models, notify, run, weekly

UTC = dt.timezone.utc
# Wednesday 18 Nov 2026, 10:00 in Vietnam.
NOW = dt.datetime(2026, 11, 18, 3, 0, tzinfo=UTC)


def item(pid, **kw):
    base = {"id": pid, "name": pid.title(), "url": f"https://example.org/{pid}", "kind": "summer_research",
            "source": "registry", "featured": True, "eligible_for_me": "likely", "status": "open",
            "deadline": None, "deadline_confirmed": False, "first_seen": "2026-10-01T00:00:00+00:00",
            "format": "in_person", "country": "Japan"}
    base.update(kw)
    return base


def test_due_from_monday_7am_vietnam_time_once_per_week():
    monday_0659 = dt.datetime(2026, 11, 22, 23, 59, tzinfo=UTC)   # Mon 23 Nov 06:59 in Vietnam
    monday_0700 = dt.datetime(2026, 11, 23, 0, 0, tzinfo=UTC)
    last_week = {"week": "2026-W47"}
    assert not weekly.is_due(monday_0659, last_week)
    assert weekly.is_due(monday_0700, last_week)
    assert not weekly.is_due(monday_0700, {"week": "2026-W48"})
    # A missed Monday goes out with the next run; a first install sends straight away.
    assert weekly.is_due(dt.datetime(2026, 11, 25, 12, 0, tzinfo=UTC), last_week)
    assert weekly.is_due(NOW, {})
    assert weekly.week_key(dt.date(2026, 11, 18)) == "2026-W47"


def test_digest_lists_closing_new_and_updates_once_each():
    items = [
        item("epfl", deadline="2026-11-29"),                                        # closing, unconfirmed
        item("confirmed", deadline="2026-11-25", deadline_confirmed=True, kind="hackathon"),
        item("far", deadline="2027-01-30"),
        item("past", deadline="2026-11-10"),
        item("shut", deadline="2026-11-20", status="closed"),
        item("blocked", deadline="2026-11-21", eligible_for_me="not_eligible"),
        item("tiny", deadline="2026-11-22", source="devpost", featured=False, kind="hackathon"),
        item("fresh", first_seen="2026-11-17T00:00:00+00:00", format="online"),
        item("fresh-and-closing", first_seen="2026-11-17T00:00:00+00:00", deadline="2026-11-30"),
        item("fresh-tiny", first_seen="2026-11-17T00:00:00+00:00", source="devpost", featured=False),
        item("opened"),
    ]
    changes = [
        {"type": "opened", "id": "opened", "at": "2026-11-16T00:00:00+00:00"},
        {"type": "deadline", "id": "far", "at": "2026-11-15T00:00:00+00:00"},
        {"type": "deadline", "id": "epfl", "at": "2026-11-15T00:00:00+00:00"},   # already under Closing
        {"type": "opened", "id": "old", "at": "2026-10-01T00:00:00+00:00"},
    ]
    d = weekly.build(items, changes, [], NOW, "https://site.example/")
    by = {s["key"]: s for s in d["sections"]}
    assert [line["name"] for line in by["closing"]["lines"]] == ["Confirmed", "Epfl", "Fresh-And-Closing"]
    assert "date unconfirmed" in by["closing"]["lines"][1]["bits"]
    assert "date unconfirmed" not in by["closing"]["lines"][0]["bits"]
    assert by["closing"]["lines"][0]["lead"] == "Wed 25 Nov (in 7 days)"
    assert "1 smaller Devpost hackathon also close" in by["closing"]["more"]
    assert [line["name"] for line in by["new"]["lines"]] == ["Fresh"]
    assert "Online" in by["new"]["lines"][0]["bits"]
    assert [(line["lead"], line["name"]) for line in by["updates"]["lines"]] == [
        ("Now open", "Opened"), ("Deadline 30 Jan 2027 (unconfirmed)", "Far")]
    assert d["title"] == "Weekly digest · 16–22 Nov 2026"
    assert d["summary"] == "3 closing within 2 weeks · 1 new · 2 opened or dated"


def test_quiet_week_still_sends_a_message_and_lists_source_problems():
    d = weekly.build([item("far", deadline="2027-03-01")], [], ["mlh: quiet"], NOW)
    assert [s["key"] for s in d["sections"]] == ["quiet", "health"]
    assert "mlh: quiet" in weekly.to_text(d)


def test_discord_payload_is_safe_and_within_limits():
    names = [f"@everyone Win [free] **money** {n} " + "x" * 120 for n in range(40)]
    items = [item(f"p{n}", name=names[n], first_seen="2026-11-17T00:00:00+00:00",
                  url="https://evil.example/a)b c") for n in range(40)]
    items.append(item("js", name="Bad link", url="javascript:alert(1)", deadline="2026-11-20"))
    payload = weekly.to_discord(weekly.build(items, [], [], NOW, "https://site.example/"))
    assert payload["allowed_mentions"] == {"parse": []}
    assert len(payload["embeds"]) <= 10
    # Embeds sharing a url are merged by Discord, which hid every section but the first.
    assert len(payload["embeds"]) > 1 and not any("url" in e for e in payload["embeds"])
    assert sum(len(e["title"]) + len(e["description"]) for e in payload["embeds"]) <= 6000
    assert all(len(e["description"]) <= 4096 for e in payload["embeds"])
    text = "\n".join(e["description"] for e in payload["embeds"])
    assert "[free]" not in text and "(free)" in text and "\\*\\*money\\*\\*" in text
    assert "https://evil.example/a%29b%20c" in text
    assert "javascript:" not in text
    assert payload["avatar_url"] == "https://site.example/icons/icon-192.png"


def test_telegram_messages_escape_html_and_split():
    items = [item(f"p{n}", name=f"<b>Prize & {n}</b> " + "y" * 200, first_seen="2026-11-17T00:00:00+00:00")
             for n in range(10)]
    d = weekly.build(items, [], [], NOW, "https://site.example/")
    d["sections"][0]["lines"] *= 3  # make it long enough to need several messages
    messages = weekly.to_telegram(d)
    assert len(messages) > 1 and all(len(m) <= 4096 for m in messages)
    assert "&lt;b&gt;Prize &amp; 0&lt;/b&gt;" in messages[0]


def test_send_weekly_posts_embeds_and_telegram_html(monkeypatch):
    posts = []

    class Resp:
        def raise_for_status(self):
            pass

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(notify.http.session(), "post", lambda url, json, timeout: posts.append((url, json)) or Resp())
    sent, errors = notify.send_weekly(weekly.build([item("a", deadline="2026-11-25")], [], [], NOW))
    assert sent == ["discord", "telegram"] and errors == []
    assert posts[0][1]["embeds"][0]["title"] == "Closing in the next 14 days"
    assert posts[1][1]["parse_mode"] == "HTML" and posts[1][1]["chat_id"] == "42"


def _run_offline(tmp_path, monkeypatch, now):
    out = tmp_path / "data.json"
    monkeypatch.setattr(run.dt, "datetime", type("FixedDT", (dt.datetime,), {"now": classmethod(lambda cls, tz=None: now)}))
    run.main(["--offline", "--out", str(out)])
    return json.loads(out.read_text())


def test_run_sends_once_per_week_and_waits_when_no_channel(tmp_path, monkeypatch):
    calls = []
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("FORCE_WEEKLY", raising=False)
    program = {**models.DEFAULTS, **item("a", deadline="2026-11-25")}
    monkeypatch.setattr(run.registry, "fetch", lambda entries, today, offline=False: [dict(program)])
    monkeypatch.setattr(run.notify, "send_weekly", lambda d: calls.append(d) or (["discord"], []))

    # No channel set up: the digest waits and nothing is marked as sent.
    data = _run_offline(tmp_path, monkeypatch, NOW)
    assert calls == [] and data["weekly"] == {}

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
    data = _run_offline(tmp_path, monkeypatch, NOW)
    assert len(calls) == 1 and data["weekly"]["week"] == "2026-W47" and data["weekly"]["channels"] == ["discord"]

    _run_offline(tmp_path, monkeypatch, NOW + dt.timedelta(hours=6))   # same week: nothing more
    assert len(calls) == 1
    monkeypatch.setenv("FORCE_WEEKLY", "1")                              # the workflow's "send now" box
    _run_offline(tmp_path, monkeypatch, NOW + dt.timedelta(hours=12))
    assert len(calls) == 2


def test_repo_sends_weekly_only_by_default():
    settings = run.load_yaml(run.ROOT / "sources.yaml")["notifications"]
    assert settings == {"weekly_digest": True, "every_run": False}
