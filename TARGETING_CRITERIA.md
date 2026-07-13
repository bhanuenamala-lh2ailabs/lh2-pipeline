# IT-Services Company Targeting & Filtering Criteria

What kind of company this pipeline is looking for, where it looks, and the exact
rules used to keep or drop each firm. This mirrors the logic implemented in
`config.yaml` (`gates:`) and `src/lh2_pipeline/transform/gates.py`.

---

## 1. The target profile (who we want)

We are sourcing **Indian IT-services companies** that are realistic targets for a
**codebase / team acquisition** — i.e. small-to-mid, founder-led, services-model
software firms, **not** giant outsourcers, pure-product/SaaS companies, or staffing shops.

A good target looks like:

| Attribute                | What we want                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------- |
| **Business model** | IT / software**services** (custom software, web/mobile dev, product engineering, consulting) |
| **Geography**      | **India-headquartered** or India-delivery                                                    |
| **Size**           | **~10–249 employees** (small enough to acquire, big enough to have a real team + codebase)  |
| **Maturity**       | Founded**on or before 2022** (established, has real IP/history)                              |
| **Ownership**      | Independent / founder-led (not a subsidiary of a large group)                                      |
| **Net-new**        | Not already on our existing lists                                                                  |

---

## 2. Where we look (sources)

Public IT-services directories that expose firmographics (founded year, team
size, location) inline, crawled per city:

| Source                             | Status                   | Notes                                                             |
| ---------------------------------- | ------------------------ | ----------------------------------------------------------------- |
| **GoodFirms**                | ✅ verified live         | Per-city software-development directory; highest structured yield |
| Clutch                             | built, not live-verified | `it-services/<city>` + developers                               |
| TechBehemoths                      | built, not live-verified | per-city company lists                                            |
| The Manifest / DesignRush          | built, off               | secondary cross-fill                                              |
| NASSCOM member directory           | built, off               | India-only by definition; India-HQ signal                         |
| **MCA / ZaubaCorp registry** | planned                  | authoritative founder/director data (not yet wired)               |

Cities crawled (drive from `config.yaml → crawl.cities`): Bengaluru, Pune,
Hyderabad, Ahmedabad, Indore, Jaipur, Noida, Gurugram, Delhi, Chennai,
Coimbatore, Kochi, Mumbai, Kolkata, Mohali, Surat, Vadodara, Nagpur, Bhopal,
Trivandrum.

---

## 3. The gate (keep / drop rules)

Every firm is evaluated against the gates below. A firm that fails **any** gate is
**kept in the database** with `gate_pass = false` and a `gate_reason` (for audit /
denominator), but is **excluded from the deliverable**.

> **Fail-closed principle:** if a required value (founded year or size) is
> **unknown**, the firm is **dropped**, not guessed. A smaller correct list beats a
> larger guessed one.

### 3.1 Include criteria (must pass ALL)

| # | Gate                     | Rule                                                                                                                                            | Config key                   |
| - | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| 1 | **HQ / delivery**  | Country =**India** (sources are India city pages → India-delivery assumed; foreign-incorporated firms are flagged in Notes, not dropped) | `gates.hq_country`         |
| 2 | **Founded year**   | `founded_year <= 2022` (unknown → **fail**)                                                                                            | `gates.founded_max_year`   |
| 3 | **Team size**      | size band ∈**{`10-49`, `50-249`}** (unknown → **fail**)                                                                       | `gates.size_bands_include` |
| 4 | **Services model** | Directory listing implies a services firm (pure-product/SaaS & pure staffing excluded where detectable)                                         | —                           |

### 3.2 Exclude criteria (any of these = drop)

| # | Gate                       | Rule                                                                                                                                                                                | Config key                                                                                         |
| - | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 5 | **Too small**        | size band =`<10`                                                                                                                                                                  | `gates.size_bands_exclude`                                                                       |
| 6 | **Too big**          | size band =`250+`                                                                                                                                                                 | `gates.size_bands_exclude`                                                                       |
| 7 | **Too new**          | `founded_year > 2022`                                                                                                                                                             | `gates.founded_max_year`                                                                         |
| 8 | **Large outsourcer** | name matches the outsourcer blocklist (TCS, Infosys, Wipro, HCL, Tech Mahindra, LTIMindtree, Mphasis, Persistent, Coforge, Cognizant, Capgemini, Accenture, Mindtree, Hexaware, …) | `gates.blocklist_outsourcers`                                                                    |
| 9 | **Already known**    | firm is on our existing lists — matched by**canonical domain** OR **distinctive core name**                                                                            | `gates.blocklist_known_domains`, `gates.blocklist_known_names`, `gates.blocklist_known_file` |

**Near-ceiling flag:** firms in `50-249` whose *precise* reported headcount is
200–249 are kept but flagged `near-250 headcount ceiling` in Notes (close to the
size limit — worth a look).

### 3.3 Current threshold values (from `config.yaml`)

```yaml
gates:
  hq_country: India
  founded_max_year: 2022
  size_bands_include: ["10-49", "50-249"]
  size_bands_exclude: ["<10", "250+"]
  blocklist_outsourcers: [TCS, Infosys, Wipro, HCL, Tech Mahindra, LTIMindtree, ...]
  blocklist_known_file: "Indian IT Services - IT Services Firms (2).csv"   # your existing list
```

---

## 4. "Already known" de-duplication (net-new guarantee)

To keep output **net-new**, each candidate is checked against firms we already have:

- **By domain** — exact match on the canonical registered domain (the dedupe key).
- **By name** — matched on the **distinctive core** of the company name: generic
  tokens (Technologies, Solutions, Software, Labs, Pvt, Ltd, India, …) are stripped
  first, so *"Velotio Technologies Pvt Ltd"* correctly matches our *"Velotio
  Technologies"*, while a genuinely different *"Brightline Technologies"* is **not**
  wrongly excluded.
- Firms already delivered in prior batches are tracked in
  `data/delivered_domains.txt` and excluded from new exports.

---

## 5. Data-accuracy rules (applied during enrichment)

These govern what we're allowed to write into a target row — never fabricate:

1. **Never guess.** A blank cell is correct; an invented value is a bug.
2. **Founder names** — only from an authoritative/verifiable source (company
   registry, company website, or a Signalhire profile **matched to the company** by
   its experience). Unknown → literal `(verify)`.
3. **Founder LinkedIn** — only a real profile confirmed to belong to that person at
   that company; never constructed from a name. Signalhire-sourced ones are flagged
   *"via Signalhire – verify"* in Notes.
4. **Phone numbers** — only from Signalhire (normalized to E.164 `+91…`); never generated.
5. **Registry beats aggregators** — if the company registry and a directory disagree
   on a founder name, the registry wins.
6. **Provenance on everything** — each enriched value records where it came from.

---

## 6. Confidence tiers (per founder row)

| Tier            | Meaning                                                                                                                                      |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **green** | Founder name agrees across ≥2 independent authoritative sources (e.g. registry ≈ company site), and any LinkedIn passed the namesake check |
| **amber** | Single source, mild disagreement, or a Signalhire-sourced / unverified LinkedIn                                                              |
| **red**   | Only a weak/aggregator source,`(verify)`, or an unresolved name conflict                                                                   |

---

## 7. One-line summary

> **Keep** an India-based IT **services** firm of **10–249** people, founded **≤ 2022**,
> that is **independent**, **not** a large outsourcer, and **not already on our lists** —
> then enrich it with a **verified founder + LinkedIn + phone**, never guessing.
