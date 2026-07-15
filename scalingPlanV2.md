
# Task: Set Up Complete HubSpot Sales Workflow via API

## Context

We have a lead-sourcing pipeline that produces qualified Indian IT-services company leads and syncs them into HubSpot as Companies + Contacts. We now need the FULL sales workflow configured in HubSpot — pipeline stages, custom properties, email templates, task automation, and workflow logic — all set up via the HubSpot API using our Service Key.

**Authentication:** Bearer token from env var `HUBSPOT_API_KEY` (HubSpot Service Key). All API calls use `Authorization: Bearer {token}` header against `https://api.hubapi.com`.

**Use httpx for all API calls.** No HubSpot SDK.

## The Complete Lead Journey

```
Pipeline syncs lead to HubSpot (automated, nightly)
    → Lead Owner claims the lead (manual, morning)
    → Cold Call (5 possible outcomes below)
    → Email sequence (M1V1 or M1V2)
    → Meeting booking via Calendly (GMEET1)
    → Tech evaluation call (script run)
    → Results received and logged
    → Under Review (handoff to ops/sales)
```

### Cold Call Outcomes (5 branches)

```
OUTCOME 1: Picked up, correct person, had the conversation
    → Move deal to "M1V1 Sent"
    → Send M1V1 email (template with Calendly link)
    → Create task: "Follow up if no meeting booked" due in 1 day

OUTCOME 2: Picked up, correct person, hard rejection
    → Move deal to "Dead - Rejected"
    → Log call note with reason
    → Close deal as Lost

OUTCOME 3: Picked up, says busy
    → If specific callback time given:
        → Log the callback time in deal property
        → Create task: "Callback" due at that exact datetime
    → If no specific time:
        → Create task: "Callback - was busy" due next business day
    → Deal stays in "Call Attempted" stage

OUTCOME 4: Picked up, wrong number
    → Set deal property "needs_number_lookup" = true
    → Log note: "Wrong number - needs Apollo/alternate lookup"
    → Create task: "Look up correct number on Apollo" due today
    → Once updated, restart call process

OUTCOME 5: Not picked up
    → Send M1V2 email (different template, no prior call context)
    → Create task: "Call again - no pickup" due in 1 day
    → If no email reply within 1 day AND second call also no pickup:
        → Send M1V1 email (escalation)
        → Create task: "Final follow-up call" due in 1 day
    → If still no response → Dead - No Response

### Post M1V1 Flow
    → Email has Calendly link for GMEET1
    → If meeting booked within 1 day → move to "GMEET1 Scheduled"
    → If NOT booked within 1 day:
        → Lead owner calls to push for booking
        → If booked → "GMEET1 Scheduled"
        → If rejected → "Dead - Meeting Rejected"

### GMEET1 (Google Meet call)
    → Tech lead joins, walks through codebase evaluation process
    → OUTCOME O1: Client runs the eval script on call itself
        → Move to "Script Running"
        → Create task: "Collect script results" due same day
    → OUTCOME O2: Client says "I'll run later and send results"
        → Move to "Awaiting Results"
        → Create task: "Follow up on script results" due in 2 days

### Results Stage
    → Results received → log to Company record in HubSpot
    → Move deal to "Results Under Review"
    → Lead owner reviews (manual, next stages TBD)
```

## What to Build

### 1. `lh2 hubspot-setup` CLI command

Creates all HubSpot configuration via API. Must be **idempotent** — check if each resource exists before creating. If it exists, skip.

#### A. Deal Pipeline

**Endpoint:** `POST /crm/v3/pipelines/deals`
**Check first:** `GET /crm/v3/pipelines/deals` — skip if "Codebase Acquisition" already exists.

Pipeline name: `Codebase Acquisition`

Stages (in this exact order, with display order and probability):

| Stage                   | Display Order | Win Probability | Category |
| ----------------------- | ------------- | --------------- | -------- |
| New Lead                | 0             | 10%             | OPEN     |
| Assigned                | 1             | 10%             | OPEN     |
| Call Attempted          | 2             | 15%             | OPEN     |
| Call Connected          | 3             | 20%             | OPEN     |
| M1V1 Sent               | 4             | 25%             | OPEN     |
| M1V2 Sent               | 5             | 20%             | OPEN     |
| Awaiting Meeting        | 6             | 30%             | OPEN     |
| GMEET1 Scheduled        | 7             | 40%             | OPEN     |
| GMEET1 Completed        | 8             | 50%             | OPEN     |
| Script Running          | 9             | 55%             | OPEN     |
| Awaiting Results        | 10            | 55%             | OPEN     |
| Results Received        | 11            | 60%             | OPEN     |
| Results Under Review    | 12            | 65%             | OPEN     |
| Won                     | 13            | 100%            | WON      |
| Dead - Rejected         | 14            | 0%              | LOST     |
| Dead - No Response      | 15            | 0%              | LOST     |
| Dead - Meeting Rejected | 16            | 0%              | LOST     |
| Dead - Wrong Fit        | 17            | 0%              | LOST     |

#### B. Company Custom Properties

**Endpoint:** `POST /crm/v3/properties/companies`
**Check first:** `GET /crm/v3/properties/companies/{propertyName}` — 200 = skip, 404 = create.

All in group `company_information`:

| Internal name                | Label                 | Type            | Field type   | Options (if enum)                    |
| ---------------------------- | --------------------- | --------------- | ------------ | ------------------------------------ |
| `founded_year`             | Founded Year          | `number`      | `number`   | —                                   |
| `size_bucket`              | Size Bucket           | `enumeration` | `select`   | `1-100`, `100-500`, `500-1000` |
| `headcount_source`         | Headcount Source      | `string`      | `text`     | —                                   |
| `segment`                  | Segment               | `string`      | `text`     | —                                   |
| `pipeline_source`          | Pipeline Source       | `string`      | `text`     | —                                   |
| `pipeline_notes`           | Pipeline Notes        | `string`      | `textarea` | —                                   |
| `pipeline_synced_at`       | Pipeline Synced At    | `date`        | `date`     | —                                   |
| `eval_results`             | Evaluation Results    | `string`      | `textarea` | —                                   |
| `eval_results_received_at` | Results Received Date | `date`        | `date`     | —                                   |

#### C. Contact Custom Properties

**Endpoint:** `POST /crm/v3/properties/contacts`

| Internal name    | Label        | Type            | Field type | Options (if enum)          |
| ---------------- | ------------ | --------------- | ---------- | -------------------------- |
| `linkedin_url` | LinkedIn URL | `string`      | `text`   | —                         |
| `contact_role` | Contact Role | `string`      | `text`   | —                         |
| `spoc_type`    | SPOC Type    | `enumeration` | `select` | `Primary`, `Secondary` |

#### D. Deal Custom Properties

**Endpoint:** `POST /crm/v3/properties/deals`

| Internal name           | Label               | Type            | Field type          | Options (if enum)                                                                                           |
| ----------------------- | ------------------- | --------------- | ------------------- | ----------------------------------------------------------------------------------------------------------- |
| `call_outcome`        | Call Outcome        | `enumeration` | `select`          | `Connected - Interested`, `Connected - Rejected`, `Connected - Busy`, `Wrong Number`, `No Pickup` |
| `callback_datetime`   | Callback Date/Time  | `datetime`    | `date`            | —                                                                                                          |
| `needs_number_lookup` | Needs Number Lookup | `enumeration` | `booleancheckbox` | —                                                                                                          |
| `email_version_sent`  | Email Version Sent  | `enumeration` | `select`          | `M1V1`, `M1V2`, `None`                                                                                |
| `calendly_link_sent`  | Calendly Link Sent  | `enumeration` | `booleancheckbox` | —                                                                                                          |
| `gmeet1_date`         | GMEET1 Date         | `datetime`    | `date`            | —                                                                                                          |
| `gmeet1_outcome`      | GMEET1 Outcome      | `enumeration` | `select`          | `Script Run On Call`, `Client Will Run Later`, `Rejected`, `No Show`                                |
| `script_status`       | Script Status       | `enumeration` | `select`          | `Not Started`, `Sent to Client`, `Running`, `Results Received`                                      |
| `lead_source`         | Lead Source         | `string`      | `text`            | —                                                                                                          |
| `call_notes`          | Call Notes          | `string`      | `textarea`        | —                                                                                                          |
| `call_attempt_count`  | Call Attempt Count  | `number`      | `number`          | —                                                                                                          |

#### E. Email Templates

These will be sent manually by the lead owner through HubSpot's email interface. Create as **saved email templates** so any team member can use them.

**Note:** HubSpot's template creation via API requires the `content` scope. Create these via:
`POST /marketing/v3/emails/templates` OR if that endpoint isn't available on Starter, document the templates as text so the lead owner can manually create them in HubSpot's UI (Settings → Email → Templates).

**M1V1 — Post-Call Introduction Email:**

```
Subject: Following Up - LH2 Data Labs x {{company.name}}

Hi {{contact.firstname}},

Great speaking with you earlier. As discussed, LH2 Data Labs acquires legacy codebases from established Indian IT-services firms like {{company.name}}.

I'd love to walk you through how the evaluation process works — it's quick and straightforward.

Pick a time that works for you: [CALENDLY_LINK]

Looking forward to connecting.

Best,
{{owner.first_name}}
LH2 Data Labs
```

**M1V2 — Cold Email (No Prior Call):**

```
Subject: Quick question about {{company.name}}'s codebase

Hi {{contact.firstname}},

I'm reaching out from LH2 Data Labs. We work with Indian IT-services firms to acquire legacy codebases — turning unused projects into real value.

Would love to have a quick 15-minute call to see if there's a fit.

Here's my calendar: [CALENDLY_LINK]

Best,
{{owner.first_name}}
LH2 Data Labs
```

**If the templates API is not available on Starter tier:** print these templates to console during `hubspot-setup` with instructions for the user to create them manually in HubSpot UI. Do NOT silently skip.

### 2. Update `lh2 hubspot-sync` to create Deals

When syncing a new company+contact to HubSpot, also create a Deal:

- Deal name: `"{company_name} - Codebase Acquisition"`
- Pipeline: `Codebase Acquisition`
- Stage: `New Lead`
- Property `lead_source`: `LH2 Pipeline`
- Property `email_version_sent`: `None`
- Property `call_attempt_count`: `0`
- Property `script_status`: `Not Started`
- Associate the deal with both the Company AND the primary Contact (SPOC 1)

**Dedup:** before creating a deal, search for existing deals associated with this company. If one already exists in the `Codebase Acquisition` pipeline, skip.

### 3. Task creation helper

Build a utility function that creates HubSpot tasks associated with a deal:

**Endpoint:** `POST /crm/v3/objects/tasks`

```python
def create_task(
    title: str,
    due_date: datetime,
    deal_id: str,
    contact_id: str | None = None,
    notes: str = "",
    priority: str = "MEDIUM",  # HIGH, MEDIUM, LOW
):
    # Create task
    # Associate with deal via associations API
    # Optionally associate with contact
```

This won't be called during nightly sync — it's a utility for the lead owners to use programmatically or for future workflow automation. But wire it into the module so it's available.

Pre-built task templates (as convenience functions):

| Function                                         | Title                           | Due              | Priority |
| ------------------------------------------------ | ------------------------------- | ---------------- | -------- |
| `create_callback_task(deal_id, callback_time)` | "Callback - {company}"          | callback_time    | HIGH     |
| `create_followup_no_booking_task(deal_id)`     | "Follow up - no meeting booked" | +1 business day  | MEDIUM   |
| `create_number_lookup_task(deal_id)`           | "Apollo lookup - wrong number"  | today            | HIGH     |
| `create_call_again_task(deal_id)`              | "Call again - no pickup"        | +1 business day  | MEDIUM   |
| `create_results_followup_task(deal_id)`        | "Follow up on script results"   | +2 business days | MEDIUM   |

### 4. Stage transition helper

Build a utility to move a deal through stages and log the transition:

```python
def move_deal_to_stage(deal_id: str, stage_name: str, properties: dict = None):
    """
    Move a deal to a new pipeline stage.
    Optionally update deal properties at the same time.
    Logs the transition.
    """
    # PATCH /crm/v3/objects/deals/{dealId}
    # Update dealstage + any extra properties
```

### 5. Full workflow helper: `process_call_outcome`

A single function that handles all 5 call outcomes:

```python
def process_call_outcome(
    deal_id: str,
    contact_id: str,
    outcome: int,  # 1-5
    callback_time: datetime | None = None,  # for outcome 3
    call_notes: str = "",
):
    """
    Process a cold call outcome and trigger the right actions.
  
    Outcome 1: Connected + interested → move to M1V1 Sent stage, 
               create follow-up task (1 day)
    Outcome 2: Connected + rejected → move to Dead - Rejected, 
               close deal
    Outcome 3: Connected + busy → log callback time, create callback task
    Outcome 4: Wrong number → flag for Apollo lookup, create task
    Outcome 5: No pickup → move to M1V2 Sent stage, create call-again task (1 day)
    """
```

### 6. CLI commands

Add to `cli.py`:

```
lh2 hubspot-setup              # Create all properties, pipeline, templates (idempotent)
lh2 hubspot-sync [--max N]     # Sync leads → Companies + Contacts + Deals
lh2 hubspot-call-outcome       # Interactive: pick deal, log call outcome, trigger actions
    --deal-id ID
    --outcome [1-5]
    --callback-time "2026-07-16 14:30"  (optional, for outcome 3)
    --notes "spoke briefly, interested but busy"
```

The `hubspot-call-outcome` command is a convenience tool for lead owners to quickly log call outcomes from terminal. The primary workflow will be through HubSpot's UI, but having CLI access is useful for batch operations.

### 7. Update nightly workflow

In `.github/workflows/nightly-enrich.yml`, add `HUBSPOT_API_KEY` to the env vars for the sync step:

```yaml
- name: Sync to HubSpot
  env:
    HUBSPOT_API_KEY: ${{ secrets.HUBSPOT_API_KEY }}
  run: lh2 hubspot-sync
```

## Architecture Notes

### File structure

```
src/lh2_pipeline/export/
    hubspot_sync.py      # Company + Contact + Deal upsert (nightly sync)
    hubspot_setup.py     # One-time setup: properties, pipeline, templates
    hubspot_workflow.py  # Call outcome processing, task creation, stage transitions
```

### Idempotency rules

- Properties: GET before POST, skip if exists
- Pipeline: list all, skip if name matches
- Companies: batch upsert by domain
- Contacts: batch upsert by email (SPOC 1), search-before-create (SPOC 2)
- Deals: search by associated company + pipeline name, skip if exists
- Tasks: always create (tasks are not idempotent by nature — that's fine, they're action items)

### Error handling

- If any API call fails, log the error with full context (deal name, company, endpoint, status code, response body)
- Never crash the full sync because one company failed — continue with the rest
- Rate limit: HubSpot allows 100 requests per 10 seconds. Add a simple rate limiter (sleep if approaching limit). Check `X-HubSpot-RateLimit-Remaining` header.

### Important

- Inspect `store.py` for the actual SQLite column names before writing queries
- Reference `sheets_sync.py` for patterns (config loading, DB queries, CLI integration)
- Email templates: if the API doesn't support template creation on Starter tier, print them to console with manual setup instructions. Don't silently fail.
- All HubSpot property internal names must be lowercase with underscores (HubSpot convention)
- The `dealstage` property value is the stage's internal ID, NOT the label. After creating the pipeline, retrieve the stage IDs and use those.

## Testing plan

1. `lh2 hubspot-setup` → verify in HubSpot UI: properties exist, pipeline exists with all stages
2. `lh2 hubspot-setup` again → verify idempotent (no errors, no duplicates)
3. `lh2 hubspot-sync --max 3` → verify 3 companies + contacts + deals appear in HubSpot
4. `lh2 hubspot-sync --max 3` again → verify no duplicates
5. `lh2 hubspot-call-outcome --deal-id X --outcome 1` → verify deal moves to M1V1 Sent, task created
6. `lh2 hubspot-call-outcome --deal-id X --outcome 3 --callback-time "2026-07-16 14:30"` → verify callback task appears with correct datetime
