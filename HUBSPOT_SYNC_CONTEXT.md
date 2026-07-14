# Context Brief: Sync a Google Sheet of Sales Leads → HubSpot CRM

> **How to use this doc:** paste it to Claude as the full context for a new task.
> You (the operator) want Claude to guide you through connecting a **Google Sheet
> (fed nightly by an automated pipeline)** into **HubSpot CRM**. This brief gives
> Claude everything about the source data so it can design the integration and
> walk you through setup. Claude has NO access to the pipeline code — everything
> it needs is here.

---

## 1. What the data is

An automated pipeline runs **every night** and produces **verified-ish B2B sales
leads**: small/mid **Indian IT-services companies** (acquisition/outreach targets)
plus their **founder contact details**. Each night it appends the new qualified
leads into a Google Sheet. We now want those leads to flow into **HubSpot CRM** so
the sales team works them there.

**Volume/cadence:** ~100 new qualified leads per nightly run (varies; tapers as the
company universe is worked through). Runs once/day.

**Each lead = one company + its founder contact(s).** So in CRM terms every row is
naturally a **Company** with 1–2 associated **Contacts** (the founders / points of
contact, "SPOC 1" and "SPOC 2").

---

## 2. The Google Sheet — structure (this is the source of truth)

One spreadsheet, **three tabs**. The operator has the spreadsheet key and a Google
service account with edit access (share the sheet with whatever connector you pick).

### Tab A — `Qualified Leads`  ← THE MAIN ONE to sync
**Append-only.** Rows are never deleted; new qualified firms are added each night.
Columns, in order:

| # | Column | Meaning / format | Notes for HubSpot |
|---|--------|------------------|-------------------|
| 1 | `#` | internal sequential id | ignore |
| 2 | `Company` | **Google-Sheets `=HYPERLINK("https://<domain>/","<Company Name>")`** | display text = company name (clickable). Use the **`Domain` column** (next) for dedup, not this formula |
| 3 | `Domain` | **plain canonical domain**, e.g. `acme.com` | **← company dedup key for HubSpot** (added for exactly this integration) |
| 4 | `Founder(s)` | `"Name1 (Role1); Name2 (Role2)"` (semicolon-separated) | Name1 = primary contact (SPOC 1), Name2 = SPOC 2 |
| 4 | `Founder LinkedIn (verified)` | URL | SPOC 1 LinkedIn |
| 5 | `Email` | email | **SPOC 1 email** (HubSpot's contact dedup key) |
| 6 | `Contact Number` | phone, E.164 (`+91…`) | SPOC 1 phone |
| 7 | `SPOC 2 Linkedin` | URL (may be blank) | SPOC 2 LinkedIn |
| 8 | `Contact Number 2` | phone (may be blank) | SPOC 2 phone |
| 9 | `Incorp. Year` | year, e.g. `2016` | Company "year founded" |
| 10 | `HQ / India delivery` | usually `India` (+ city elsewhere) | Company country/city |
| 11 | `Approx. Headcount` | **a band string**, e.g. `10-49`, `50-249`, `250 - 999` | Company employee count — it's a *range*, not an exact number |
| 12 | `Size Bucket` | `1-100` \| `100-500` \| `500-1000` | Company custom property (coarse size tier) |
| 13 | `Headcount source (approx.)` | provenance, e.g. `GoodFirms` | optional custom prop / note |
| 14 | `Segment` | services/description text | Company "industry" or custom |
| 15 | `Status` | Independent / Acquired / **usually blank** | optional |
| 16 | `Notes` | provenance caveats, e.g. `founder 'X' via Signalhire - verify` | put on a note or custom prop |
| 17 | `Synced At` | ISO timestamp of the run | maps to created/first-synced date |

### Tab B — `Under Review`
**Overwritten every run** (self-cleaning). Firms with **3 of the 4** key fields
(founder name, LinkedIn, phone, email) — exactly one missing. Has an extra
`Missing Field(s)` column and a plain `Domain` column (not a hyperlink). These are
lower-quality/partial leads; **decide whether to sync these at all** (e.g. as a
separate HubSpot list or lifecycle stage, or skip until they graduate to Qualified).

### Tab C — `Pipeline Stats`
One metrics row appended per run (Date, Firms Enriched, Qualified, Review, fill-%).
**Do not sync to CRM** — it's an ops dashboard, not lead data.

---

## 3. Data semantics & quality (important for CRM hygiene)

- **Never-fabricated.** A blank cell means "genuinely unknown," not "look it up."
  Never invent values on the CRM side.
- **Contacts are matched-by-company but NOT independently verified.** The founder
  name/LinkedIn/phone/email are sourced from a contact-data provider (SignalHire)
  and matched to the right company, but the sales team is expected to **verify on
  first contact**. → In HubSpot, set an appropriate **Lead Status / Lifecycle
  stage** (e.g. `Lead` / "New – unverified"), not "qualified/won".
- **Already net-new.** The pipeline excludes firms it has already delivered or
  already reached out to (it reads exclusion lists). But **HubSpot may still
  contain some of these** from other sources → you still need **HubSpot-side dedup**
  (by company **domain** and contact **email**).
- **SPOC 2 has no email** in the sheet (only name + LinkedIn + phone). HubSpot
  dedups contacts by email, so SPOC 2 is harder to create/dedup cleanly — **decide:
  create SPOC 2 as a contact (keyed on name+company) or skip it.**
- **Append-only Qualified → upsert, never delete.** A firm appearing again should
  UPDATE, not duplicate. Use domain (company) + email (contact) as the idempotency key.

---

## 4. The goal

Get **`Qualified Leads` rows → HubSpot**, as **Companies + associated Contacts**
(optionally Deals), running automatically after each nightly refresh, **deduped**,
with sensible property mapping and a "new lead" lifecycle stage — without creating
duplicates on re-runs.

---

## 5. Suggested HubSpot object model (Claude: confirm with the operator)

- **Company** (one per row): name, domain (from the hyperlink URL), country/city,
  year founded, employee range, size bucket, industry/segment, source, notes.
- **Contact** SPOC 1 (primary founder): first/last name (split from `Founder(s)`),
  email, phone, LinkedIn, associated to the Company; lifecycle = Lead.
- **Contact** SPOC 2 (optional): name, phone, LinkedIn (no email), associated to
  the Company.
- **Deal** (optional): one per company in an "Outbound / Sourcing" pipeline at a
  "New lead" stage, if the team wants to track outreach as deals.
- **Dedup keys:** Company = **domain**; Contact = **email** (SPOC 1) / name+company
  (SPOC 2).

---

## 6. Integration options (Claude: help the operator pick, based on their HubSpot tier)

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Zapier / Make** (recommended for no-code) | "New/updated Google Sheet row → HubSpot Create/Update Company + Contact + associate" | Fast to set up, handles append-only via upsert, no coding | Monthly cost at volume; must parse the hyperlink domain + split `Founder(s)`; 2 objects per row = multiple steps |
| **B. HubSpot Operations Hub – Data Sync / Workflows** | Native Google Sheets connector or a scheduled import + workflow | Native, no third party | Needs Operations Hub / Pro tier; company+contact association can be fiddly |
| **C. Direct HubSpot CRM API** (recommended if they want it robust/free) | Add a step to the existing nightly pipeline that batch-upserts to HubSpot's CRM API (`/crm/v3/objects/companies` + `/contacts` batch upsert with associations), keyed on domain/email | Most control, exact dedup, no per-row SaaS cost, reuses the pipeline's data directly (could even skip the sheet) | Requires a HubSpot private-app token + a bit of code |
| **D. Manual CSV import** | Export the tab → HubSpot Import UI, map columns | Zero setup | Manual, not automated, easy to dup |

**Rule of thumb:** if they're on HubSpot Free/Starter and want it now → **Zapier/Make**.
If they want it clean, free-at-volume, and are comfortable adding to the pipeline →
**direct API (Option C)** is the best long-term (it can push straight from the
pipeline's database, with the sheet remaining just a human view).

---

## 7. Known gotchas to handle (Claude: make sure the chosen method addresses these)

1. **Company domain:** the Qualified tab now has a **plain `Domain` column (col 3)**
   — use it directly as the company dedup key. (The `Company` column is still a
   `=HYPERLINK(...)` formula so the name stays clickable; you don't need to parse
   it.) The `Under Review` tab also has a plain `Domain` column.
2. **`Founder(s)` is a combined string** `"Name (Role); Name2 (Role2)"` — must be
   split into SPOC 1 / SPOC 2, and name split into first/last for HubSpot.
3. **`Approx. Headcount` is a range** (`50-249`), not a number — map to a HubSpot
   employee-range property or store as text; `Size Bucket` is the clean tier field.
4. **Phones are text with a leading `+`** (E.164) — keep them as text so `+` isn't
   dropped.
5. **Upsert, don't insert** — re-running must update existing Company/Contact
   (dedup on domain/email), never duplicate.
6. **SPOC 2 has no email** — decide create-vs-skip.
7. **Lifecycle stage** — land these as unverified "Lead"; sales verifies on contact.
8. **Only `Qualified Leads`** by default; treat `Under Review` separately or skip.

---

## 8. Questions for Claude to ask the operator before building

1. **HubSpot tier?** (Free / Starter / Professional / Operations Hub) — decides which
   sync methods are available.
2. **Preferred method?** No-code (Zapier/Make) vs native HubSpot vs direct API.
3. **Which objects?** Companies + Contacts only, or also Deals in a pipeline?
4. **Lifecycle/Lead status** for imported leads? Owner assignment / round-robin?
5. **SPOC 2** — create as a contact or ignore?
6. **Sync `Under Review` too**, or only `Qualified Leads`?
7. **Custom properties** — OK to create HubSpot custom props for `Size Bucket`,
   `Segment`, `Headcount source`, `Founded year`, `Source = LH2 pipeline`?
8. **Trigger** — real-time on new row, or a scheduled daily sync a bit after the
   nightly pipeline finishes?

---

## 9. One-line summary for Claude

> "I have a Google Sheet (`Qualified Leads` tab, append-only, ~100 new rows/night)
> where each row is an Indian IT-services **company + its founder contact(s)**
> (company name+domain-in-a-hyperlink, founder name(s), email, phone, LinkedIn,
> size, etc.). Help me push it into **HubSpot as Companies + associated Contacts**,
> deduped (company by domain, contact by email), as unverified new leads, running
> automatically after each nightly refresh — and walk me through the setup for my
> HubSpot tier."
