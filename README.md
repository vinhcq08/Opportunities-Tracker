# The Opportunity Tracker

A self-updating dashboard of **summer programs, hackathons, innovation challenges, business competitions and big-tech programs that students in Vietnam can actually enter**.

Every 6 hours a GitHub Action checks the sources, works out eligibility, records what changed, sends a Discord digest, and redeploys the dashboard to GitHub Pages.

## How it works

| Source | What | File |
|---|---|---|
| Curated list | Named programs: summer research, scholarships, insight programs, open-source programs, contests, competitions. Each official page is watched for "applications open/closed". | `programs.yaml` |
| Opportunity sites | RSS from global and Vietnamese opportunity sites; items go to the Review tab | `sources.yaml` → `feeds` |
| Job boards | Greenhouse and Lever boards, internships in Vietnam/Singapore only | `sources.yaml` → `job_boards` |
| Devpost, MLH | Hackathons, online or in Asia | `tracker/sources/` |
| Kaggle, Challenge.gov | Competitions and prize challenges | `sources.yaml` |
| SimplifyJobs | Internship feed, Vietnam/Singapore roles | `tracker/sources/simplify.py` |

Every run also writes `data/deadlines.ics`, a calendar you can subscribe to from the Overview tab, and checks each source's health so a broken feed raises an alert.

Each item gets an eligibility label for the profile in `profile.yaml`:

- **Eligible**: the rules allow students in Vietnam, and a human verified it (`verified: true`)
- **Likely**: the rules look open, but nobody has verified them yet
- **Check rules**: not enough information; listed in the dashboard's **Review** tab
- **Not eligible**: e.g. US citizens only, or the host university's own students; hidden by default, with the reason shown

## Setup (once)

1. **Turn on Pages:** go to *Settings → Pages → Build and deployment → Source* and choose **GitHub Actions**.
2. **Optional extras** go in *Settings → Secrets and variables → Actions → New repository secret*. Each one switches a feature on:

   | Secret | Turns on |
   |---|---|
   | `DISCORD_WEBHOOK_URL` | Digest in a Discord channel (*channel → Edit → Integrations → Webhooks*) |
   | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Digest on Telegram: create a bot with @BotFather, message it once, then read your chat id from `https://api.telegram.org/bot<token>/getUpdates` |
   | `KAGGLE_USERNAME` + `KAGGLE_KEY` | Live Kaggle competitions (*kaggle.com → Settings → API → Create New Token*) |

3. **Run it the first time:** go to *Actions → Update opportunities → Run workflow*. After that it runs every 6 hours.

The site is at `https://<user>.github.io/Opportunities-Tracker/`.

## Everyday use

- **Verify a program:** open its page, set `nationality_ok`, `enrollment_req`, `class_years` and `deadline` in `programs.yaml`, then set `verified: true`.
- **Add a program:** copy an entry in `programs.yaml`. The header comments list every field.
- **Review tab:** accept Claude's suggestions and decide unclear items, click **Copy for overrides.yaml**, paste it into `overrides.yaml` (replacing its contents) and commit.
- **Calendar:** on the Overview tab, click *Subscribe in Google Calendar*; each dated card also has a **+ Calendar** button.
- **Tracker:** saved items and notes live in your browser (localStorage) on each device.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest -q
python -m tracker.run            # full run (needs network)
python -m tracker.run --offline  # registry only, no network
python -m http.server -d web 8000
```

## Keeping things safe

- **Your personal data** (saved programs, notes, decisions, verifications) lives only in your browser. Use **Tracker → Back up my data** regularly; **Restore from backup** brings it back on any device or after clearing the browser.
- **Verification:** open a program page, check the official page, and use **Verify this program**. Then copy your decisions from the Review tab into `overrides.yaml`. Only verified programs can show "Eligible", and only their deadlines count as confirmed; other dates show "unconfirmed" in the app and the calendar.
- **Claude page reading is off.** It uses the paid Claude API (billed per use, separately from a Claude.ai subscription), so `sources.yaml` has `claude_page_reading: false` and the workflow passes no Anthropic key. Turning it back on needs both changes plus an `ANTHROPIC_API_KEY` secret; it is then capped by `CLAUDE_DAILY_BUDGET_USD` (default `1.00`) and rereads a page only when its eligibility or deadline sentences change.
- **The schedule:** GitHub turns off scheduled workflows after 60 days without repository activity. Every run commits fresh data, which counts as activity, so this only happens if updates keep failing for two months (GitHub emails you about failed runs). Scheduled runs are best-effort: GitHub may delay or skip a slot when busy, so data can occasionally be up to 12 hours old.

