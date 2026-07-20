# HubSpot Setup — Exact Replication Reference

The **complete, authoritative** schema of the LH2 HubSpot portal (246754894),
generated from `src/lh2_pipeline/export/hubspot_setup.py`. Replicate this exactly
for a new pipeline/vertical. See `HUBSPOT_PUSH_HANDOVER.md` for the push code +
gotchas (unique-key upsert, cross-vertical key scoping, tier caps).

Base `https://api.hubapi.com` · header `Authorization: Bearer <HUBSPOT_API_KEY>` · httpx, no SDK.

## Deal pipeline: `Codebase Acquisition`
`POST /crm/v3/pipelines/deals` (check `GET /crm/v3/pipelines/deals` first). `probability` is a STRING; `dealstage` writes the stage **ID**, not the label.

| # | Stage | Probability | isClosed |
|---|---|---|---|
| 0 | New Lead | 0.1 | false |
| 1 | Assigned | 0.1 | false |
| 2 | Call Attempted | 0.15 | false |
| 3 | Call Connected | 0.2 | false |
| 4 | M1V1 Sent | 0.25 | false |
| 5 | M1V2 Sent | 0.2 | false |
| 6 | Awaiting Meeting | 0.3 | false |
| 7 | GMEET1 Scheduled | 0.4 | false |
| 8 | GMEET1 Completed | 0.5 | false |
| 9 | Script Running | 0.55 | false |
| 10 | Awaiting Results | 0.55 | false |
| 11 | Results Received | 0.6 | false |
| 12 | Results Under Review | 0.65 | false |
| 13 | Won | 1.0 | true |
| 14 | Dead - Rejected | 0.0 | true |
| 15 | Dead - No Response | 0.0 | true |
| 16 | Dead - Meeting Rejected | 0.0 | true |
| 17 | Dead - Wrong Fit | 0.0 | true |

## Company properties
`POST /crm/v3/properties/companies` · group `companyinformation` · check `GET /crm/v3/properties/companies/{name}` first

| name | label | type/fieldType | options | flags |
|---|---|---|---|---|
| `lh2_domain` | LH2 Domain (unique key) | string/text | — | UNIQUE KEY |
| `founded_year` | Founded Year | number/number | — |  |
| `size_bucket` | Size Bucket | enumeration/select | 1-100, 100-500, 500-1000 |  |
| `headcount_source` | Headcount Source | string/text | — |  |
| `segment` | Segment | string/text | — |  |
| `pipeline_source` | Pipeline Source | string/text | — |  |
| `pipeline_notes` | Pipeline Notes | string/textarea | — |  |
| `pipeline_synced_at` | Pipeline Synced At | date/date | — |  |
| `eval_results` | Evaluation Results | string/textarea | — |  |
| `eval_results_received_at` | Results Received Date | date/date | — |  |

Standard company fields also written: `name`, `domain`, `city`, `country`.

## Contact properties
`POST /crm/v3/properties/contacts` · group `contactinformation`

| name | label | type/fieldType | options | flags |
|---|---|---|---|---|
| `linkedin_url` | LinkedIn URL | string/text | — |  |
| `contact_role` | Contact Role | string/text | — |  |
| `spoc_type` | SPOC Type | enumeration/select | Primary, Secondary |  |
| `call_outcome` | Call Outcome | enumeration/select | Not Called, Connected, No Answer, Left Voicemail, Interested, Not Interested, Callback Requested, Wrong Contact, Do Not Contact |  |
| `call_notes` | Call Notes | string/textarea | — |  |
| `call_date` | Call Date | date/date | — |  |
| `next_step` | Next Step | string/text | — |  |

Standard contact fields also written: `email` (unique key), `firstname`, `lastname`, `phone`.

## Deal properties
`POST /crm/v3/properties/deals` · group `dealinformation`

| name | label | type/fieldType | options | flags |
|---|---|---|---|---|
| `lh2_domain` | LH2 Domain (unique key) | string/text | — | UNIQUE KEY |
| `call_outcome` | Call Outcome | enumeration/select | Connected - Interested, Connected - Rejected, Connected - Busy, Wrong Number, No Pickup |  |
| `callback_datetime` | Callback Date/Time | datetime/date | — |  |
| `needs_number_lookup` | Needs Number Lookup | enumeration/booleancheckbox | true, false |  |
| `email_version_sent` | Email Version Sent | enumeration/select | M1V1, M1V2, None |  |
| `calendly_link_sent` | Calendly Link Sent | enumeration/booleancheckbox | true, false |  |
| `gmeet1_date` | GMEET1 Date | datetime/date | — |  |
| `gmeet1_link` | GMEET1 Link | string/text | — |  |
| `gmeet1_outcome` | GMEET1 Outcome | enumeration/select | Script Run On Call, Client Will Run Later, Rejected, No Show |  |
| `script_status` | Script Status | enumeration/select | Not Started, Sent to Client, Running, Results Received |  |
| `lead_source` | Lead Source | string/text | — |  |
| `call_notes` | Call Notes | string/textarea | — |  |
| `call_attempt_count` | Call Attempt Count | number/number | — |  |
| `poc` | PoC | enumeration/select | user picker (OWNER) | externalOptions |
| `deal_value_range` | Deal Value Range ($) | string/text | — |  |
| `script_link` | Script Link | string/text | — |  |
| `script_output_link` | Script Output Link | string/text | — |  |

Standard deal fields also written: `dealname`, `pipeline`, `dealstage`, `amount` (the native forecast number, UI-labelled "Deal Value").

## Sync keys, associations & rules
- **Companies** upsert by `lh2_domain` (unique) = canonical domain: `POST /crm/v3/objects/companies/batch/upsert {inputs:[{idProperty:'lh2_domain',id:'<domain>',properties:{...}}]}`
- **Contacts** upsert by `email` (HubSpot-native unique): `.../contacts/batch/upsert idProperty=email`
- **Deals**: SEARCH by `lh2_domain` then `batch/create` only if missing. NEVER update an existing deal.
- **SPOC 2** (no email): `POST /crm/v3/objects/contacts` once, cache the id (`hubspot:spoc2:<domain>`), skip if cached.
- **Associations** (v4 default): `POST /crm/v4/associations/{from}/{to}/batch/associate/default {inputs:[{from:{id},to:{id}}]}` — contacts→companies, deals→companies, deals→contacts (both SPOCs).
- Batch cap **100**; retry 429/5xx/ReadTimeout; only send non-empty values.
- Tag `pipeline_source`/`lead_source` per vertical (this one: `LH2 pipeline` / `LH2 Pipeline`).

## ⚠️ To replicate for a NEW vertical, change ONLY:
1. **Pipeline label** (new pipeline — but Starter caps at 2; one slot left).
2. **Deal unique key** — `lh2_domain` is already taken on the `deals` object portal-wide. Use a vertical-scoped value (`distress:acme.com`) or a new `hasUniqueValue` deal prop. **Keep `lh2_domain`=plain domain on COMPANIES** (shared company record is desirable).
3. **`pipeline_source` / `lead_source`** tag values.
Everything else (properties, stages, associations) is identical — the GET-checks make re-creating idempotent.
