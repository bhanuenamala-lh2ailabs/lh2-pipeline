# BUILD SPEC — LH2 Indian IT-Services Sourcing Pipeline

**Audience:** Claude Code (the coding agent building this).
**Goal:** A repeatable, mostly-unattended pipeline that produces a few thousand verified Indian IT-services companies as target rows for codebase acquisition — sourced from public directories + the company registry, enriched with contacts, confidence-scored, and exported as CSV in a fixed 14-column schema.

Build this **phase by phase, in order**. Each phase has a Definition of Done. Do not start a phase until the previous one passes its DoD. Ask the human before deviating from the schema, the dedupe key, or the accuracy rules below.

---

## 0. NON-NEGOTIABLE RULES (apply to every phase)

These are hard constraints. Violating them silently corrupts the dataset, which is worse than a smaller dataset.

1. **Never fabricate or pattern-guess data.** A blank cell is correct; an invented value is a bug. This applies especially to:
   - **Founder LinkedIn URLs** — only ever populated when confirmed to belong to the right person at the right company (see Phase 4). Never constructed from a name. If unconfirmed → blank.
   - **Phone numbers** — only from the Signalhire API response. Never generated.
   - **Founder names** — only from an authoritative source (registry, company site). If unknown → literal string `(verify)`.
2. **Registry beats aggregators.** When MCA/ZaubaCorp director data conflicts with a directory/aggregator, the registry wins. (Real example to encode as a test case: for "Promatics Technologies" the registry founders are Arpit Jain & Indu Jain — an aggregator's "Rauf Saiyed" is wrong.)
3. **Idempotent + cached.** Re-running the pipeline must not re-scrape or re-bill enrichment for rows already done. Everything is cached keyed by a stable identifier (canonical domain). A crash mid-run resumes, it doesn't restart.
4. **Polite crawling.** Respect rate limits, randomized delays, one concurrent request per host by default, identifiable but rotating user agents, honor robots where reasonable. Prefer official APIs/exports over scraping where a source offers them. Make crawl rate a config value, default conservative.
5. **Secrets via env only.** API keys come from a `.env` file (gitignored). Never hardcode keys. Never log full keys.
6. **Every value carries provenance.** Each enriched field stores which source produced it and when, so a human reviewing an "amber" row can see why.

---

## 1. TECH STACK & PROJECT LAYOUT

**Language/runtime:** Python 3.11+.

**Core libraries:**
- `playwright` (headless Chromium) — for the directory sites (Cloudflare-protected, server/JS-rendered). NOT `requests` for those.
- `httpx` — for clean JSON APIs (Signalhire, Claude, optional Proxycurl).
- `selectolax` or `beautifulsoup4` — HTML parsing of fetched pages.
- `pydantic` v2 — schema/validation for every record.
- `tldextract` — canonical registered-domain extraction (the dedupe key).
- `rapidfuzz` — fuzzy name matching (namesake guard).
- `anthropic` — Claude API for parsing/judgment glue.
- `duckdb` **or** `sqlite3` — the local data store + cache (DuckDB preferred for CSV/Parquet ergonomics; SQLite fine if simpler).
- `typer` — CLI.
- `pyyaml`, `python-dotenv`, `tenacity` (retries), `structlog` or stdlib `logging`.

**Layout:**
```
lh2_pipeline/
  config.yaml                # all tunables (filters, cities, rate limits, sources on/off)
  .env.example               # documents required keys; real .env is gitignored
  pyproject.toml
  README.md
  data/
    pipeline.duckdb          # the spine (or sqlite)
    raw_html/                # cached raw pages (gzip), keyed by url hash
    exports/                 # generated CSVs
  src/lh2_pipeline/
    __init__.py
    config.py                # load+validate config.yaml and env
    models.py                # pydantic models + DB schema
    store.py                 # DB access, upserts, cache get/set
    crawl/
      base.py                # BaseCrawler: fetch, throttle, cache, retry
      goodfirms.py
      clutch.py
      techbehemoths.py
      designrush.py
      manifest.py
      nasscom.py
      registry_zauba.py      # MCA/ZaubaCorp director lookup
    transform/
      canonicalize.py        # domain canonicalization, field normalization
      dedupe.py
      gates.py               # filter to qualifying firms
    enrich/
      signalhire.py          # contacts ONLY (ignore its linkedin field)
      registry_founders.py   # founder names from registry (Claude-assisted parse)
      linkedin_optional.py   # Proxycurl/Coresignal adapter, OFF by default
    judge/
      claude_client.py       # thin wrapper: batching, retry, response caching
      extract.py             # director extraction prompt
      match.py               # person<->company match prompt (namesake guard)
      confidence.py          # green/amber/red scoring
    export/
      csv_writer.py          # 14-col schema + optional HYPERLINK wrapping
    cli.py                   # `lh2 crawl`, `lh2 build`, `lh2 enrich`, `lh2 export`, `lh2 run`
  tests/
```

**DoD Phase 1:** repo scaffolds, `pip install -e .` works, `lh2 --help` lists the commands (even if stubbed), config + .env load and validate, DB initializes with empty tables.

---

## 2. DATA MODEL

Use these tables (DuckDB/SQLite). Pydantic models mirror them.

**`raw_listings`** — one row per (source, listing) as scraped, before dedupe:
```
id (pk), source, source_url, scraped_at,
company_name, website_raw, city, founded_year_raw, size_raw,
segment_raw, extra_json
```

**`companies`** — one row per unique firm (post-dedupe, post-gate):
```
domain (pk, canonical registered domain),   # dedupe key
company_name, website,
city, state, hq_country,
founded_year, founded_source,
size_band, size_source,                      # e.g. "10-49","50-249"
segment,
status,                                      # Independent / Acquired(..) / etc, default blank
sources_json,                                # list of {source, url} it appeared on
gate_pass (bool), gate_reason,
created_at, updated_at
```

**`people`** — founders/SPOCs linked to a company:
```
id (pk), domain (fk),
name, role,                                  # e.g. "Founder & CEO"
name_source,                                 # registry / company_site / directory
linkedin_url, linkedin_source, linkedin_confirmed (bool),
phone, phone_source,                         # phone_source = signalhire
is_primary (bool),                           # SPOC 1 vs SPOC 2
confidence,                                  # green / amber / red
notes
```

**`cache`** — generic enrichment/LLM cache:
```
key (pk),                                     # e.g. "signalhire:domain", "claude:extract:<hash>"
value_json, created_at
```
All external calls check `cache` first and write through on success.

**DoD Phase 2 (model):** migrations create all tables; `store.py` exposes typed upsert + cache get/set; a unit test inserts and reads back a company + person.

---

## 3. PHASE 1 — SOURCE THE RAW UNIVERSE

Build one crawler per source, all inheriting `BaseCrawler` (handles throttle, raw-HTML cache, retry/backoff, user-agent rotation). Each crawler's job: enumerate the India software-development/IT-services listings for the configured cities and emit `raw_listings` rows. Capture whatever the listing exposes — name, website, city, founded year, size band, segment — leaving blanks where a field isn't present (do not infer).

**Sources (config-toggleable, build in this priority order):**
1. **GoodFirms** — India software-development directory + per-city pages. Listing rows expose founded year, team size, location inline. Highest structured yield.
2. **Clutch** — `it-services/india` and `developers` + city pages; left-rail filters for size/rate. Profiles carry year founded, employees, hourly rate, min project size.
3. **TechBehemoths** — per-city company lists; company profile pages give "founded YYYY, N employees".
4. **The Manifest** and **DesignRush** — India software-dev directories; secondary coverage / cross-fill.
5. **NASSCOM member directory** — India-only by definition; good for breadth and as an India-HQ signal.

Pagination: each source paginates by city × (optionally) size band. Drive the full city list from `config.yaml` (Bengaluru, Pune, Hyderabad, Ahmedabad, Indore, Jaipur, Noida, Gurugram, Delhi, Chennai, Coimbatore, Kochi, Mumbai, Kolkata, Chandigarh/Mohali, Surat, Vadodara, Nagpur, Bhopal, Trivandrum — extend freely).

**Implementation notes for the agent:**
- Selectors WILL break over time — isolate each source's CSS/XPath selectors at the top of its module with a comment, so they're easy to fix. Add a per-source "smoke test" that fetches one known city page and asserts it extracted ≥1 row with a non-empty company name.
- Cache every fetched page to `data/raw_html/` (gzipped, keyed by URL hash). Re-runs read cache unless `--refresh`.
- If a source hard-blocks (Cloudflare challenge), log it, skip gracefully, continue other sources. Do not crash the run.
- Make concurrency + delay config values. Default: 1 worker/host, 2–5s randomized delay.

**DoD Phase 1:** `lh2 crawl --source goodfirms --city pune` populates `raw_listings`; smoke tests pass for each enabled source; a full `lh2 crawl` across cities yields several thousand raw rows total.

---

## 4. PHASE 2 — CANONICALIZE, DEDUPE, GATE-FILTER

Transform `raw_listings` → `companies`.

**Canonicalize:**
- Website → canonical registered domain via `tldextract` (lowercase, strip `www`, strip path/query, keep registered domain e.g. `cmarix.com`). This is the **dedupe key**. If a listing has no website, attempt to resolve one from the company name via a single search only if reliable; otherwise hold it in a `no_domain` bucket for human review rather than guessing.
- Normalize `founded_year_raw` → int (handle "since 2015", "11+ years" → derive approx and tag as approximate; "two decades" → `~2005 (verify)`).
- Normalize `size_raw` → band in {`10-49`, `50-249`} (or `<10`, `250+` for exclusion). Keep the raw string in `size_source` provenance.

**Dedupe:** group `raw_listings` by canonical domain. Merge into one `companies` row, unioning the `sources_json` list and keeping the most specific founded/size values. Same firm on 4 directories + 5 city pages collapses to one row.

**Gate-filter** (config-driven thresholds):
- `hq_country == India` (or India-delivery; flag foreign-incorporated in notes).
- services-model (directory listing implies this; exclude pure-product/SaaS and pure staffing where detectable).
- `founded_year <= config.founded_max_year` (default 2022).
- `size_band in {10-49, 50-249}` (exclude `<10` and `250+`; flag near-ceiling firms in notes).
- Exclude a config blocklist of large outsourcers (TCS, Infosys, Wipro, HCL, Tech Mahindra, LTIMindtree, Mphasis, Persistent, Coforge, etc.).
- Exclude a config blocklist of **already-known firms** (the existing ~130 LH2 already has) so output is net-new.

Rows failing a gate are kept in `companies` with `gate_pass=false` + `gate_reason` (don't delete — useful denominator and audit trail).

**DoD Phase 2:** `lh2 build` produces a deduped `companies` table; counts logged (raw → unique → passing gates); spot-check that a firm appearing on 3 sources is one row with 3 sources listed.

---

## 5. PHASE 3 — ENRICH (FOUNDERS + CONTACTS)

Only enrich `gate_pass=true` companies. Everything here is cached by domain.

### 5a. Founder names from the registry (authoritative)
- `registry_zauba.py`: for each domain/company, look up the company on MCA/ZaubaCorp (by name + city) and fetch the directors/partners page. **Consult the current ZaubaCorp/MCA access method and structure — do not assume an endpoint; verify against the live site/docs.** It's Cloudflare-class, so route through the Playwright `BaseCrawler`.
- `judge/extract.py`: pass the fetched director/leadership text to Claude (Haiku — cheap, this is extraction not reasoning) to return structured `{name, role}` list. Prompt template:

  > System: You extract company directors/founders from registry text. Output strict JSON only: a list of objects `{ "name": str, "role": str }`. Use only names present in the text. If none, return `[]`. No commentary.
  > User: `<company name>` / `<city>` / `<raw registry text>`

- Also pull founder/leadership from the **company's own site** (`/about`, `/team`, `/leadership`) via a light fetch + the same extraction prompt, as a second source. Company-site title (e.g., "Founder & CEO") is good for role; registry is good for legal ground truth.
- Write `people` rows with `name_source` = `registry` or `company_site`. Mark the primary founder `is_primary=true`; a clear second founder becomes SPOC 2.

### 5b. Contacts via Signalhire API (numbers only)
- `signalhire.py`: call the Signalhire API for each company/person to get **phone numbers**. **Use the official Signalhire API docs for exact endpoints/params — do not invent them.** Auth from `SIGNALHIRE_API_KEY`.
- **Ignore the LinkedIn field in the Signalhire response.** It is unreliable for this segment (namesake mismatches) and must not be written to `people.linkedin_url`. Pull `phone` only; set `phone_source = signalhire`.
- Normalize numbers to E.164 (`+91…`).
- Cache by domain; never re-bill a cached company.

### 5c. LinkedIn — left blank by default
- Pipeline default: `people.linkedin_url` stays **blank** unless confirmed in Phase 4 from a trusted LinkedIn-derived source.
- `linkedin_optional.py`: an adapter for **Proxycurl or Coresignal** (company-domain → people → real LinkedIn URLs), **OFF by default** behind a config flag. These are LinkedIn-derived (different mechanism from Signalhire's identity-resolution guess) and are the only paid component — wire it but don't enable until the human decides it's worth the per-record cost.
- Provide a **human-review export** (Phase 6) listing the founder name + company + domain for rows missing LinkedIn, formatted for fast filling via LinkedIn Sales Navigator's company "People" filter.

**DoD Phase 3:** for a sample of 25 gate-passing firms, `people` rows are populated with registry founder names, phone numbers from Signalhire, and `linkedin_url` blank; cache prevents re-calls on re-run.

---

## 6. PHASE 4 — CONFIDENCE SCORING + NAMESAKE GUARD

This is what lets you trust thousands of rows without eyeballing each.

For each `people` row, compute `confidence`:
- **green** — founder name agrees across ≥2 independent sources (e.g., registry name ≈ company-site name via `rapidfuzz` ≥ threshold) AND, if a LinkedIn URL is present, it passed the match check below.
- **amber** — name from a single source, or sources mildly disagree, or LinkedIn present but match uncertain.
- **red** — only a weak/aggregator source, or unresolved name conflict.

**Namesake guard (only when a LinkedIn URL is being considered, e.g., from Proxycurl):** before writing any `linkedin_url`, run `judge/match.py` — give Claude the founder name + company + city + the candidate profile's headline/experience text and ask:

  > System: Decide if this LinkedIn profile belongs to the named person AT the named company. Output JSON `{ "match": "yes"|"no"|"uncertain", "reason": str }`. "yes" ONLY if the profile's current role/experience explicitly references that company. Name-only similarity is "no".
  > User: name / company / city / profile text

Only `match=="yes"` sets `linkedin_confirmed=true` and writes the URL. `"uncertain"`/`"no"` → leave blank, note the reason.

Also encode the **registry-overrides-aggregator** rule as a deterministic check: if registry name and aggregator name conflict, keep registry, set a note, and don't let the aggregator name leak into the output.

**DoD Phase 4:** every `people` row has a confidence tag; a test with a deliberately wrong namesake profile returns `match=="no"` and leaves LinkedIn blank.

---

## 7. PHASE 5 — EXPORT (14-COLUMN CSV)

`export/csv_writer.py` generates the deliverable from the DB. **Exact column order (do not change):**

```
#, Company, Founder(s), Founder LinkedIn (verified), Contact Number,
SPOC 2 Linkedin, Contact Number, Incorp. Year, HQ / India delivery,
Approx. Headcount, Headcount source (approx.), Segment, Status, Notes
```

Mapping:
- `Founder(s)`: primary founder + (if present) second founder, as `"Name (Role); Name (Role)"`. Unknown → `(verify)`.
- `Founder LinkedIn (verified)`: primary founder's URL **only if `linkedin_confirmed`**, else blank.
- First `Contact Number`: primary founder phone (Signalhire). Second `Contact Number`: SPOC 2 phone.
- `SPOC 2 Linkedin`: second founder's confirmed URL, else blank.
- `Incorp. Year`, `HQ / India delivery`, `Approx. Headcount`, `Headcount source (approx.)`, `Segment`, `Status`: from `companies`.
- `Notes`: provenance caveats — "LI tentative", "no founder found - pull MCA", founded-year mismatch, near-250 ceiling, foreign incorporation, registry-vs-aggregator override, etc.

**Two export variants** (flag):
- Plain CSV (above).
- **Hyperlinked CSV** — wrap the `Company` cell value as `=HYPERLINK("<url>","<Company>")`. Use the direct website where known; otherwise a Google-search resolver URL `https://www.google.com/search?q=<Company+City+software+company>` (always lands on the company, never a wrong/broken domain). CSV-quote the formula properly (csv writer handles the doubling).
- Also emit the **LinkedIn human-review sheet**: `Company, Domain, Founder name, City, [blank LinkedIn]` for fast Sales-Navigator filling.

Google Sheets import note for the human (put in README): File → Import → Append → tick **"Convert text to numbers, dates, and formulas"** so `=HYPERLINK` renders; pasting evaluates automatically.

Output convention: also offer an `.xlsx` writer matching LH2 house style (navy header `#1F3864`, Arial 10, white bold headers, banded rows white/`EAF0F8`, freeze panes at A3 i.e. header on row, auto-filter on all columns) — optional, behind a flag.

**DoD Phase 5:** `lh2 export --hyperlinked` writes a 14-column CSV that imports cleanly into Sheets with clickable names; founder/LinkedIn columns obey the blank-unless-confirmed rule.

---

## 8. PHASE 6 — ORCHESTRATION, CACHING, RE-RUNS

- `lh2 run` chains: crawl → build → enrich → score → export, each step skippable via flags, each resumable.
- **Incremental mode:** `lh2 run --since <date>` only processes companies not already enriched (new firms from fresh crawls), so a monthly re-run is cheap.
- **Caching guarantees:** no external call (directory page, Signalhire, Claude, Proxycurl) fires if its cache key exists, unless `--refresh`.
- **Cost guardrails:** log per-run counts of Signalhire calls and Claude tokens; add a `--max-enrich N` cap so a runaway run can't drain the Signalhire credits.
- **Claude usage discipline:** small single-purpose prompts (one extraction / one match per call), use Haiku for extraction+matching, batch where the SDK allows, cache every response. Never send giant prompts or re-run cached judgments.
- **Scheduling (optional):** a cron/GitHub-Actions entry running `lh2 run --since` monthly. Build it but leave disabled until the human enables.

**DoD Phase 6:** a second consecutive `lh2 run` with no `--refresh` makes ~zero external calls (all cache hits) and re-produces the same export.

---

## 9. CROSS-CUTTING: TESTING, LOGGING, DOCS

- **Tests:** smoke test per crawler (parses ≥1 row), dedupe test (multi-source firm → one row), gate test (a 300-employee firm is excluded), namesake test (wrong profile → blank), schema test (export has exactly the 14 columns in order).
- **Logging:** structured, per-phase counts (rows in/out), per-source success/skip, enrichment hit/miss, cost counters. Errors never crash the whole run — log, skip, continue.
- **README:** how to set keys, run each phase, the Sheets import tip, how to fix a broken selector, and the accuracy rules restated for whoever maintains it.
- **Legal/ToS note in README:** several directories restrict scraping in their terms; keep crawl rates polite, prefer official APIs/exports where offered, and treat this as the human operator's call.

---

## 10. SUGGESTED BUILD ORDER (so the human sees value early)

1. Phases 0–2 first → you can already produce a few-thousand-row company list (no founders/contacts yet). That alone is useful.
2. Phase 3b (Signalhire contacts) → adds phone numbers.
3. Phase 3a + 4 (registry founders + confidence) → adds trustworthy founder names.
4. Phase 5 → the deliverable CSV.
5. Phase 6 → make it repeatable/cheap.
6. LinkedIn (Proxycurl) only if the human enables it after seeing fill-rates; otherwise the human-review sheet covers it.

**Start with Phase 0. Confirm the config.yaml shape and the column schema with the human before writing crawlers.**