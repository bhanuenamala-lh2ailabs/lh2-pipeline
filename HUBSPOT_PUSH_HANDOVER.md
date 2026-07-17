# Handover: Pushing LH2 leads into HubSpot (for the Distress-list agent)

You're pushing ranked candidates into the **same HubSpot portal (246754894)** that the
IT-services pipeline already writes to. This doc is the whole contract: what works,
what bit us, and exactly what to change for a **new vertical + new deal pipeline**.

Reference implementation (copy the patterns): `src/lh2_pipeline/export/` in the
`ITserviceCompLeadQ` repo —
`hubspot_client.py` (HTTP + limits) · `hubspot_setup.py` (properties + pipeline) ·
`hubspot_sync.py` (the push) · `hubspot_workflow.py` (stages/tasks — optional for you).

---

## 0. TL;DR — what you need to build

1. **Setup (once, idempotent):** create your custom deal properties + a **new deal pipeline** for the distress vertical.
2. **Push (repeatable):** for each ranked candidate → **upsert Company** → **upsert Contact** → **create Deal** (only if missing) → **associate** deal↔company↔contact.
3. **Never** re-update an existing deal (sales owns its stage).
4. Read §4 (idempotency) and §7 (**cross-vertical key collision**) before writing code — those are the two things that will silently corrupt data.

---

## 1. Auth + client

- Base: `https://api.hubapi.com`
- Header: `Authorization: Bearer <HUBSPOT_API_KEY>` (private-app token, already in `.env`)
- Use plain `httpx`. No SDK.

**Rate limit:** 100 requests / 10 s. Pace proactively (sliding window at ~90% of the
limit) *and* reactively: on **429 or 5xx**, honor `Retry-After` and back off. Also
watch the `X-HubSpot-RateLimit-Remaining` header. Retry transient
`ReadTimeout`/`TransportError` — a single timeout killed a long run for us.

```python
def _request(method, path, json=None):
    for attempt in range(1, 5):
        pace()                                     # sliding-window limiter
        try:
            r = httpx.request(method, BASE+path, json=json, headers=H, timeout=40)
        except (httpx.TimeoutException, httpx.TransportError):
            time.sleep(min(10, 2**attempt)); continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", min(10, 2**attempt)))); continue
        return r.status_code, (r.json() if r.content else {})
```

---

## 2. The object model

| LH2 concept | HubSpot object | Natural key |
|---|---|---|
| Firm | **Company** | canonical domain |
| Founder / SPOC 1 | **Contact** | email |
| Second SPOC | **Contact** (no email) | — (see §6) |
| The opportunity | **Deal** in your pipeline | see §7 ⚠️ |

Standard company props: `name`, `domain`, `city`, `country`.
Standard contact props: `email`, `firstname`, `lastname`, `phone`.
Everything else = custom properties you create in setup.

---

## 3. Creating custom properties (idempotent)

- **Check:** `GET /crm/v3/properties/{objectType}/{name}` → **200 = exists, skip**; 404 = create.
- **Create:** `POST /crm/v3/properties/{objectType}`

```json
{"name":"size_bucket","label":"Size Bucket","type":"enumeration","fieldType":"select",
 "groupName":"companyinformation",
 "options":[{"label":"1-100","value":"1-100","displayOrder":0}]}
```
- `objectType` ∈ `companies` | `contacts` | `deals`
- groups: `companyinformation` / `contactinformation` / `dealinformation`
- types: number→`number`, text→`string`/`text`, long text→`string`/`textarea`,
  date→`date`/`date`, datetime→`datetime`/`date`, enum→`enumeration`/`select`,
  checkbox→`enumeration`/`booleancheckbox` (options must be `true`/`false`).

### ⚠️ Gotcha: property **labels** must be unique per object
Creating `linkedin_url` labelled *"LinkedIn URL"* **400s** with
`NON_UNIQUE_PROPERTY_LABEL` because HubSpot's standard `hs_linkedin_url` already owns
that label. The *name* is what you write to, so just retry with a suffixed label:

```python
if status == 400 and "NON_UNIQUE_PROPERTY_LABEL" in str(resp):
    body["label"] = body["label"] + " (LH2 Distress)"
    status, resp = _request("POST", f"/crm/v3/properties/{obj}", body)
```

### Properties that already exist in this portal (reuse, don't recreate)
`lh2_domain`, `founded_year`, `size_bucket`, `headcount_source`, `segment`,
`pipeline_source`, `pipeline_notes`, `pipeline_synced_at`, `eval_results`,
`eval_results_received_at` (companies); `linkedin_url`, `contact_role`, `spoc_type`,
`call_outcome`, `call_notes`, `call_date`, `next_step` (contacts). Your GET-check
handles this automatically — they'll just be skipped.

---

## 4. 🔑 Idempotency — the single most important lesson

**Company `domain` is NOT a unique-value property in HubSpot**, so you *cannot*
`batch/upsert` by it. Our first version did *search-by-domain → create-or-update*
and **created 14 duplicate companies**, because HubSpot's **search index is
eventually consistent** — a back-to-back run didn't find records created seconds
earlier and made them again.

**The fix — create your own unique-value key property and upsert by it:**

```json
{"name":"lh2_domain","label":"LH2 Domain (unique key)","type":"string",
 "fieldType":"text","groupName":"companyinformation","hasUniqueValue": true}
```

Then upsert atomically (no search, no index race):

```python
POST /crm/v3/objects/companies/batch/upsert
{"inputs":[{"idProperty":"lh2_domain","id":"acme.com","properties":{...}}]}
```

**Contacts:** `email` **is** a HubSpot unique key, so upsert-by-email works out of the box:
```python
POST /crm/v3/objects/contacts/batch/upsert
{"inputs":[{"idProperty":"email","id":"a@acme.com","properties":{...}}]}
```

Batch endpoints take **≤100 items** per call. Responses return `{"results":[{"id":..., "properties":{...}}]}` — map the echoed key back to the HubSpot id.

---

## 5. Creating your **new deal pipeline**

- **Check first:** `GET /crm/v3/pipelines/deals` → skip if your label already exists.
- **Create:** `POST /crm/v3/pipelines/deals`

```json
{"label":"Distress Acquisition","displayOrder":1,
 "stages":[
   {"label":"New Lead","displayOrder":0,"metadata":{"probability":"0.1","isClosed":"false"}},
   {"label":"Won","displayOrder":13,"metadata":{"probability":"1.0","isClosed":"true"}},
   {"label":"Dead - Rejected","displayOrder":14,"metadata":{"probability":"0.0","isClosed":"true"}}
 ]}
```
- `probability` is a **string** 0.0–1.0; `1.0` = closed-won, `0.0` = closed-lost; set `isClosed`.

### ⚠️ Tier cap on pipelines
The portal is **Sales Hub Starter = 2 deal pipelines**. **One is already used**
("Codebase Acquisition"). **Yours is the 2nd — it should fit, but it's the last one.**
If `POST` returns `400 ... "You have reached your limit of N deal pipelines"`, you're
capped (that's what happens on free/STANDARD, where we had to *repurpose* the default
pipeline via `PUT /crm/v3/pipelines/deals/{id}`). Handle that error gracefully rather
than crashing.

### ⚠️ `dealstage` takes the stage **ID**, not the label
After creating/fetching the pipeline, build a label→id map and use the id:
```python
p = get_pipeline("Distress Acquisition")
stage_ids = {s["label"]: s["id"] for s in p["stages"]}
props["pipeline"]  = p["id"]
props["dealstage"] = stage_ids["New Lead"]
```

---

## 6. The push flow (order matters)

1. **Upsert Companies** — `batch/upsert`, `idProperty="lh2_domain"`, id = canonical domain.
   *(Same key as IT-services → a firm in both lists correctly becomes **one** company record, enriched by both. This is desirable.)*
2. **Upsert Contacts (SPOC 1)** — `batch/upsert`, `idProperty="email"`.
3. **Associate contact → company** (see below).
4. **SPOC 2** (no email → can't upsert): `POST /crm/v3/objects/contacts` once, then
   **cache the returned id locally** (`key: hubspot:spoc2:<domain>` → id) and skip if
   cached. Don't rely on name-search — it's flaky. Associate it to the company **and**
   the deal (so it shows on the deal card).
5. **Deals — create ONLY if missing.** Search your unique deal key first; create the
   missing ones with `batch/create`. **Never PATCH an existing deal** — its stage is
   owned by sales, and a re-sync must not drag a worked deal back to "New Lead".
6. **Associate** deal→company and deal→contact(s).

**Associations (v4, default/unlabeled):**
```python
POST /crm/v4/associations/{fromType}/{toType}/batch/associate/default
{"inputs":[{"from":{"id":"<id>"},"to":{"id":"<id>"}}]}
# e.g. contacts→companies, deals→companies, deals→contacts
```

---

## 7. ⚠️⚠️ CROSS-VERTICAL COLLISION — read this or you'll be blocked

The IT-services deals **already use `lh2_domain` as a unique-value property on the
`deals` object**, with the value = the **plain domain** (`acme.com`). Unique means
**one deal per value, portal-wide**.

**So if a distressed firm is also in the IT-services list, your deal create will fail
the uniqueness constraint** — you'd never get a second deal for that company.

**Fix — scope your deal key to your vertical.** Pick one:

- **(a) Prefix the value (simplest, no new schema):** set `lh2_domain = "distress:acme.com"` on **deals only**. Distinct from `acme.com`, so both deals coexist, and the IT sync (which searches `lh2_domain IN [plain domains]`) will never see yours.
- **(b) Your own key property (cleanest):** create `lh2_distress_key` with `hasUniqueValue: true` on `deals`, value = the plain domain, and upsert/search by that. Leaves `lh2_domain` empty on your deals — zero interference either way.

**Either way: keep `lh2_domain` = plain domain on COMPANIES** (you *want* to share the
company record). Only the **deal** key must be vertical-scoped.

Also set a distinct **`pipeline_source`** (e.g. `"LH2 Distress"`) on your companies/deals
so both verticals stay filterable and reportable apart. Ours uses `"LH2 pipeline"` /
`lead_source = "LH2 Pipeline"` on deals.

---

## 8. Gotchas checklist (all learned the hard way)

- [ ] `domain` isn't unique → **use a `hasUniqueValue` key + batch/upsert** (never search-then-create; the index lags and you'll get duplicates).
- [ ] Property **labels** must be unique per object → retry with a suffixed label on `NON_UNIQUE_PROPERTY_LABEL`.
- [ ] `dealstage` = stage **ID**, not label.
- [ ] Pipelines are **tier-capped** (Starter = 2; one is taken).
- [ ] **Deal key must be vertical-scoped** (§7).
- [ ] Batch limit **100**; associations are a **separate v4 call**.
- [ ] **Never update existing deals** on re-sync.
- [ ] Retry **429/5xx/ReadTimeout**; one timeout can kill a whole run.
- [ ] Phone numbers: normalize to **E.164** before sending.
- [ ] Only send **non-empty** values — never fabricate a field.
- [ ] Log per-record failures and **continue** — one bad company must not abort the push.

---

## 9. Suggested build order

1. `setup` command: create your deal properties + the "Distress Acquisition" pipeline (GET-check everything; idempotent). Run it twice — second run must create nothing.
2. `push --limit 3`: end-to-end on 3 candidates. Verify in the UI: company has your custom fields, contact is associated, deal is in *New Lead*.
3. Run `push --limit 3` **again** → must create **0** new deals/companies (proves idempotency; this is where duplicates would show).
4. Full push. Then verify `distinct domains == total companies` (we do exactly this check — it's how we caught the 14 dupes).

## 10. Sheet write-back

Independent of HubSpot — keep your existing `gsheets.write_new_tab(..., replace=True)`
path. Just note the ordering: **enrich → write sheet → push to HubSpot**, and make the
HubSpot push read from your **DB**, not the sheet, so a sheet rewrite can't affect CRM state.
