# The Opportunity Tracker

A self-updating dashboard of **summer programs, hackathons, innovation challenges, business competitions and big-tech programs that students in Vietnam can actually enter**.

Every 6 hours a GitHub Action checks the sources, works out eligibility, records what changed, sends a Discord digest, and redeploys the dashboard to GitHub Pages.

## How it works

| Source | What | File |
|---|---|---|
| Curated registry | Named programs (NASA, MIT, ETH, OIST, Mitacs, Hult Prize, Grab, VNG…). Each official page is watched for "applications open/closed". | `programs.yaml`, `tracker/sources/registry.py` |
| Devpost | Open and upcoming hackathons, kept to online or Asia-based ones | `tracker/sources/devpost.py` |
| MLH | Season events, online or in Asia (best effort) | `tracker/sources/mlh.py` |
| SimplifyJobs | Internship feed, kept to roles in Vietnam/Singapore | `tracker/sources/simplify.py` |

Each item gets an eligibility label for the profile in `profile.yaml`:

- **Eligible**: the rules allow students in Vietnam, and a human verified it (`verified: true`)
- **Likely**: the rules look open, but nobody has verified them yet
- **Check rules**: not enough information; listed in the dashboard's **Review** tab
- **Not eligible**: e.g. US citizens only, or the host university's own students; hidden by default, with the reason shown

## Setup (once)

1. **Turn on Pages:** go to *Settings → Pages → Build and deployment → Source* and choose **GitHub Actions**.
2. **Optional: add a Discord digest.** Create a webhook (*Discord channel → Edit → Integrations → Webhooks*). Add it as a repository secret named `DISCORD_WEBHOOK_URL` (*Settings → Secrets and variables → Actions*).
3. **Run it the first time:** go to *Actions → Update opportunities → Run workflow*. After that it runs every 6 hours.

The site is at `https://<user>.github.io/Opportunities-Tracker/`.

## Everyday use

- **Verify a program:** open its page, set `nationality_ok`, `enrollment_req`, `class_years` and `deadline` in `programs.yaml`, then set `verified: true`.
- **Add a program:** copy an entry in `programs.yaml`. The header comments list every field.
- **Review queue:** decide items in the dashboard's Review tab, click **Copy for overrides.yaml**, paste the result into `overrides.yaml` and commit.
- **Tracker:** saved items and notes live in your browser (localStorage) on each device.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest -q
python -m tracker.run            # full run (needs network)
python -m tracker.run --offline  # registry only, no network
python -m http.server -d web 8000
```
