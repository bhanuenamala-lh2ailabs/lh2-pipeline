# LH2 → HubSpot Sales Workflow — Manual UAT Playbook

You are the **lead owner**. This walks every case end-to-end so you can prove the
whole machine works before KT to the sales team. ~30–40 min.

## 0. Orientation — what's automated vs manual

| Part of the journey | How it's driven |
|---|---|
| Lead → HubSpot (Company + Contact + Deal at *New Lead*) | **Automated** — `lh2 hubspot-sync` (nightly / on demand) |
| Cold-call outcomes 1–5 (stage move + properties + tasks) | **Automated** — `lh2 hubspot-call-outcome` |
| Call feedback → pipeline learning loop | **Automated** — `lh2 hubspot-pull` |
| Claim/assign, send emails, book meeting, GMEET1, script, results, Won, "meeting rejected"/"wrong fit" | **Manual in HubSpot UI** (this is by design — the sequence lives in HubSpot) |

**Golden rule:** the CLI automates the *cold-call branch*. Everything after the
meeting is a manual stage move in HubSpot. That's the intended split.

### Terminal prep (run once)
```bash
cd /Users/bhanusaienamala/dev/LH2ai/ITserviceCompLeadQ
source .venv/bin/activate
lh2 config-check | grep hubspot_api_key      # should show pat-…4b (not unset)
```

### How to get a Deal ID
- **HubSpot UI:** open a deal → the number in the URL (`…/record/0-3/<DEAL_ID>`).
- **Terminal:** `lh2 hubspot-call-outcome` (no args) lists open deals with IDs.

### Create disposable TEST deals (so you never touch a real lead)
All test deals are tagged `lead_source = UAT` so cleanup (Section 10) is one command.
Run this each time you need a fresh deal; it prints the ID:
```bash
python - <<'PY'
from lh2_pipeline.config import load_config
from lh2_pipeline.export.hubspot_client import HubspotClient
from lh2_pipeline.export.hubspot_workflow import get_stage_map
hc = HubspotClient(token=load_config().secrets.hubspot_api_key)
pid, stages = get_stage_map(hc)
_, d = hc._request("POST","/crm/v3/objects/deals",{"properties":{
  "dealname":"UAT TEST - delete me","pipeline":pid,"dealstage":stages["New Lead"],
  "lead_source":"UAT","email_version_sent":"None","call_attempt_count":0,"script_status":"Not Started"}})
print("TEST DEAL ID:", d["id"])
PY
```
> Tip: to inspect any deal's key props from the terminal, run:
> ```bash
> python - <<'PY'
> from lh2_pipeline.config import load_config
> from lh2_pipeline.export.hubspot_client import HubspotClient
> from lh2_pipeline.export.hubspot_workflow import get_stage_map
> hc=HubspotClient(token=load_config().secrets.hubspot_api_key); pid,st=get_stage_map(hc); byid={v:k for k,v in st.items()}
> DID="PASTE_ID"
> _,d=hc._request("GET",f"/crm/v3/objects/deals/{DID}?properties=dealstage,call_outcome,email_version_sent,calendly_link_sent,callback_datetime,needs_number_lookup,call_attempt_count,call_notes")
> p=d["properties"]; print("stage:",byid.get(p['dealstage']));
> print({k:v for k,v in p.items() if v and k!='dealstage'})
> _,ta=hc._request("GET",f"/crm/v4/objects/deals/{DID}/associations/tasks")
> for t in ta.get("results",[]):
>     _,tk=hc._request("GET",f"/crm/v3/objects/tasks/{t['toObjectId']}?properties=hs_task_subject,hs_task_priority,hs_timestamp")
>     print("  TASK:",tk["properties"]["hs_task_subject"],tk["properties"]["hs_task_priority"])
> PY
> ```

---

## 1. Lead creation (the nightly sync)

**Do:** `lh2 hubspot-sync --max 2` (safe — idempotent).
**Expect:** prints `✓ pushed 2 companies, 2 contacts …, N new deals …`.
In HubSpot → **Deals → Codebase Acquisition** pipeline → real deals sit in **New Lead**,
each named `"<Company> - Codebase Acquisition"`, associated to 1 Company + 1 Contact,
with `Lead Source = LH2 Pipeline`, `Email Version Sent = None`, `Call Attempt Count = 0`,
`Script Status = Not Started`.
**Re-run it** → prints `0 new deals` (nothing duplicates).

## 2. Claim & assign a lead (manual)

**Do (HubSpot UI):** open a New Lead deal → set **Deal owner** = you → drag/change stage to **Assigned**.
**Expect:** deal shows your name as owner, sits in *Assigned*.
*(There's no CLI for this — owners self-assign in the UI.)*

---

## 3. Cold-call outcomes (the core — `lh2 hubspot-call-outcome`)

Use a **fresh TEST deal** (Section 0) for each terminal case. Format:
`lh2 hubspot-call-outcome --deal-id <ID> --outcome <1-5> [--callback-time "..."] [--notes "..."]`

### Case 3.1 — Outcome 1: Picked up, right person, interested ✅
```bash
lh2 hubspot-call-outcome --deal-id <ID> --outcome 1 --notes "keen, wants the eval walkthrough"
```
**Expect** (deal): stage → **M1V1 Sent** · Call Outcome = `Connected - Interested` ·
Email Version Sent = `M1V1` · Calendly Link Sent = `Yes` · Call Attempt Count = `1` ·
Call Notes has a timestamped line with your note.
**Task created:** `Follow up - no meeting booked`, priority **MEDIUM**, due **next business day**, associated to the deal.
**CLI printed:** "→ Send the M1V1 email (HubSpot template) with your Calendly link".

### Case 3.2 — Outcome 2: Picked up, hard rejection ❌
```bash
lh2 hubspot-call-outcome --deal-id <ID> --outcome 2 --notes "not interested, do not contact"
```
**Expect:** stage → **Dead - Rejected** (closed-lost) · Call Outcome = `Connected - Rejected` ·
reason saved in Call Notes · **no task**.

### Case 3.3 — Outcome 3: Busy, gave a callback time ⏰
```bash
lh2 hubspot-call-outcome --deal-id <ID> --outcome 3 --callback-time "2026-07-17 14:30" --notes "asked for 2:30pm tomorrow"
```
**Expect:** stage → **Call Attempted** · Callback Date/Time set to that moment ·
**Task** `Callback - <company>`, priority **HIGH**, due at the **exact callback time**.
> Note: `--callback-time` is your **local time**; HubSpot stores UTC, so 14:30 IST shows as 09:00 UTC — that's correct.

### Case 3.4 — Outcome 3: Busy, no specific time
```bash
lh2 hubspot-call-outcome --deal-id <ID> --outcome 3 --notes "busy, call back sometime"
```
**Expect:** stage → **Call Attempted** · no Callback Date/Time ·
**Task** `Callback - was busy`, priority **MEDIUM**, due next business day.

### Case 3.5 — Outcome 4: Wrong number 📵
```bash
lh2 hubspot-call-outcome --deal-id <ID> --outcome 4 --notes "this number is a reception desk"
```
**Expect:** stage → **Call Attempted** · **Needs Number Lookup = Yes** ·
Call Notes appended "Wrong number - needs Apollo/alternate lookup" ·
**Task** `Apollo lookup - wrong number`, priority **HIGH**, due today.
*(Your manual follow-up: update the contact's phone, then call again.)*

### Case 3.6 — Outcome 5: No pickup + escalation chain 🔁 (use ONE test deal, call 3×)
```bash
# Call A (1st no-pickup)
lh2 hubspot-call-outcome --deal-id <ID> --outcome 5 --notes "rang out"
```
→ stage **M1V2 Sent** · Email Version Sent = `M1V2` · Attempt Count `1` · Task `Call again - no pickup` (MEDIUM, +1 biz day).
```bash
# Call B (2nd no-pickup, same deal)
lh2 hubspot-call-outcome --deal-id <ID> --outcome 5 --notes "no pickup again"
```
→ stage **M1V1 Sent** (escalation) · Email Version Sent = `M1V1` · Attempt Count `2` · Task `Final follow-up call` (**HIGH**, +1 biz day).
```bash
# Call C (3rd no-pickup, same deal)
lh2 hubspot-call-outcome --deal-id <ID> --outcome 5 --notes "still nothing"
```
→ stage **Dead - No Response** · Attempt Count `3` · **no task**.
**This is the key branch** — confirm all three transitions on the same deal.

### Case 3.7 — Guard rails
```bash
lh2 hubspot-call-outcome --deal-id <ID> --outcome 9      # → error: outcome must be 1-5
lh2 hubspot-call-outcome --deal-id BADID --outcome 1     # → clean "deal not found" error, no crash
lh2 hubspot-call-outcome                                 # → lists open deals to pick from
```

---

## 4. Post-M1V1: email + meeting booking (manual in HubSpot UI)

Continue from a **Case 3.1** deal (in *M1V1 Sent*).
1. **Send M1V1 email:** open the associated Contact → Email → **Templates → M1V1** → replace `[CALENDLY_LINK]` with your Calendly → Send.
2. **Meeting booked within ~1 day:** drag the deal to **GMEET1 Scheduled**.
   - *If not booked and you're chasing:* use **Awaiting Meeting**, keep the follow-up task.
   - *If they refuse the meeting:* drag to **Dead - Meeting Rejected**.
**Expect:** deal sits in the stage you chose; the earlier "Follow up - no meeting booked" task can be marked complete.

## 5. GMEET1 (the eval call) — 2 outcomes (manual)

From a deal in **GMEET1 Scheduled**, after the call drag to **GMEET1 Completed**, then set **GMEET1 Outcome** and move:
- **O1 — client runs the script on the call:** GMEET1 Outcome = `Script Run On Call` · Script Status = `Running` · drag to **Script Running** · create a task `Collect script results` (due same day).
- **O2 — client will run later:** GMEET1 Outcome = `Client Will Run Later` · Script Status = `Sent to Client` · drag to **Awaiting Results** · create a task `Follow up on script results` (due +2 days).

## 6. Results stage (manual + Company property)

When results come in:
1. On the **Company** record: fill **Evaluation Results** (paste the output) and **Results Received Date**.
2. On the **Deal**: Script Status = `Results Received` → drag to **Results Received**, then **Results Under Review**.
**Expect:** the eval text lives on the Company (survives even if the deal moves); deal in *Results Under Review* (the handoff point).

## 7. Terminal outcomes (summary of all Dead/Won paths)

| Stage | How you reach it |
|---|---|
| **Won** | manual drag when a deal closes |
| **Dead - Rejected** | Outcome 2 (auto) |
| **Dead - No Response** | Outcome 5 × 3 (auto) |
| **Dead - Meeting Rejected** | manual (Section 4) |
| **Dead - Wrong Fit** | manual drag anytime the fit fails |

---

## 8. Feedback loop (pipeline learning — `lh2 hubspot-pull`)

This is separate from the deal workflow: it reads **Contact-level** call fields
back into the pipeline so you can refine targeting. (Day-to-day sales uses the
deal workflow above; this is a pipeline-owner function.)

1. In HubSpot, open any **Contact** (a founder) → set **Call Outcome** = `Interested`,
   **Call Notes** = "test — wants callback", **Next Step** = "send deck".
   *(These are the Contact's call fields — distinct from the Deal's Call Outcome.)*
2. Terminal:
```bash
lh2 hubspot-pull
sqlite3 data/pipeline.sqlite "SELECT domain, email, call_outcome, next_step FROM crm_feedback;"
```
**Expect:** `hubspot-pull` prints `✓ pulled feedback for 1 firms …`; the SQL row shows
the feedback **keyed to the company domain**. Reset the test contact's fields afterward.

---

## 9. Safety / idempotency (must pass before KT)

1. **Re-sync doesn't duplicate or reset worked deals:**
   Pick a deal you moved to *M1V1 Sent* in Case 3.1. Run `lh2 hubspot-sync`.
   **Expect:** `0 new deals`; open that deal → it's **still in M1V1 Sent** (NOT dragged back to New Lead).
   *This is the critical guarantee — a nightly sync never disturbs sales' work.*
2. **Setup is idempotent:** `lh2 hubspot-setup` → everything "already exists", no errors.
3. **No duplicate companies/deals:** in HubSpot, sort Deals by name — no repeats.

---

## 10. Cleanup (remove all UAT test data)

```bash
python - <<'PY'
from lh2_pipeline.config import load_config
from lh2_pipeline.export.hubspot_client import HubspotClient
hc = HubspotClient(token=load_config().secrets.hubspot_api_key)
deals = hc.search_all("deals",[{"propertyName":"lead_source","operator":"EQ","value":"UAT"}],["dealname"])
for d in deals:
    _, ta = hc._request("GET", f"/crm/v4/objects/deals/{d['id']}/associations/tasks")
    for t in ta.get("results", []):
        hc._request("DELETE", f"/crm/v3/objects/tasks/{t['toObjectId']}")
    hc._request("DELETE", f"/crm/v3/objects/deals/{d['id']}")
    print("deleted test deal", d["id"])
print("done — real leads untouched")
PY
```
Also reset any Contact whose Call Outcome/Notes you edited in Section 8.

---

## Appendix A — the 18 pipeline stages (in order)
New Lead → Assigned → Call Attempted → Call Connected → M1V1 Sent → M1V2 Sent →
Awaiting Meeting → GMEET1 Scheduled → GMEET1 Completed → Script Running →
Awaiting Results → Results Received → Results Under Review → **Won** ·
**Dead - Rejected · Dead - No Response · Dead - Meeting Rejected · Dead - Wrong Fit**

## Appendix B — task templates the CLI creates
| Outcome | Task | Priority | Due |
|---|---|---|---|
| 1 | Follow up - no meeting booked | MEDIUM | +1 business day |
| 3 (time) | Callback - {company} | HIGH | at the callback time |
| 3 (no time) | Callback - was busy | MEDIUM | +1 business day |
| 4 | Apollo lookup - wrong number | HIGH | today |
| 5 (1st) | Call again - no pickup | MEDIUM | +1 business day |
| 5 (2nd) | Final follow-up call | HIGH | +1 business day |

## Appendix C — where each field lives
- **Deal** props (sales workflow): Call Outcome, Callback Date/Time, Needs Number Lookup,
  Email Version Sent, Calendly Link Sent, GMEET1 Date/Outcome, Script Status,
  Lead Source, Call Notes, Call Attempt Count.
- **Company** props: Founded Year, Size Bucket, Segment, Pipeline Source, **Evaluation Results**, Results Received Date.
- **Contact** props: LinkedIn URL, Contact Role, SPOC Type, and the *feedback* fields
  Call Outcome / Call Notes / Call Date / Next Step (read by `hubspot-pull`).
- To see all deal props in HubSpot: open the deal → **View all properties**.
