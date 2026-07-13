# LH2 IT-Services Sourcing Pipeline — Full Project Context & Scaling Plan

> **Purpose of this document:** a complete, self-contained brief you can hand to
> Claude (or any AI) to continue/scale this project. It covers what the project
> is, what's built, the hard-won learnings, the exact commands, and a concrete
> roadmap to capture more companies from **every source possible**.

---

## 1. What this project is

A repeatable pipeline that produces **verified Indian IT-services companies** as
acquisition targets (for codebase/team acquisition), sourced from public
directories + registries, enriched with **founder name + LinkedIn + phone**,
confidence-scored, and exported as CSV in a fixed 14-column schema — appendable
to a master list.

**Target profile & filtering rules:** see `TARGETING_CRITERIA.md` (India-based IT
*services* firms, ~10–249 employees, founded ≤2022, independent, net-new).

**Core principle:** never fabricate. A blank cell is correct; an invented value
is a bug. Founder names/LinkedIn/phones only from verifiable sources.

---

## 2. Current status (as of last session)

**Built & working:**
- Full pipeline: `crawl → build → enrich → score → export`, 46 passing tests.
- **GoodFirms crawler** verified live (all 20 cities).
- **Signalhire** enrichment (2-step: search → enrich) working — founder name +
  LinkedIn + phone.
- **Company-site → Claude Haiku** founder extraction (currently OFF for speed).
- Confidence scoring + namesake guard + registry-overrides-aggregator rule.
- 14-column export: plain, hyperlinked, xlsx, LinkedIn-review sheet,
  **append-ready** (matches an existing sheet's columns + continues numbering,
  with `--require-full`, `--exclude-file`, `--limit`, `--start-index` filters).

**Delivered:**
- `data/exports/append_ready.csv` — 100 net-new firms (#130–229): company
  (hyperlinked), founders, LinkedIn (66%), phones (56%).
- `AI Labs to do - filled.csv` — 108 firms researched via web (founders 79%,
  LinkedIn 64%) + `data/exports/ailabs_research_results.csv` (source+confidence).
- **Staged pool: ~1,587 net-new gate-passing firms** ready to enrich (from a
  4,965-row GoodFirms crawl → 1,687 gate-pass).

**Blocked / pending:**
- Enriching the next 400 is gated on the **Signalhire daily search quota**
  (see §5). Resume when it resets.
- ZaubaCorp/MCA registry (authoritative founders) not yet wired.
- Clutch/TechBehemoths/Manifest/DesignRush/NASSCOM crawlers built but **not
  live-verified** (selectors/URLs need confirming).

---

## 3. Tech stack & layout

- **Python 3.11+** (dev machine runs 3.14). **SQLite** store (not DuckDB — 3.14
  wheel risk; `store.py` isolates this).
- **Playwright** (headless Chromium, async API) for Cloudflare-class directory
  sites. **httpx** for JSON APIs. **BeautifulSoup** for parsing. **pydantic v2**,
  **tldextract** (dedupe key), **rapidfuzz** (fuzzy match), **anthropic** (Haiku),
  **typer** (CLI).

```
lh2_pipeline/
  config.yaml            # all tunables (cities, sources, gates, enrich, judge)
  .env                   # ANTHROPIC_API_KEY, SIGNALHIRE_API_KEY (gitignored)
  src/lh2_pipeline/
    config.py  models.py  store.py  logging_setup.py  cli.py  orchestrate.py
    crawl/     base.py (fetch/throttle/cache/retry/UA/robots), goodfirms.py, clutch.py,
               techbehemoths.py, manifest.py, designrush.py, nasscom.py, parsing.py
    transform/ canonicalize.py (domain/founded/size), dedupe.py, gates.py
    enrich/    signalhire.py, company_site.py, registry_founders.py, linkedin_optional.py, phones.py
    judge/     claude_client.py, extract.py, match.py, confidence.py
    export/    csv_writer.py
  data/        pipeline.sqlite, raw_html/ (gzip cache), exports/, delivered_domains.txt
  tests/
```

**Data model (SQLite):** `raw_listings` (scraped rows) → `companies` (deduped by
canonical domain, gate-flagged) → `people` (founders/SPOCs) + `cache`
(write-through for every external call, so re-runs never re-bill).

---

## 4. The pipeline, phase by phase

| Phase | Command | What it does |
|---|---|---|
| **Crawl** | `lh2 crawl [--source --city]` | Directory sites → `raw_listings` (gzip-cached, polite, robots-configurable) |
| **Build** | `lh2 build` | Canonicalize domain, dedupe, gate-filter, exclude known → `companies` |
| **Enrich** | `lh2 enrich [--max-enrich N]` | Founders (Signalhire title-search + optional company-site→Claude) + LinkedIn + phone; cached by domain/name |
| **Score** | `lh2 score` | Confidence (green/amber/red) + namesake guard |
| **Export** | `lh2 export [--hyperlinked --xlsx --append-to --require-full --exclude-file --limit --start-index]` | 14-col CSV deliverable |
| **Run** | `lh2 run` | Chains all, resumable, idempotent |

**14-column schema (do not change order):**
`#, Company, Founder(s), Founder LinkedIn (verified), Contact Number, SPOC 2 Linkedin, Contact Number, Incorp. Year, HQ / India delivery, Approx. Headcount, Headcount source (approx.), Segment, Status, Notes`

---

## 5. Hard-won learnings (READ before scaling)

These cost real time to discover — don't re-learn them:

### Signalhire (the phone/LinkedIn source)
- **Two separate limits:** (a) **credits** — for contact reveals (enrich); "no
  find, no charge"; ~1 credit/founder. (b) **daily search quota** — for
  `searchByQuery`; **this is the real bottleneck** and returns HTTP **402** when
  exhausted. Credits ≠ search quota.
- **API is 2-step:** `POST /candidate/searchByQuery` (find profile by
  `currentCompany`/`currentPastCompany`/`fullName`/`currentTitle` → returns
  `uid` + `experience[]`) → `POST /candidate/search` with `{items:[uid],
  withoutWaterfall:true}` (reveal → `contacts[]` phones + `social[]` LinkedIn `type:"li"`).
- **Credits are in the response body** `{"credits": N}`, not a header.
- **Do NOT pass company HQ city as the person's `location`** — Signalhire filters
  on the *person's* location, which differs, and zeroes the match.
- **Match by company in `experience[]`**, not top-level fields. This is what makes
  the returned LinkedIn trustworthy (it's the right person at the right company).
- For **deadpooled** (shut-down) companies, search by `currentPastCompany`, not
  `currentCompany` (founder's current employer is now different).
- **Search API access** may need enabling by Signalhire support for some accounts.

### Environment / infra
- **Python 3.14 + Playwright:** `greenlet` fails to import with "DLL load failed"
  because the **Microsoft Visual C++ Redistributable was missing**. Fix: install
  VC++ redist (`winget install Microsoft.VCRedist.2015+.x64`). Playwright's async
  AND sync APIs both import greenlet.
- **GoodFirms is a Next.js/React app.** Correct URL:
  `https://www.goodfirms.co/directory/city/top-software-development-companies/<slug>?page=N`
  (48 firms/page). City slug quirks: **Bengaluru → `bangalore`**, Gurugram →
  `gurgaon`, Trivandrum → `thiruvananthapuram`. Card selectors: `li.firm-wrapper`,
  `h3.firm-name a`, `.firm-urls a.visit-website`, `.firm-founded span`,
  `.firm-employees span`, `.firm-location span`.
- **Selectors WILL break.** Each crawler isolates its CSS selectors at the top of
  its module + has a smoke test (`lh2 smoke <source>`).

### Company-site founder extraction
- Grab **team/leadership pages first** (not the first page with any text —
  /about-us is usually generic marketing with no names). Still only ~20% of firms
  name founders in scrapeable text → **registry or Signalhire title-search is the
  higher-yield path.**

### Fill-rate reality (per 100 firms, Signalhire-only path)
- Founders ~74%, LinkedIn ~66%, phones ~56%, all-three ~50–56%. So **~2× the pool
  must be enriched** to hit a target count of fully-filled rows.
- **Cost:** ~$0.11 Claude + ~1 Signalhire credit per firm. Money is NOT the
  constraint — the daily search quota is.

---

## 6. Commands cheat-sheet

```bash
# setup
pip install -e ".[all]" && python -m playwright install chromium
lh2 config-check ; lh2 init

# per-source live check
lh2 smoke goodfirms --city Pune

# grow + build the universe
lh2 crawl --source goodfirms                 # all cities
lh2 build

# enrich + score + export (Signalhire-only, fully-filled, append-ready)
lh2 enrich --max-enrich 400
lh2 score
lh2 export --append-to "Indian IT Services - IT Services Firms (2).csv" \
           --require-full --exclude-file data/delivered_domains.txt \
           --start-index 230 --limit 400
```

Key config toggles (`config.yaml`): `crawl.sources.*`, `crawl.max_pages_per_city`,
`crawl.honor_robots`, `enrich.company_site.enabled`, `enrich.registry.enabled`,
`enrich.linkedin_optional.enabled`, `gates.*`.

---

## 7. SCALING ROADMAP — capture more from every source

Goal: go from ~1,700 gate-pass firms to **tens of thousands**, with high fill
rates. Ordered by leverage.

### 7A. Broaden the crawl (breadth)
1. **Verify the 5 built-but-unverified crawlers** (Clutch, TechBehemoths, The
   Manifest, DesignRush, NASSCOM). Each is ~1 hour: run `lh2 smoke <source>`, fix
   the URL + selectors at the top of the module against live DOM. Each adds
   thousands of firms and cross-fills founded/size.
2. **Raise `max_pages_per_city`** and add **more cities / tier-2 towns** (Coimbatore,
   Vizag, Chandigarh, Bhubaneswar, Nagpur, Rajkot, Mysuru…). GoodFirms alone had
   124 pages across 20 cities → 4,965 rows.
3. **Add category axes**, not just cities: crawl by technology/service
   (`/php/`, `/reactjs/`, `/mobile-app-development/`, `/ai/`) — GoodFirms and Clutch
   both slice this way. Surfaces firms that don't rank on the generic city page.
4. **New directory sources:** Sortlist, ITFirms, TopDevelopers.co, SelectedFirms,
   MobileAppDaily, AppFutura, Techreviewer, GoodFirms *reviews* pages, YourStory
   company pages. Each is another `BaseCrawler` subclass (URL builder + isolated
   selectors + smoke test).

### 7B. Registries & funding databases (depth + authority)
5. **MCA / ZaubaCorp / Tofler / InstaFinancials** — authoritative directors →
   moves founder confidence to **green** and fills firms Signalhire misses. This is
   the single biggest data-quality upgrade. (Cloudflare-class → route via
   Playwright `BaseCrawler`; adapter stub exists in `registry_founders.py`.)
6. **Tracxn / Crunchbase / PitchBook / CB Insights** — founders, funding, headcount,
   status (active/deadpooled). Great for both discovery *and* enrichment. Tracxn in
   particular has deep India-startup coverage (used successfully for the AI Labs list).
7. **Startup ecosystems:** YourStory, Inc42, VCCEdge, StartupIndia registry.

### 7C. Alternative discovery angles (find firms directories miss)
8. **GitHub** — Indian software-services orgs with public repos (search by
   location + language + org type). Direct signal of an acquirable codebase.
9. **Job boards** (LinkedIn Jobs, Naukri, AngelList/Wellfound) — companies hiring
   developers in India = active services shops; reverse-lookup the employer.
10. **Web search sweep** — for a known niche, Google/Bing programmatic search
    ("top custom software companies in <city>") to catch long-tail firms. (Worked
    well for the AI Labs founder research via parallel agents.)
11. **Clearbit/Apollo/company-graph APIs** — firmographic discovery by
    industry+geo+size filters, bypassing per-directory crawling.

### 7D. Enrichment providers (raise fill rate + confidence)
12. **Proxycurl / Coresignal** (adapters built, OFF) — company-domain → real
    LinkedIn people. Different mechanism from Signalhire; use as a second LinkedIn
    source and to feed the namesake guard for **green** confidence.
13. **Apollo.io / Lusha / RocketReach** — additional phone/email coverage to lift
    the ~56% phone fill.
14. **Multi-source founder consensus:** registry ∩ company-site ∩ Signalhire ∩
    Proxycurl → the more independent sources agree, the higher the confidence.

### 7E. Throughput & infra (make it fast + unattended)
15. **Concurrency:** the enrich loop is currently sequential. Parallelize Signalhire
    (respect its ~3 concurrent-search limit) and Playwright (pool of contexts) —
    10–20× speedup. Watch each provider's rate limits.
16. **Quota management:** the Signalhire **daily search quota** is the true
    bottleneck. Either (a) get it raised via Signalhire support, or (b) run a
    **daily cron** (`lh2 run --since`) that enriches one quota's worth per day and
    accumulates — the pipeline is fully resumable/idempotent for exactly this.
17. **Proxies + polite crawling** for scale without blocks (rotating residential
    proxies, per-host concurrency=1, randomized delays — already config-driven).
18. **Scheduling:** GitHub Actions / cron entry exists (`.github/workflows/monthly-run.yml`,
    disabled). Enable for continuous monthly sourcing.
19. **Dashboards/metrics:** log per-source yield, fill rates, cost, quota burn.

### 7F. Geographic / vertical expansion
20. **Beyond India:** the gate is config-driven (`gates.hq_country`) — extend to
    other delivery geographies if the acquisition thesis broadens.
21. **Vertical lists:** re-run the whole machine against a themed seed list (like the
    AI Labs deadpooled list) — the pipeline handles "given a company list, fill
    founders+contacts" as a first-class flow.

---

## 8. Suggested next actions (in order)

1. **Resume the 400** when the Signalhire quota resets (pool is staged; commands in §6).
2. **Wire ZaubaCorp registry** → green-confidence founders + higher fill.
3. **Verify Clutch + TechBehemoths crawlers** → 2–3× the universe.
4. **Turn on Proxycurl** (behind the existing flag) for a second LinkedIn source.
5. **Parallelize enrichment** + set a **daily cron** to work within quota unattended.
6. **Add Tracxn/Crunchbase** as both a discovery and enrichment source.

---

## 9. Accuracy guarantees to preserve while scaling

- Never fabricate names/LinkedIn/phones. Unknown → blank / `(verify)`.
- Every value keeps its **provenance + confidence**.
- **Registry beats aggregators** on conflicts.
- **Net-new** always: exclude the master list (by domain + core-name) and
  previously delivered firms (`data/delivered_domains.txt`).
- Cache every external call → re-runs never re-bill; a crash resumes, not restarts.
