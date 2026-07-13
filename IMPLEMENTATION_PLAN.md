# Implementation Plan — Scaling the LH2 Lead-Qualification Engine

> Companion to `ScalingPlan.md` (the research/strategy) and `PROJECT_CONTEXT.md`
> (current state). This doc is the **buildable checklist**: what to procure, what
> to code, and how the rate-limit/quota safety layer works. Nothing here is
> implemented yet — this is the agreed plan of record.

**Decisions locked (2026-07-13):**
- **Enrichment = SignalHire only, for now.** It's the only provider key the
  operator currently has — and it's a **paid key**, so its reveal returns
  **email + phone + LinkedIn bundled in one credit.** The waterfall/cascade is
  still built as the target architecture, but **only the SignalHire adapter ships
  in this phase**; the other paid providers (DIN tool, FullEnrich, Apollo) are
  **deferred** until keys exist. Spend tier Option B remains the eventual target.
- **Four fields ARE achievable this phase** via SignalHire alone: founder name +
  LinkedIn + Indian mobile + **email**. The current code deliberately ignores
  email (`signalhire.py` = "phones only") — that adapter gains email extraction.
- **No automated verification — the sales team verifies manually.** Second-source
  confirmation, email deliverability checks (ZeroBounce/NeverBounce), and the
  namesake/green-confidence machinery are **out of scope**: sales confirms a lead
  by actually calling / emailing. The pipeline's job is *find real values + record
  provenance*; never-fabricate still holds (blank beats guessed), but a found
  value is delivered as-is with its source, not gated on a verification verdict.
- **Immediate lever = DISCOVERY.** With enrichment on one provider, volume comes
  from more discovery sources: **verify the 5 dormant directory crawlers + add MCA.**
- **Google Maps / Places API: DEFERRED** to a later stage.
- **Runtime:** **local pilot** on the operator's machine via a shell command.
  Cloud scheduling (GitHub Actions / VPS) is **deferred** to a later stage.
- **Google Sheets direct write:** **deferred** (later stage). Export stays CSV/xlsx.
- **First code step:** none yet — this document. Next likely step (pending
  operator go-ahead): smoke-test the 5 dormant crawlers.

---

## 0. Build status (2026-07-13)

**Shipped & tested (64 tests passing, was 46):**
- **Net-new exclusion gate** — `transform/exclusions.py` harvests known names +
  canonical domains from the delivered ledger, master sheet, and AI-Labs list
  (unwrapping `=HYPERLINK`, reading Domain columns). Wired into `build`; live run
  now excludes **174 previously-mined firms**. Guardrail skips any file under
  `data/exports/` so the live export can't become a self-referential exclusion.
- **Email end-to-end** — SignalHire adapter now extracts email (work-first) from
  `contacts[]`; threaded through enrich → `people.email` (DB migrated in place) →
  new `Email` column appended to the export (15 cols; original 14 unchanged).
  `--require-full` is now four-field (name+LinkedIn+phone+email present).
- **Rate-limit + quota safety layer** — `ratelimit.py` (token bucket, 80% margin),
  `quota_ledger.py` (persistent `quota` table, daily/monthly reset), `governor.py`
  (per-provider). Wired into SignalHire: paces requests, charges the daily search
  quota, and the enrich loop **stops cleanly on 402/exhaustion** (resumable).
  Config: `providers.*` block.
- **Google Sheets sync** — `export/sheets_sync.py` (Qualified append-only / Under
  Review overwrite / Pipeline Stats), `lh2 sync` CLI, wired into `lh2 run`
  (fail-soft). Config: `sheets.*`. Creds gitignored.

**Verified live:** GoodFirms crawler (48 rows/page, all gate fields on listing).

**Crawler finding (2026-07-13):** all 5 dormant crawlers smoke-FAILed (0 rows).
Investigated TechBehemoths deeply and fixed it: real URL is `/companies/<city>`
(not `/companies/all/...`), cards are `.co-box`; selectors now confirmed live +
unit-tested → parses 24 named firms/city. **But** the listing card withholds
website (only ~3/24), founded-year, and employee-size — those live on each firm's
**profile page**. The gate needs founded+size, so listing-only firms can't pass.
→ **Making these directories useful requires a per-firm profile-page fetch**, a
real build per site, not a one-line selector fix (recalibrates the plan's "~1 hr
each"). GoodFirms remains the only source that puts all gate fields on the
listing. TechBehemoths left OFF until the profile-fetch step is built.

**E2E validation (2026-07-13):** crawl✓ build✓ enrich-search✓ export✓ sheets✓
(live auth + tabs + write). **Blocked:** SignalHire has **0 reveal credits** →
email/phone reveal returns 402 (the enrich loop stops cleanly, as designed).
Top up credits to validate live email extraction + fill the sheet.

**Operator action items:** (1) rename the service-account JSON to
`google_service_account.json` (or set `sheets.credentials_file`), share the sheet
with the service-account email as Editor, and paste `sheets.spreadsheet_key`;
(2) re-run `lh2 enrich` to populate emails on existing firms.

---

## 1. Objective & scope

Evolve the working `crawl → build → enrich → score → export` pipeline into a
**repeatable, resumable, quota-safe engine.** Target (eventual) vs **this phase**:

1. **Discovery** — target ~10,000 firms (directories + MCA + Google Maps).
   *This phase:* verify+enable the 5 dormant directory crawlers + add MCA registry.
   Google Maps deferred.
2. **Enrichment** — target a four-field multi-provider waterfall, India-phone-first.
   *This phase:* **SignalHire only**, 3-field (name + LinkedIn + phone), behind the
   new rate-limit/quota layer. Paid providers + required email deferred.
3. **Never exceeds any provider's rate limit or quota** — enforced proactively
   (rate limiter) and reactively (backoff/spillover), durable across restarts.
   *Built this phase* (applied to SignalHire now; scales to N providers later.)
4. Runs as a **single local shell command**; graduates to cloud later.

**Out of scope for this phase:** paid enrichment providers, required-email/four-field,
Google Maps, cloud scheduling, Google Sheets write-back, Option C (Cognism/Clay).
The architecture is built so each drops in later without rework.

---

## 2. What the operator must procure (accounts + API keys)

Everything goes in `.env` (gitignored). Split into **needed this phase** vs
**deferred** per the locked decisions.

### 2.1 Needed this phase
| Key / account | Env var | Cost | Notes |
|---|---|---|---|
| **SignalHire** (existing, **paid**) | `SIGNALHIRE_API_KEY` | credit + daily search quota | Only enrichment provider this phase; reveal = **email + phone + LinkedIn** in 1 credit |
| **data.gov.in** API key | `DATA_GOV_IN_API_KEY` | Free | For MCA registry ingest (discovery) |
| Clutch / TechBehemoths / Manifest / DesignRush / NASSCOM | — | Free (scrape) | **No keys** — selector verification only |
| Slack incoming webhook *(optional)* | `SLACK_WEBHOOK_URL` | Free | Run-summary / failure alert on the local run |

### 2.2 Deferred — extra enrichment providers (procure when expanding beyond SignalHire)
Target Option B, India-phone-first cascade. Adapters built only once keys land.
Email/second-source **verifiers are intentionally omitted** — sales verifies manually.
| Key / account | Env var | Cost | Role |
|---|---|---|---|
| **India MCA/DIN tool** — EasyLeadz "Mr. E" (API) *or* Surereach / CookLeads | `EASYLEADZ_API_KEY` (etc.) | Pay-per-credit, "no-find-no-charge" | **Phone primary** — biggest lever to lift ~40% mobile fill |
| **FullEnrich** | `FULLENRICH_API_KEY` | $29-55/mo entry, pay-per-found | Email + mobile backfill |
| **Apollo.io** | `APOLLO_API_KEY` | Paid tier for API (~$49-119/mo) | LinkedIn URL + email backfill |

### 2.3 Deferred — Google Maps discovery (later stage)
| Key / account | Env var | Cost | Notes |
|---|---|---|---|
| Google Cloud project + **Places API (New)** | `GOOGLE_MAPS_API_KEY` | 5k free calls/mo; full sweep <$100 | Enable billing; set a hard quota cap in the GCP console |

---

## 3. Target architecture

Extends the existing structure (`BaseCrawler`, write-through `cache`, injectable
clients, gates) — no rewrite. New/changed modules:

Legend: **[now]** ships this phase · **[later]** built when its key/decision lands.

```
src/lh2_pipeline/
  ratelimit.py          # NEW [now]  — token-bucket limiter, per provider
  quota_ledger.py       # NEW [now]  — persistent daily/monthly quota accounting (SQLite)
  providers/            # NEW        — one adapter per external provider, common interface
    base.py             #   [now]      Provider protocol: enrich(company, person) -> Result
    signalhire.py       #   [now]      (moved/refactored from enrich/signalhire.py)
    easyleadz.py        #   [later]    India DIN phone+email
    fullenrich.py       #   [later]    waterfall backfill
    apollo.py           #   [later]    LinkedIn + email
                        #   (no verify_email.py — sales verifies manually)
  enrich/
    waterfall.py        # NEW [now]  — cascade orchestration, early-exit, spillover
                        #              (runs with SignalHire-only until more adapters land)
    __init__.py         #   [now]      run_enrich() rewired to drive the waterfall
  crawl/
    mca_registry.py     # NEW [now]  — data.gov.in bulk ingest + director names
    googlemaps.py       # NEW [later]— Places API (New) discovery crawler
  export/csv_writer.py  # CHANGED [now]   — append Email column (Company Phone reserved)
  judge/confidence.py   # unchanged       — confidence stays informational (sales verifies)
```

**Data flow (unchanged shape, new sources):**
`raw_listings` (GoodFirms + Clutch + … + GoogleMaps + MCA) → `companies`
(canonical-domain dedup + gates) → `people` (waterfall four-field) → export.

---

## 4. Schema changes (email now sourced from SignalHire — THIS PHASE)

Email arrives with SignalHire's reveal, so the four-field deliverable is in scope
now. The 14-column export order is fixed — so we **append** new columns at the end
(never reorder existing ones):

- `Email` — the founder/decision-maker email from SignalHire.
- `Company Phone` — office/reception number **[deferred]** — only lands with the
  Google Maps discovery source; column reserved but empty this phase.

**`people` table addition:** `email`, `email_source` (provenance only — no
verification verdict, since sales verifies manually).
**`companies` table addition (deferred):** `company_phone`, `company_phone_source`.

**`--require-full` = four-field present:** founder name **and** LinkedIn **and**
phone **and** email all non-blank. No verification gate — a present, real value
qualifies; the sales team confirms on contact.

> Append-ready flow note: the master sheet in `Indian IT Services … (2).csv` will
> need the new `Email` column added on its side before appended rows line up.
> Flag to operator before first four-field delivery.

---

## 5. Rate-limit & quota safety layer (the "never hit the limit" requirement)

Four independent protections. Config-driven; adding a provider = one YAML block +
one adapter.

**(1) Per-provider token-bucket `RateLimiter`.** Each provider declares its
documented limits; we run at a **safety margin (default 0.8 = 80%)** of each.
Enforced dimensions: requests/sec, requests/min, requests/day, max concurrency
(async `httpx` + per-provider semaphore).

**(2) Persistent `QuotaLedger` (new `quota` table).** Consumption is written to
SQLite, **not** memory — a killed-and-restarted local run never double-spends or
forgets it was near a cap. Each provider declares its reset window
(`daily_utc` / `rolling_24h` / `monthly`); the ledger self-resets.

**(3) Reactive backpressure + waterfall spillover.** Honor `Retry-After`; on
`429`/`402`/`403` mark the provider exhausted for its window and **fall through to
the next provider in the cascade** (this is why a waterfall beats single-provider —
we sum multiple providers' daily caps). Backoff via `tenacity` (already a dep).

**(4) Pacing scheduler.** Daily batch size derived from
`min(remaining quota across the cascade)` so we *plan* the day to fit inside the
budget rather than sprinting into a wall. Targets the plan's ~55-110 firms/day.

### 5.1 Config schema (goes in `config.yaml`)
```yaml
providers:
  defaults:
    safety_margin: 0.8          # use 80% of every documented limit
    max_retries: 4
    backoff_base_seconds: 2
    honor_retry_after: true

  # --- enrichment cascade order (first = tried first, spillover downward) ---
  # This phase only SignalHire is enabled, so every field resolves to it alone.
  # The full target ordering is kept here so enabling a provider = one flip.
  cascade:
    phone:   [signalhire]       # target: [easyleadz, fullenrich, signalhire, apollo]
    email:   [signalhire]       # SignalHire reveal includes email (no verifier — sales verifies)
    linkedin:[signalhire]       # target: [apollo, fullenrich, signalhire]
    name:    [mca_registry, signalhire]   # target: [mca_registry, easyleadz, apollo, signalhire]

  signalhire:
    enabled: true               # the only enrichment provider this phase
    limits: { requests_per_minute: 60, search_per_day: 5000,
              person_items_per_minute: 600, concurrency: 3 }
    reset: daily_utc

  # --- deferred: flip enabled:true when the key lands (limits ⚠ = confirm live) ---
  easyleadz:
    enabled: false
    limits: { requests_per_minute: 60, requests_per_day: 1000, concurrency: 2 }
    reset: daily_utc
  fullenrich:
    enabled: false
    limits: { requests_per_minute: 30, requests_per_day: 2000, concurrency: 3 }
    reset: daily_utc
  apollo:
    enabled: false
    limits: { requests_per_minute: 50, requests_per_hour: 200, requests_per_day: 600,
              monthly_credits: 10000, concurrency: 3 }
    reset: monthly
  zerobounce:
    enabled: false
    limits: { requests_per_minute: 300, concurrency: 5 }
    reset: none
  google_places:
    enabled: false              # deferred discovery (later stage)
    limits: { requests_per_minute: 600, free_calls_per_month: 5000, concurrency: 5 }
    reset: monthly
```
> Numeric limits above are **placeholders** — each is confirmed against the
> provider's live docs before its adapter ships (marked ⚠ in the checklist).

### 5.2 `quota` table (DDL sketch)
```sql
CREATE TABLE IF NOT EXISTS quota (
    provider     TEXT NOT NULL,
    window_key   TEXT NOT NULL,   -- e.g. "2026-07-13" (daily) or "2026-07" (monthly)
    metric       TEXT NOT NULL,   -- "requests" | "credits" | "search"
    used         INTEGER NOT NULL DEFAULT 0,
    limit_value  INTEGER,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (provider, window_key, metric)
);
```

---

## 6. Discovery expansion — the immediate lever this phase

With enrichment pinned to SignalHire, discovery is where volume grows. All
crawlers paginate a directory **by city** (the 20 cities in `config.yaml`) and
write `raw_listings` (company name, website, city, founded year, size band,
segment). Ordered by leverage:

**What's scraped today:** GoodFirms only (verified live; produced all 4,964 raw
rows). The other five crawlers exist in code but are toggled `false` because
their URLs/selectors were never confirmed against the live sites.

1. **Verify + enable the 5 dormant directory crawlers** — no API keys, pure
   scraping. Each ~1 hr: `lh2 smoke <source>`, fix the URL + selectors at the top
   of its module against live DOM, flip `crawl.sources.<x>: true`.
   | Source | Live URL pattern (in code) | Note |
   |---|---|---|
   | Clutch | `clutch.co` IT-services/India + per-city | Cloudflare → Playwright path |
   | TechBehemoths | `techbehemoths.com/companies/all/{city}` | sitemap-crawlable, ~50k global |
   | The Manifest | `themanifest.com` India software-dev | overlaps Clutch/GoodFirms |
   | DesignRush | `designrush.com` India software-dev | cross-fill |
   | NASSCOM | `nasscom.in` member dir, `?location=` facet | India-only by definition |
   > Reality check: directories overlap heavily and share the canonical-domain
   > dedup, so this won't multiply the universe — its main win is **cross-filling
   > missing founded-year/size** plus some net-new long-tail firms.

2. **MCA `mca_registry`** — `data.gov.in` bulk CSV ingest for the authoritative
   backbone + Tier-2/3 coverage + **director names** (feeds the `registry` source,
   unlocks **green** confidence, and adds firms the directories miss — the one
   source that genuinely grows the universe). Needs the free `DATA_GOV_IN_API_KEY`.

3. **Google Maps `GoogleMapsCrawler` — DEFERRED (later stage).** When enabled:
   Places API (New), httpx JSON (no Playwright), grid-tile each city into
   <60-result viewports, 5 query variations, dedup by `place_id`, Pro-tier fields
   only, noise gates (reject `electronics_store`/`computer_support`/…, require a
   website, review sweet-spot 5-50). See ScalingPlan.md §Google Maps guide.

---

## 7. Confidence / consensus (informational — not a delivery gate)

Since the sales team verifies manually, confidence is **informational only** — it
never blocks a row from delivery. Keep the existing behavior, don't build more:

- The existing confidence field + `reconcile_registry_vs_aggregator` rule keep
  running and stay in the export (useful triage signal for sales).
- When MCA registry lands, it naturally becomes a second independent source and
  lifts some founders to **green** — a free byproduct, not a goal to engineer.
- No verifier verdicts, no namesake-guard expansion, no green-gating of output.

---

## 8. Local pilot run (shell command)

Single resumable, idempotent, quota-safe command (SignalHire-only enrichment):

```bash
lh2 run --max-enrich 60          # crawl→build→enrich→score→export; resumes, never re-bills
# or step-wise:
lh2 crawl                        # all enabled directory sources × cities
lh2 build                        # dedupe + gates
lh2 enrich --max-enrich 60       # SignalHire (email+phone+LinkedIn) behind the rate limiter
lh2 score
lh2 export --require-full --hyperlinked   # four-field deliverable (email = unverified this phase)
```

Behavior: reads the quota ledger → computes today's safe batch from remaining
SignalHire search quota → enriches with per-provider rate limiting → writes
provenance/confidence → firms missing fields re-queue for the next day. Optional
`--dry-run` prints the planned quota spend without calling SignalHire. A wrapper
script (`run_pilot.sh`) chains this + prints a run summary (and posts to Slack if
`SLACK_WEBHOOK_URL` is set). No verification gate — delivered rows carry real,
provenance-tagged values that the sales team confirms on contact.

---

## 9. Staged build checklist

Legend: ⚠ = needs live site/provider-doc confirmation before shipping.
Ordered by the locked priorities: **discovery first, SignalHire-only enrichment,
paid providers + four-field + Maps deferred.**

### This phase

**Stage A — Discovery (the immediate lever)**
- [ ] `lh2 smoke` each dormant crawler; fix URL+selectors vs live DOM ⚠
  - [ ] Clutch  - [ ] TechBehemoths  - [ ] The Manifest  - [ ] DesignRush  - [ ] NASSCOM
- [ ] Flip verified sources `true` in `config.yaml`; re-crawl + `build`
- [ ] `crawl/mca_registry.py` data.gov.in ingest + director names ⚠

**Stage B — Safety core + waterfall interface (SignalHire-only)** *(no new keys)*
- [ ] `ratelimit.py` token-bucket limiter + tests
- [ ] `quota_ledger.py` + `quota` table + reset windows + tests
- [ ] `providers/base.py` common `enrich()` interface
- [ ] Refactor SignalHire into `providers/signalhire.py` behind the interface
- [ ] **Add email extraction to the SignalHire adapter** (`type=email` from `contacts[]`)
- [ ] `enrich/waterfall.py` cascade (SignalHire-only) + early-exit + 402 backoff + tests
- [ ] `providers.*` config schema + loader

**Stage C — Four-field schema (email via SignalHire)**
- [ ] `people`.email/email_source migration
- [ ] Export: append `Email` column (`Company Phone` reserved/empty)
- [ ] `--require-full` = name + LinkedIn + phone + email present (no verification gate)
- [ ] Flag master-sheet `Email` column addition to operator

**Stage D — Pilot polish**
- [ ] Pacing scheduler (batch = min remaining SignalHire quota)
- [ ] `run_pilot.sh` wrapper + run summary + optional Slack
- [ ] `lh2 run --dry-run` quota preview

### Deferred (built when the gating key/decision lands)

**Extra enrichment providers** *(each: adapter + rate-limit config + verified limits ⚠)*
- [ ] `providers/easyleadz.py` (phone+email primary) ⚠
- [ ] `providers/fullenrich.py` (backfill) ⚠
- [ ] `providers/apollo.py` (LinkedIn+email) ⚠
- [ ] **Stage-0 bake-off:** 100 firms via SignalHire vs DIN tool vs Apollo →
      decide final cascade order (if DIN mobiles >60% vs SignalHire ~40% → phone primary)

**Google Maps discovery**
- [ ] `crawl/googlemaps.py` grid-tiling + noise gates + `place_id` cache ⚠
- [ ] `companies`.company_phone migration + populate `Company Phone` column

**Cloud** — GitHub Actions / VPS scheduling (ledger already makes it restart-safe)

---

## 10. Open questions / to confirm before/along the way

- **DIN tool choice:** start with EasyLeadz (has a clean API) unless the bake-off
  says otherwise. Confirm it exposes an API on your plan (some are extension-only).
- **Every ⚠ limit** in §5.1 confirmed against live docs before that adapter ships.
- **Master-sheet columns:** operator adds the new email/company-phone columns on
  the sheet side before first four-field delivery.
- **Verifier choice:** ZeroBounce vs NeverBounce (functionally equivalent here).
- **DPDP/ToS posture** (ScalingPlan §Caveats): prefer registry/official-API data
  for personal contact fields; store provenance; not legal advice.

---

## 11. Deferred (explicitly later, designed-for now)

- **Extra enrichment providers** (DIN tool, FullEnrich, Apollo) + the Stage-0
  bake-off — SignalHire-only until keys land.
- **Google Maps / Places API discovery** + the `Company Phone` column (later stage).
- **Cloud scheduling** (GitHub Actions cron or $5-20/mo VPS + the persistent ledger).
- **Google Sheets API** direct write-back (service account).
- **Option C** providers (Cognism Diamond, Clay orchestration).
