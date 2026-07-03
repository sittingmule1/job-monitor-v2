# Job Monitor v2

Reads new emails under your Gmail "Job Alerts" label, fetches Verizon/PBS/
EchoStar/NBCUniversal directly from their ATS, dedupes everything against
what you've already seen, and publishes one HTML digest — no email needed,
just a URL you bookmark.

## What you get

The digest (`docs/index.html`, served via GitHub Pages) is grouped into
three sections, always in this order, and **the tier is never hidden**:

- **✅ Verified** — title/company/link confirmed from structured data
  (LinkedIn, Indeed, ZipRecruiter subjects; Verizon/PBS/EchoStar Workday;
  NBCUniversal SmartRecruiters). Trust these to scan and act on directly.
- **⚠️ Best-effort** — parsed automatically but from a source known to
  shift format (Lensa, Kimble, JJ Alerts, agencies). Spot-check before acting.
- **🔍 Manual-check** — the monitor knows something happened but can't tell
  you what (Amazon, Paramount, Amdocs, Marriott email notifications, any
  ATS fetch that errors out). Click through and look yourself.

## One-time setup

### 1. Gmail API access
```
pip install google-auth-oauthlib
```
Follow the prerequisites at the top of `setup_gmail_auth.py`, then:
```
python setup_gmail_auth.py
```
This prints three values — `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`,
`GMAIL_REFRESH_TOKEN`. Add each as a GitHub Actions secret:
repo → **Settings → Secrets and variables → Actions → New repository secret**.

### 2. GitHub Pages
Repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch:
`main`, folder: `/docs`. Save. Your digest will be live at
`https://<username>.github.io/<repo-name>/` after the first successful run.

### 3. First run
Repo → **Actions** tab → **Job Monitor Digest** → **Run workflow** (this is
the `workflow_dispatch` trigger, for testing without waiting for the cron
schedule). Check the Actions log for errors, then visit the Pages URL.

After that, it runs automatically once a day.

## Extending it

- **New email sender** → add an entry to `EMAIL_SOURCES` in `src/sources.py`.
  Default new senders to `MANUAL_CHECK` until you've confirmed the parser
  output looks right against a real sample — don't self-promote a source's
  tier without evidence.
- **New ATS to fetch directly** → add to `ATS_SOURCES` and, if it's not
  Workday or SmartRecruiters, write a new fetcher function in
  `src/ats_fetchers.py` following the same pattern (always wrap in
  try/except and degrade to a MANUAL_CHECK record on failure — never let
  one bad fetch break the whole run).
- **Tune relevance** → edit `PRIORITY_COMPANIES`, `KEYWORDS`, or
  `NOISE_TERMS` in `src/keywords.py`.

## Known limitations (by design, not bugs)

- Amazon has no public ATS API and RTO policy makes remote rare — email
  stays flag-only, no fetch attempted.
- Paramount (SuccessFactors), Amdocs (Eightfold), and Marriott (Oracle
  Cloud) are technically fetchable but their endpoints aren't yet
  reverse-engineered/verified — they stay manual-check until that work is
  done deliberately, not silently assumed to work.
- Indeed and ZipRecruiter subjects don't reveal which saved search
  triggered them — can't map a hit back to a specific alert you configured.
