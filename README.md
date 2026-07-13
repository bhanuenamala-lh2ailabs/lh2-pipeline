# LH2 Indian IT-Services Sourcing Pipeline

A repeatable, mostly-unattended pipeline that produces **verified Indian
IT-services companies** as acquisition targets — sourced from public directories +
the company registry, enriched with founder **name + LinkedIn + phone + email**,
confidence-scored, exported as CSV, and synced straight to Google Sheets.

> Full architecture, status, and roadmap: see **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)**
> and **[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)**.

## Accuracy rules (non-negotiable)

1. **Never fabricate.** A blank cell is correct; an invented value is a bug.
2. **Registry beats aggregators** on conflicts.
3. **Idempotent + cached.** Re-runs never re-scrape or re-bill cached work.
4. **Net-new always.** Previously mined/delivered firms are excluded by domain + name.
5. **Secrets via env only** (`.env` / GitHub secrets — never committed).

## Setup

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[all]"                             # crawlers, Claude, xlsx, sheets, tests
python -m playwright install chromium               # once, for crawlers

cp .env.example .env                                # fill ANTHROPIC_API_KEY, SIGNALHIRE_API_KEY, GOOGLE_SHEETS_KEY
# place the Google service-account JSON at google_service_account.json (gitignored)

lh2 config-check                                    # validate config + .env (keys masked)
lh2 init                                            # create data dirs + initialize the DB
```

Tunables (cities, source toggles, gate thresholds, provider rate limits, sheet
tab names) live in `config.yaml`. API keys live in `.env` only.

## Run locally

```bash
lh2 crawl                 # Phase 1 — directory sites -> raw_listings
lh2 build                 # Phase 2 — canonicalize, dedupe, gate, exclude already-known
lh2 enrich --max-enrich N # Phase 3 — founders + email/phone/LinkedIn (Signalhire), rate-limited
lh2 score                 # Phase 4 — confidence + namesake guard
lh2 export --hyperlinked  # Phase 5 — the CSV deliverable
lh2 run                   # Phase 6 — chain all of the above, resumable + idempotent
```

## Sync to Google Sheets

```bash
lh2 sync                  # push results: Qualified (append) / Under Review (overwrite) / Stats
lh2 sync --dry-run        # report counts without writing
```

Three tabs: **Qualified Leads** (four-field, append-only), **Under Review**
(3-of-4, overwritten each run), **Pipeline Stats** (one metrics row per run).
Credentials resolve from `google_service_account.json` + `GOOGLE_SHEETS_KEY`
locally, or the `GOOGLE_SERVICE_ACCOUNT_JSON` + `GOOGLE_SHEETS_KEY` env vars in CI.

## Automation (GitHub Actions)

`.github/workflows/nightly-enrich.yml` runs **nightly at 18:30 UTC (00:00 IST)**:
`enrich → score → sync → export`, carrying the SQLite DB between runs via Actions
cache. Trigger manually anytime via **Run workflow** (`workflow_dispatch`).

Required repo secrets: `ANTHROPIC_API_KEY`, `SIGNALHIRE_API_KEY`,
`GOOGLE_SERVICE_ACCOUNT_JSON` (the full JSON string), `GOOGLE_SHEETS_KEY`.

> First run only: the DB is gitignored, so seed it once with `lh2 crawl && lh2 build`
> (locally or a one-off dispatch) before the nightly enrich has firms to work on.

## The export schema

The fixed 14 columns (do not reorder), plus an appended `Email` column (15th):

```
#, Company, Founder(s), Founder LinkedIn (verified), Contact Number,
SPOC 2 Linkedin, Contact Number, Incorp. Year, HQ / India delivery,
Approx. Headcount, Headcount source (approx.), Segment, Status, Notes, Email
```

## Tests

```bash
pytest -q                 # 65 tests, offline (no network / no API keys needed)
```
