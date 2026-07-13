
# Implementation Task: Wire Google Sheets Auto-Sync into LH2 Pipeline

## What to build

Add a `sheets_sync.py` module and a `lh2 sync` CLI command that pushes pipeline results from SQLite directly to a live Google Sheet after every enrichment run. The Google Cloud service account is already set up and the Sheet is shared with the bot.

## Context

- **Project:** `lh2_pipeline/` — a Python lead-sourcing pipeline with typer CLI (`lh2` command).
- **Existing flow:** `lh2 run` chains `crawl → build → enrich → score → export` (CSV). All data lives in `data/pipeline.sqlite`.
- **SQLite schema:** `raw_listings` → `companies` (deduped, gate-filtered by domain) → `people` (founders/SPOCs with `founder_name`, `linkedin_url`, `phone`, `email`, `confidence`, `provenance`). Inspect `src/lh2_pipeline/store.py` for exact column names.
- **Config:** `config.yaml` (all tunables), `.env` (API keys).
- **Existing export:** `src/lh2_pipeline/export/csv_writer.py` — produces 14-column CSVs. The Sheets sync is a parallel output channel, not a replacement.

## Credentials already in place

- `google_service_account.json` in project root (gitignored)
- Sheet is shared with the service account email as Editor
- Spreadsheet key is known — add to `config.yaml` under `sheets.spreadsheet_key`

## Dependencies to add

```
gspread>=6.0
google-auth>=2.0
```

Add to `pyproject.toml` or `requirements.txt` (check which the project uses) and install.

## What to implement

### 1. Config block

Add to `config.yaml`:

```yaml
sheets:
  enabled: true
  credentials_file: "google_service_account.json"
  spreadsheet_key: ""  # user fills this in
  qualified_tab: "Qualified Leads"
  review_tab: "Under Review"
  stats_tab: "Pipeline Stats"
```

Load this in `config.py` alongside existing config.

### 2. `src/lh2_pipeline/export/sheets_sync.py`

A `SheetsSyncer` class with three methods:

**`sync_qualified(db_path, start_index)`** — Append-only. Query SQLite for companies+people where ALL FOUR fields are present (founder_name, linkedin_url, phone, email) AND gate_pass=1. Check existing rows in the Sheet to avoid duplicates (match on company name or domain). Append only net-new rows. Include a "Synced At" timestamp column.

**`sync_review(db_path)`** — Overwrite mode (clear + rewrite). Query for leads with exactly 3 of 4 fields filled. Include a "Missing Field(s)" column showing which field is missing. These are re-try candidates.

**`sync_stats(db_path)`** — Append one row per run. Columns: Date, Firms Enriched (gate_pass count), Qualified (4/4), Review (3/4), Founder %, LinkedIn %, Phone %, Email %, All-Four %.

Key implementation details:

- Use `gspread.service_account()` or `Credentials.from_service_account_file()` with scopes for spreadsheets + drive.
- Auto-create tabs if they don't exist (with bold headers).
- Use `append_rows()` for batch writes (single API call, no rate limit issues).
- Match the existing 14-column export schema from `csv_writer.py` as closely as possible for the Qualified tab. Add Email column (the CSV schema predates the email requirement). Inspect `csv_writer.py` for exact column order.
- Column order for Qualified tab: #, Company, Founder(s), Founder LinkedIn (verified), Email, Contact Number, SPOC 2 Linkedin, Contact Number 2, Incorp. Year, HQ / India delivery, Approx. Headcount, Headcount source, Segment, Status, Notes, Synced At.

### 3. CLI command: `lh2 sync`

Add to `cli.py`:

```
lh2 sync [--db PATH] [--start-index N] [--stats-only]
```

- Reads sheets config from `config.yaml`
- If `sheets.enabled` is false, exit with message
- Otherwise run `sync_qualified` + `sync_review` + `sync_stats`
- Print summary: "✓ Synced X qualified + Y review leads to Sheets"

### 4. Wire into `lh2 run`

In `orchestrate.py`, after the existing export step, add a conditional sheets sync:

```python
if config.get("sheets", {}).get("enabled"):
    # import and call SheetsSyncer
    # sync_qualified, sync_review, sync_stats
```

This makes `lh2 run` automatically push to Sheets after every pipeline run.

## Important constraints

- **Append-only for Qualified tab** — never clear/overwrite it. Delivered leads must not disappear.
- **Overwrite for Review tab** — stale 3-of-4 leads should vanish once the missing field is filled.
- **Dedup before appending** — read existing company names/domains from the Sheet before appending to avoid duplicate rows on re-runs. The pipeline is designed to be idempotent; the sync should be too.
- **Never fabricate data** — blank cells are correct. Don't fill defaults.
- **Inspect the actual SQLite schema** in `store.py` before writing queries. Column names may differ from what I've described — use the real ones.
- **Error handling** — wrap API calls in try/except. If Sheets sync fails, log the error but don't crash the pipeline. The CSV export is the backup.

## Testing

After implementation:

1. Run `python -c "import gspread; ..."` quick connection test
2. Run `lh2 sync` manually and check the Google Sheet
3. Run `lh2 run` end-to-end and verify the Sheet updates
4. Run `lh2 sync` again and verify no duplicate rows appear

## Reference

Full design doc with code examples: see `google_sheets_sync_guide.md` in the project (already provided to the user). Adapt the code from there but always defer to the actual SQLite schema in `store.py`.
