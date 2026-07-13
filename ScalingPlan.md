
# Scaling Plan: A Daily Lead-Qualification Engine for India's IT-Services Universe

## TL;DR

- **Go hybrid, not "one paid tool."** No single platform one-stop-solves both discovery AND all-four-field (name + LinkedIn + phone + email) enrichment for India's ~10,000 small IT-services firms. The winning architecture keeps discovery mostly free (Indian registries + directory crawlers + Google Maps API) and builds a **multi-provider enrichment waterfall that puts India-native MCA/DIN-sourced tools FIRST** — because Indian founder mobile numbers, the binding constraint, are structurally under-covered by US-centric tools (Apollo, ZoomInfo, Lusha).
- **The phone field is your bottleneck, not money or discovery.** Email + LinkedIn are cheap to hit at 70-90%; verified Indian mobiles are the hard 40-60%. Because you require all four, your realistic all-four-field yield is ~45-60% per firm enriched, so you must enrich ~1.7-2.2 firms for every delivered lead.
- **Recommended spend: a ~$150-500/month mid-tier waterfall stack.** This delivers ~55-65% all-four yield at roughly $0.30-1.00 per fully-qualified lead — far better economics than a $15,000+/year Cognism/ZoomInfo "enterprise" contract that still underperforms on Indian SMB mobiles.

---

## Key Findings

### 1. The company universe is discoverable for free; ~10,000 is a defensible target

India's formal IT industry is large but the "independent IT-services firm, ~10-249 employees" slice is smaller than the raw company count. NASSCOM represents 3,000+ member companies accounting for ~90% of industry revenue. The ~10,000 figure is a reasonable estimate of the addressable independent services-firm population, and it is fully discoverable by combining three complementary layers:

- **Directory sites** (GoodFirms verified-live, plus Clutch/TechBehemoths/The Manifest/DesignRush) — these overlap heavily but together give near-complete coverage of firms that market for inbound leads. TechBehemoths lists ~56,000 companies globally and is fully sitemap-crawlable; Clutch has 280,000+ global listings; GoodFirms lists 110,000+ tech companies.
- **Indian company registries** (MCA master data via data.gov.in, surfaced through ZaubaCorp / Tofler / InstaFinancials) — this is the authoritative backbone and the key to Tier-2/3 cities (Pune, Ahmedabad, Coimbatore, Jaipur, Indore) that are invisible to LinkedIn-first tools. MCA covers 2 million+ registered companies.
- **Google Maps / Places API** — the long-tail gap-filler. Many small IT firms (especially in Tier-2/3 cities) have a Google Business Profile but never bothered listing on GoodFirms or Clutch. Google Maps covers every category of business in every city in India, and no other database matches this breadth at this cost. It catches an estimated 500–1,500 firms that directories miss entirely.

The directories capture firms that *want* to be found (good for warm ICP). The registry captures *everyone* (good for completeness). Google Maps catches the **long-tail firms in smaller cities** that do neither. You need all three.

### 2. Proxycurl is dead — do not build on LinkedIn scraping

LinkedIn (with parent Microsoft) filed a federal suit in January 2025, alleging Proxycurl "created hundreds of thousands of fake accounts to scrape millions of profiles," including non-public data. Proxycurl (run by Nubela, CEO Steven Goh) posted its shutdown notice July 2025; the case settled mid-2025 with a court-entered permanent injunction requiring Proxycurl to permanently delete all LinkedIn data obtained through unauthorized means. The founder disclosed it was a ~$10M-revenue business, and about half came from scraping LinkedIn — exactly why the legal risk was existential. This is the single most important architectural warning: **any provider whose business is a central scraped LinkedIn index is one injunction from disappearing and taking your data with it.** LinkedIn also removed the company Pages of Apollo and Seamless.AI in 2025. Favor providers that source LinkedIn URLs as a byproduct of licensed/consent data rather than raw scraping, and abstract your enrichment behind an interface so any single provider is swappable.

### 3. The MCA/DIN registry is your India superpower — and it legally contains phone + email

This is the finding that should reshape your enrichment strategy. Every Indian company director has a Director Identification Number (DIN), and the DIR-3 KYC filing contains the director's **personal mobile number and personal email** (both OTP-verified). Company/director *email* is effectively public (MCA master data + downloadable forms); the personal *mobile* is not shown in free master data but is present inside downloadable statutory forms (DIR-2/DIR-3/DIR-12). India-native tools (EasyLeadz/"Mr. E", Surereach, CookLeads) exploit this via Chrome-extension overlays on ZaubaCorp/Tofler/InstaFinancials, claiming ~100% accuracy (these are **unaudited marketing claims** — treat skeptically; "no mobile, no charge" pricing is itself an admission that mobile fill is materially below 100%). Note two caveats: MCA notified a change via the Companies (Appointment and Qualification of Directors) Amendment Rules, 2025, effective 31 March 2026 — shifting DIR-3 KYC Web to "once every third consecutive financial year, on or before 30 June" and merging the e-form and web forms into one. So registry contact data may now be up to ~3 years stale. And directors are not always the marketing/decision-maker persona you want (a registry director may be a co-founder's spouse or a nominee).

### 4. US-centric enrichment tools are weak exactly where you need them (Indian mobiles)

- **Apollo** (~$49-119/user/mo): deepest *accessible* Indian database for metro IT/SaaS emails + LinkedIn URLs, but real-world data accuracy is ~65-80% and mobile numbers cost 8-10 credits each with accuracy that lags significantly behind in APAC. Excellent cheap email + LinkedIn layer; unreliable as a phone source.
- **Cognism** ($15,000-25,000+/yr): best-in-class phone verification (Diamond Data, ~87% connect) but India is gated to premium tiers and APAC depth is thin; its 98% accuracy applies only to Diamond-verified numbers.
- **Lusha / Kaspr**: both explicitly weaker for India/APAC; one independent deployment reported Lusha coverage as low as ~10% of contacts.
- **People Data Labs / Coresignal**: API-first bulk data ($0.20-0.28/enrichment; $1,000+/mo floor for Coresignal), good for engineering pipelines but monthly-refresh staleness and heavy post-processing.
- **SignalHire (current)**: single credit = full reveal (email+phone+LinkedIn), but mobile hit rate ~35-40% and the daily *search* quota (shared with the web app) is your throughput ceiling, not credits.

### 5. Google Maps / Places API — the overlooked discovery layer

**Why it earns a slot:** Many 10-50 person IT shops in Coimbatore, Jaipur, Vizag, Indore, or Mysuru have a Google Business Profile (because Google practically forces it via Maps verification) but never paid for a Clutch or GoodFirms listing. These firms are invisible to directory crawlers and under-represented on LinkedIn. Google Maps is the only source that catches them at near-zero cost.

**What it gives you per listing:** business name, address, phone number (typically office/reception, NOT founder mobile), website URL, rating, reviews, business category, opening hours. Crucially, the website URL feeds directly into your existing canonical-domain dedup pipeline, and the address validates HQ city for gating.

**What it does NOT give you:** founder name, personal mobile, email, LinkedIn URL. It is purely a **discovery source**, not an enrichment source. The four required fields still come from the enrichment waterfall.

**The 60-result cap and grid-tiling workaround:** Google's Text Search returns a maximum of 60 results across 3 pages, regardless of how many businesses actually match. "IT companies in Bangalore" has thousands of results but you only see 60. The standard workaround is to subdivide each city into geographic tiles (using `locationRestriction` with rectangular viewports), run a separate Text Search per tile, and deduplicate by `place_id`. For 20+ Indian cities, this means ~500-2,000 API calls total.

**The noise problem:** "IT services" on Google Maps is a messy category. You'll get legitimate software firms mixed with computer repair shops, CCTV installers, laptop service centers, coaching institutes, and TCS/Infosys branch offices. You need to search multiple query variations ("software development company," "IT company," "web development company," "mobile app development company") and then run your existing gate filters hard (employee count, founded year, independence check, domain dedup). Expect ~40-60% of raw results to survive gating — worse than GoodFirms (~70%+) but the incremental volume of net-new firms makes up for it.

**Cost math:** Text Search at the Pro SKU (which returns display name, formatted address, location, types) runs at $32.00 per 1,000 calls. Google provides 5,000 free calls per month per SKU. Your entire 10,000-firm discovery sweep via Google Maps costs roughly **$16-64 total** — essentially negligible. Even with Place Details calls to grab phone/website for each result, the full sweep stays under $100.

**Implementation:** Build as another `BaseCrawler` subclass wrapping the official Text Search API (via httpx, no Playwright needed — it's a JSON API). Grid-tile each city, search with `includedType` filters, dedup by `place_id`, extract company name + website + office phone + address, feed into the existing `build` phase where gate filters handle noise.

| Attribute                          | Google Maps/Places                    | GoodFirms/Clutch         | MCA Registry                     |
| ---------------------------------- | ------------------------------------- | ------------------------ | -------------------------------- |
| **Discovery role**           | Long-tail + Tier-2/3 gap-fill         | Warm-ICP firms           | Authoritative backbone           |
| **Phone**                    | Office/reception (not founder mobile) | None                     | Director mobile (via DIN tools)  |
| **Website**                  | Yes (feeds canonical domain dedup)    | Yes                      | Registered address only          |
| **Founder name**             | No                                    | No                       | Yes (directors)                  |
| **Noise level**              | High (needs heavy gating)             | Low (pre-filtered)       | Medium (NIC code filtering)      |
| **Cost**                     | ~$20-100 for full sweep               | Free (scrape)            | Free (bulk CSV) / paid (reports) |
| **Overlap with directories** | ~30-40%                               | Baseline                 | ~50-60%                          |
| **Unique value**             | Catches 500-1,500 firms others miss   | Pre-qualified warm leads | Legal authority + phone/email    |

### 6. Waterfall enrichment is the only way to hit high all-four fill rates

Single-source enrichment caps at ~40-60% coverage per field; waterfall enrichment routinely pushes match rates to 80-95%. Cleanlist's Q1 2026 standardized 500-record test reports 98% email deliverability via 15+ providers vs single-source 65-87% (Apollo 70-80%, Lusha 82%, ZoomInfo 85%, Cognism 87%). **FullEnrich** (~$29-55/mo entry, 15-25+ providers, pay-per-found: work email 1 credit, personal email 3, mobile 10) and **Clay** ($149-495/mo, 75+ providers, steep learning curve) are the leading orchestration layers. Because you can build your own waterfall in Python (you already have httpx + a cache), you can replicate this logic and only pay per successful find.

### 7. Email verification is mandatory and cheap

Because "email" is a required field and you must never fabricate, run every found email through a verifier: **ZeroBounce** (~$0.01/email, 99.6% claimed) or **NeverBounce** (~$0.008/email). The known blind spot is catch-all domains (common on Indian company domains) — treat catch-all as "risky/unconfirmed," not "delivered."

### 8. A daily engine on free infrastructure is feasible

GitHub Actions runs scheduled cron jobs free (unlimited minutes for public repos; 2,000 min/mo private), with caveats: UTC-only, 10-30 min scheduling jitter, 6-hour max job, and auto-disable after 60 days of repo inactivity. This is sufficient for a nightly enrichment batch. It is NOT sufficient for time-critical or very high concurrency; for heavier loads a $5-20/mo VPS with real cron is more reliable.

---

## Details

### Discovery source comparison

| Source                                                                                        | India IT-services coverage                                      | Free/Paid                                 | API or Scrape                                    | Role in plan                              |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------ | ----------------------------------------- |
| **MCA master data (via data.gov.in)**                                                   | Authoritative, all 2M+ cos incl. Tier-2/3                       | Free (bulk CSV)                           | Bulk download / CSV;**no official API**    | Backbone universe + director names        |
| **ZaubaCorp / Tofler / InstaFinancials**                                                | MCA-derived; directors, DINs, some email                        | Free tier / paid reports                  | Scrape (or paid reports)                         | Registry enrichment surface               |
| **GoodFirms**                                                                           | High (verified live, all cities)                                | Free to crawl                             | Scrape                                           | Primary warm-ICP source (already working) |
| **Clutch**                                                                              | High (280k+ global)                                             | Free to crawl                             | Scrape (Cloudflare — needs Playwright)          | Secondary directory                       |
| **TechBehemoths**                                                                       | ~50k global, sitemap-crawlable                                  | Free                                      | Scrape via sitemap                               | Broad fill                                |
| **Google Maps / Places API**                                                            | **Very high** (every city, every firm with a GMB listing) | Free tier (5k calls/mo) then $32/1k calls | **Official JSON API** (no scraping needed) | Long-tail + Tier-2/3 gap-filler           |
| **The Manifest / DesignRush / Sortlist**                                                | Medium, overlaps Clutch/GoodFirms                               | Free                                      | Scrape                                           | Overlap/dedup fill                        |
| **TopDevelopers / SelectedFirms / ITFirms / MobileAppDaily / AppFutura / Techreviewer** | Medium, long-tail                                               | Free                                      | Scrape                                           | Long-tail coverage                        |
| **Tracxn / Crunchbase / Inc42 / StartupIndia**                                          | Funded/startup slice (biased to funded)                         | Freemium/Paid                             | Limited API/scrape                               | Funding signal + newer firms              |
| **Apollo / PDL / Coresignal (company search)**                                          | Filter by industry+geo+size                                     | Paid                                      | API                                              | Firmographic discovery + gap-fill         |
| **GitHub orgs / Naukri / Wellfound / NASSCOM directory**                                | Niche/alt discovery                                             | Free/Freemium                             | Scrape/API                                       | Edge discovery, dedup validation          |

**Verdict on discovery:** Discovery is a solved, near-free problem. Crawl the registry (data.gov.in bulk) + your existing GoodFirms crawler + verify and turn on the built-but-unverified Clutch/TechBehemoths/Manifest/DesignRush crawlers + run a one-time Google Maps API sweep across all target cities with grid-tiling. Dedup by canonical domain (you already do this). This alone gets you to ~10,000. Reserve paid firmographic APIs only for gap-filling firms that have no web/directory/Maps footprint.

### Enrichment provider comparison (weighted for India + four-field requirement)

| Provider                                                              | LinkedIn                            | Phone (India mobile)                        | Email + verification                                       | India quality                      | Pricing model                                   | Rate limits                                    |
| --------------------------------------------------------------------- | ----------------------------------- | ------------------------------------------- | ---------------------------------------------------------- | ---------------------------------- | ----------------------------------------------- | ---------------------------------------------- |
| **India-native MCA/DIN (EasyLeadz/Mr.E, Surereach, CookLeads)** | Via LinkedIn overlay                | **Best for India** (registry-sourced) | Registry + SMTP verify                                     | **Highest for SMB/Tier-2/3** | Pay-per-credit, some refund/"no-find-no-charge" | Extension/API, varies                          |
| **Apollo.io**                                                   | Strong                              | Weak (8-10 cr, low APAC accuracy)           | Strong email (~97% claimed / 65-80% real), built-in verify | Metro IT good; SMB thin            | $49-119/user/mo + credits                       | Credits expire monthly; API on Org tier        |
| **SignalHire (current)**                                        | Good                                | ~35-40% hit                                 | Email+phone bundled 1 credit                               | Moderate                           | Credit +**daily search quota**            | 402 on quota exhaust; 600 items/min Person API |
| **FullEnrich (waterfall)**                                      | Yes                                 | Aggregates many (10 cr)                     | ~80% find, triple-verify                                   | Better than single-source          | Pay-per-found; $29-55/mo entry                  | API + bulk                                     |
| **Clay (orchestration)**                                        | Yes                                 | Multi-provider                              | Multi-provider                                             | Depends on providers               | $149-495/mo + credits                           | Complex                                        |
| **Cognism**                                                     | Yes                                 | Diamond ~87% connect, India premium-only    | AI+SMTP verify                                             | APAC thin                          | $15k-25k+/yr                                    | Generous credits, no self-serve                |
| **Lusha**                                                       | Yes                                 | Weak APAC (~10% coverage in one test)       | ~95% email claimed                                         | Weak India                         | $49.90-399.90/mo                                | Credit caps                                    |
| **Kaspr**                                                       | Yes                                 | EU-first, weak non-EU                       | Unlimited B2B email                                        | Weak India                         | €45-79/mo                                      | Credit caps                                    |
| **People Data Labs**                                            | Yes                                 | Bulk, stale                                 | Bulk, monthly refresh                                      | Moderate, needs post-processing    | $0.20-0.28/enrich; $98/mo Pro                   | Per-credit                                     |
| **Coresignal**                                                  | Yes (900M records)                  | Company-heavy                               | Bulk                                                       | Moderate                           | $1,000+/mo floor                                | Per-record                                     |
| **RocketReach / Snov.io / Hunter**                              | Some                                | Weak India phone                            | Email-focused                                              | Weak-moderate                      | $39-149/mo                                      | Credit caps                                    |
| **Proxycurl**                                                   | **DEAD** (shut down Jul 2025) | —                                          | —                                                         | —                                 | —                                              | —                                             |

### The four-field problem, quantified

Component fill rates you can realistically expect for Indian IT-services founders:

- **Founder/decision-maker name:** ~75-85% (registry + directories + Apollo)
- **Verified LinkedIn URL:** ~65-80% (Apollo/waterfall; lower for Tier-2/3 non-LinkedIn-active founders)
- **Email (verified):** ~70-85% (waterfall + registry email + verification)
- **Verified Indian mobile:** ~40-60% (the binding constraint; registry/DIN tools materially lift this over US tools)

Because all four are required and the fields are partially independent, **all-four-field yield ≈ 45-60% per firm enriched** with a good waterfall, versus your current Signalhire-only ~50-56% all-three (adding a mandatory verified email will pull the current all-four below that unless you add an email waterfall + verifier). The single biggest lever is putting registry/DIN phone data first in the cascade.

---

## Free vs Paid: The Verdict

**Neither pure-free nor a single paid platform is correct. The answer is a hybrid waterfall.** A single paid platform fails because: (a) Apollo/ZoomInfo/Lusha are weak on the exact data (Indian SMB mobiles) that is your bottleneck; (b) Cognism/ZoomInfo cost $15k+/yr and *still* underperform on Tier-2/3 Indian firms; (c) none combines authoritative Indian registry discovery with four-field contact enrichment. The India-native registry tools solve the phone problem but have narrower LinkedIn/firmographic breadth. So you cascade: registry/DIN first (phone+email), Apollo/waterfall second (LinkedIn+email backfill), verifier last.

### Three concrete stack options

**Option A — Scrappy / mostly-free (~$50-150/mo). Expected all-four yield ~40-50%.**

- Discovery: registry bulk + your GoodFirms/Clutch/TechBehemoths crawlers + Google Maps API free tier (free)
- Enrichment: Apollo free/Basic (10k email credits + LinkedIn) + SignalHire pay-as-you-go + one India-native DIN tool on pay-per-credit for phone
- Verify: NeverBounce/ZeroBounce pay-as-you-go
- Pros: near-zero fixed cost; Cons: throughput throttled by SignalHire daily quota + Apollo mobile weakness; lowest phone yield

**Option B — Mid-tier waterfall (~$150-500/mo). Expected all-four yield ~55-65%. RECOMMENDED.**

- Discovery: same free crawlers + registry + Google Maps API (~$20-100 one-time sweep, then periodic re-runs)
- Enrichment cascade: **(1) India-native MCA/DIN tool (EasyLeadz/Surereach/CookLeads) for phone+email** → (2) FullEnrich waterfall for email+mobile backfill → (3) Apollo Basic for LinkedIn URL + email → (4) SignalHire as tertiary
- Verify: ZeroBounce/NeverBounce; treat catch-all as unconfirmed
- Pros: best yield-per-dollar; pay-per-found economics; India phone problem directly addressed; Cons: multiple provider accounts to manage (your cache + waterfall interface handles this)

**Option C — "Just solve it" paid (~$1,000-2,000/mo, or Cognism $15k+/yr). Expected all-four yield ~60-70% (capped by India mobile reality).**

- Apollo Organization (API) + Clay orchestration across 10+ providers + a dedicated phone specialist + India-native DIN tool + Cognism Diamond for senior contacts
- Pros: highest yield, most automation, best for a funded team; Cons: diminishing returns — you pay 3-5x Option B for ~5-10 more percentage points, because the ceiling is Indian mobile availability, not budget

---

## Architecture for a Daily Engine

Evolve `crawl → build → enrich → score → export` into a continuous loop:

1. **Scheduler:** GitHub Actions nightly cron (free) for the enrichment batch; add `workflow_dispatch` for manual runs; monitor for the 60-day auto-disable. For higher reliability/volume, a $5-20/mo VPS with real cron.
2. **Concurrency + quota management:** async enrichment loop (httpx async) with per-provider rate limiters and a **quota ledger** per provider (daily search caps, credit caps). When SignalHire returns 402 (daily search exhausted), the waterfall automatically **spills over to the next provider** — this is the core reason a waterfall beats single-provider: you sum multiple providers' daily caps.
3. **Waterfall cascade with early-exit:** stop calling providers for a field once it's filled+verified (saves credits). Cheapest/highest-India-yield provider first.
4. **Write-through cache (already built):** never re-bill; store provenance + confidence per value.
5. **Multi-source consensus for confidence:** when 2+ sources agree on a founder name/phone, boost confidence; registry data wins conflicts (per your core principle). Flag single-source values as lower-confidence.
6. **Dedup at scale:** canonical-domain dedup (existing) + rapidfuzz name matching across sources.
7. **Google Maps periodic re-scan:** re-run the Maps sweep quarterly to catch newly listed businesses; only process firms not already in the master universe.
8. **Daily output:** only rows where all four fields are present AND email passes verification AND phone is registry- or SMTP-plausibly-valid graduate to "delivered." Everything else stays in a re-try queue for the next provider/day.

---

## Throughput Math

- To **cover 10,000 firms once** at ~55% all-four yield → ~5,500 delivered leads from ~10,000 enrichment passes; the ~4,500 misses re-queue for additional waterfall providers on later days.
- To finish the initial 10,000 sweep in **~6 months** → enrich ~55 firms/day; in **~3 months** → ~110/day.
- To sustain a **steady 20 fully-qualified leads/day** afterward (re-enrichment + new firms) at 55% yield → enrich ~36 firms/day; at 45% yield → ~44/day.
- Cost per delivered lead (Option B): with pay-per-found economics ~$0.20-0.60 per attempt and ~55% four-field yield → roughly **$0.30-1.00 per fully-qualified lead.**

---

## Recommendations — Staged Rollout

**Stage 0 (Week 1) — Prove the phone lever.** Run a 100-firm bake-off from your staged 1,587-firm pool: enrich the same 100 firms through (a) current SignalHire, (b) one India-native MCA/DIN tool, (c) Apollo. Measure all-four-field yield and, critically, verified-mobile yield per source. This decides which provider leads your waterfall. **Benchmark to change the plan: if a registry/DIN tool delivers >60% verified Indian mobiles vs SignalHire's ~40%, make it the phone primary.**

**Stage 1 (Weeks 2-3) — Build the waterfall + verifier.** Wrap each provider behind a common `enrich(company, person) → fields+provenance+confidence` interface (swap-ability protects against another Proxycurl event). Add ZeroBounce/NeverBounce as the mandatory email gate. Implement the quota ledger + 402 spillover.

**Stage 2 (Weeks 3-4) — Turn on full discovery.** Three parallel tracks:

- Verify the built-but-unverified Clutch/TechBehemoths/Manifest/DesignRush crawlers (~1 hour each).
- Add the MCA/data.gov.in bulk ingest for registry backbone + Tier-2/3 coverage.
- Run the **Google Maps API sweep**: build the `GoogleMapsCrawler` subclass, grid-tile across all target cities (20+ metros + Tier-2 towns), search with multiple query variations ("software development company," "IT company," "web development," "mobile app development"), dedup by `place_id`, feed into the existing `build` phase. The free tier (5,000 calls/month) likely covers the entire initial sweep; overage is ~$32/1,000 additional calls.
- Dedup everything to the ~10,000 universe.

**Stage 3 (Week 4+) — Schedule the daily engine.** GitHub Actions nightly cron; enrich ~55-110 firms/day to sweep 10,000 in 3-6 months; keep a re-try queue for misses. Add failure alerting (Slack webhook) since GitHub doesn't notify on failed scheduled runs.

**Stage 4 (ongoing) — Re-enrichment cadence.** B2B contact data decays ~22.5%/yr (2.1%/month) — phone numbers decay faster (42.9% of business contacts change within one year). Re-verify delivered leads quarterly. Given the March/April 2026 shift of DIR-3 KYC to a 3-year cycle, treat registry phone/email as potentially stale and always re-verify email before it counts as delivered. Re-run the Google Maps sweep quarterly to catch newly registered businesses.

**Budget recommendation:** Start on **Option B (~$150-500/mo)**. Only escalate to Option C if you have a funded outbound team and Stage-0 data shows the extra providers materially lift verified-mobile yield. Do NOT sign a Cognism/ZoomInfo annual contract before the Stage-0 bake-off proves it beats the India-native tools on your exact ICP.

---

## Google Maps API — Implementation Guide

### Architecture fit

Google Maps slots into the discovery layer as a `GoogleMapsCrawler` subclass of `BaseCrawler`. It's a JSON API (httpx, no Playwright needed), which makes it the simplest crawler to implement.

### Query strategy

Run multiple query variations per city to maximize coverage and reduce noise:

```
"software development company in {city}"
"IT company in {city}"
"web development company in {city}"
"mobile app development company in {city}"
"custom software company in {city}"
```

Use `includedType` parameter to filter by relevant business types where possible, and `locationRestriction` (rectangular viewport) for grid-tiling.

### Grid-tiling logic

For each city:

1. Define a bounding box (lat/lng rectangle covering the metro area).
2. Subdivide into tiles small enough that each tile returns <60 results (typically 2-5 km per side for metros, larger for Tier-2 cities).
3. Run Text Search per tile with `locationRestriction`.
4. Dedup results by `place_id` across tiles.
5. For each unique result, extract: `displayName`, `formattedAddress`, `nationalPhoneNumber`, `websiteUri`, `rating`, `userRatingCount`, `types`.

### Cost control

- Request only Pro-tier fields (displayName, formattedAddress, location, types, websiteUri, nationalPhoneNumber) — $32/1,000 calls.
- Do NOT request rating/reviews (pushes to Enterprise tier at $35-40/1,000).
- Use the 5,000 free calls/month first; track usage via Google Cloud Console.
- Cache every response (write-through, keyed by `place_id`) — re-runs never re-bill.

### Data mapping to pipeline

| Google Maps field                | Pipeline field                                    | Notes                                                  |
| -------------------------------- | ------------------------------------------------- | ------------------------------------------------------ |
| `displayName`                  | `company_name`                                  | May include "Pvt Ltd" suffixes — normalize            |
| `websiteUri`                   | `website` → canonical domain (dedup key)       | Critical: this is the dedup bridge                     |
| `nationalPhoneNumber`          | `company_phone` (new field, NOT founder mobile) | Office/reception — useful for cold-call fallback      |
| `formattedAddress`             | `hq_city` (extract city from address)           | Feeds HQ city gate                                     |
| `types`                        | Gate filter input                                 | Filter out "electronics_store," "computer_repair" etc. |
| `rating` + `userRatingCount` | Quality signal                                    | 4+ stars + 50+ reviews = established, active company   |
| `place_id`                     | Dedup key (within Google Maps source)             | Prevents cross-tile duplicates                         |

### Noise filtering

After the Maps sweep, apply these additional gates before merging into the company universe:

- **Type filter:** reject results where `types` includes `electronics_store`, `hardware_store`, `computer_support`, `education`, `training`, `repair`, `telecom`.
- **Size proxy:** firms with 50+ Google reviews are likely too large (TCS, Infosys branch offices); firms with 0 reviews may be ghost listings. Sweet spot: 5-50 reviews.
- **Website required:** reject listings with no `websiteUri` — you need a domain for dedup and enrichment.
- **Domain dedup:** merge with existing universe by canonical domain; only process net-new firms.

---

## Caveats

- **Legal/ToS (DPDP Act 2023 + Rules 2025):** India's DPDP consent regime is being phased in to ~May 2027. Section 3(c)(ii) exempts "publicly available" personal data, and statutory ROC/MCA filings are treated as public — which is why registry-sourced director contacts are the most legally defensible path. However, the government has stated in Parliament that scraping publicly available data may *still* require consent, and the Act's B2B direct-marketing posture may require opt-in consent. Favor official registry/licensed-API data over LinkedIn/ToS-violating scraping for personal contact fields, honor opt-outs, store provenance, and apply purpose limitation + data minimization. This is not legal advice — get Indian counsel before scaling storage of personal mobiles.
- **LinkedIn scraping is high-risk:** Proxycurl's shutdown and the removal of Apollo/Seamless company Pages show LinkedIn's enforcement posture. Never build on a LinkedIn-session-cookie or fake-account tool.
- **Google Maps ToS:** Using the official Places API for business-data retrieval is compliant with Google's Terms of Service. The data is publicly listed by businesses themselves. Scraping Google Maps directly (bypassing the API) is NOT compliant — always use the official API.
- **Vendor accuracy claims are unaudited:** the ~100% claims of India-native DIN tools and the 95-98% claims of global tools are marketing. Trust only your own Stage-0 bake-off numbers.
- **Catch-all email domains** (common on Indian company domains) can't be definitively verified — count them as "risky," not "delivered," to honor the never-fabricate principle.
- **Directors ≠ ideal decision-makers:** registry directors may be nominees or non-marketing co-founders; cross-check against the firm's actual founder/CEO where possible.
- **The all-four requirement is your hardest constraint:** near-complete four-field coverage of all 10,000 is likely unattainable — realistic steady-state is ~50-65% of firms yielding a complete four-field lead. Plan for a permanent "3-of-4" queue you keep re-attempting rather than expecting 100%.
- **Google Maps 60-result cap:** grid-tiling is engineering work but a one-time build. Cache aggressively — the tiling logic only runs during discovery sweeps, not daily enrichment.
