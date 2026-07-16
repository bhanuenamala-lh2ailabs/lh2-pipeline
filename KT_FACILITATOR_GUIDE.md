# KT Facilitator Guide — HubSpot Sales Workflow

For **you** (the lead owner / admin) to run the knowledge-transfer session with the
4-person sales team. Goal: at the end, every rep is **set up** and can **run a lead
end-to-end unaided**. Plan ~**90 minutes**.

Hand the team **[SALES_SOP_HUBSPOT.md](SALES_SOP_HUBSPOT.md)** (their rulebook) and
show **[SALES_WORKFLOW_FLOWCHART.md](SALES_WORKFLOW_FLOWCHART.md)** (the picture).

---

## A. Before the session (admin — do these yourself first)

- [ ] All 4 reps have a **Sales Hub Starter seat** assigned.
- [ ] Pipeline **Codebase Acquisition** exists with all 18 stages (`lh2 hubspot-setup` already did this).
- [ ] **M1V1 & M1V2 email templates created and SHARED with the team.** Compose an email → paste from `hubspot_email_templates.md` → **Save as template → shared**. Do this once so reps just pick them.
- [ ] Deal record sidebar customized once (Settings → Objects → Deals → Record customization): **Companies card** shows headcount/size/founded/segment; **Contacts card** shows LinkedIn/role/SPOC type. (One-time; applies to all.)
- [ ] The **8 UAT practice deals** exist at *New Lead* (each named `UAT-1 … UAT-8` with its scenario) — reps will practice on these.
- [ ] Share the two docs above with the team **before** the call so they can skim.

---

## B. Session agenda (90 min)

| Time | Segment |
|---|---|
| 0:00–0:10 | **Why / the mission** — we source acquisition leads; HubSpot is the single source of truth. Consistency = forecasting + no cold leads. |
| 0:10–0:25 | **The mental model** — walk the flowchart top to bottom (§C). |
| 0:25–0:45 | **Live demo** — you drive one UAT deal end-to-end on screen (§D). |
| 0:45–1:15 | **Hands-on** — each rep works a UAT scenario live (§E). |
| 1:15–1:25 | **The 10 golden rules** + common mistakes (§F). |
| 1:25–1:30 | **Setup checklist + Q&A** (§G). |

---

## C. The mental model (talking points, ~15 min)

Open **SALES_WORKFLOW_FLOWCHART.md** (renders on GitHub, or export a PNG from mermaid.live for slides). Walk it:

1. **A lead = a Deal + a Company + founder Contacts.** It arrives automatically in **New Lead**.
2. **You claim it** (Assigned), then **call**.
3. **The call has exactly 5 outcomes** — point at each branch on the diagram:
   ① interested → M1V1, ② rejected → dead, ③ busy → callback, ④ wrong number → fix & retry, ⑤ no pickup → **escalation** (M1V2 → M1V1 → dead).
4. **After the intro email:** meeting booking → **GMEET1** (tech eval) → results → **Under Review** → **Won**.
5. **The stage is the truth.** Moving cards is how everyone sees where a lead is. Every call → move the stage.
6. Emphasize the two hard gates: **paste the GMEET link** when scheduling, and **enter the deal `Amount`** after GMEET1.

## D. Live demo script (you drive, ~20 min) — use deal **UAT-1**

Do it slowly, narrating each click. This is the reps' template.
1. Open **UAT-1** → set **Deal owner = you** → move **New Lead → Assigned**.
2. "I call the founder, they're interested" → **Call** icon → outcome *Connected* + a note → Log.
3. Set deal **Call Outcome = Connected - Interested** → move to **Call Connected**.
4. **Email → Templates → M1V1** → show the Calendly link → Send (it lands in the shared inbox).
5. Move to **M1V1 Sent** → create task **"Follow up - no meeting booked" (+1d)** — show it appear in Tasks.
6. "They book" → **GMEET1 Scheduled** → paste a **GMEET1 Link**.
7. "We ran the eval" → **GMEET1 Completed** → **enter Amount = 25000** → GMEET1 Outcome *Script Run On Call* → **Script Running**.
8. On the **Company**: fill **Evaluation Results** → deal **Results Received → Results Under Review → Won**.
9. Finish by opening **Sales → Forecast / Deals** and showing how the **Amount + stage** rolls up into pipeline value. "This is why we're strict about Amount."

## E. Hands-on — each rep runs a scenario (~30 min)

Assign one UAT deal per rep (they can do more if time). Each follows the SOP unaided; you float and correct:
- **UAT-2** Rejected → Dead - Rejected
- **UAT-3** Busy → callback task
- **UAT-4** Wrong number → lookup task
- **UAT-5** No pickup → the full M1V2 → M1V1 → Dead-No Response escalation *(the trickiest — make sure someone does this one)*
- **UAT-6** Meeting rejected → Awaiting Meeting → Dead - Meeting Rejected
- **UAT-7** GMEET1 later → Awaiting Results
- **UAT-8** Wrong fit → Dead - Wrong Fit

Success = the deal ends in the right stage with the right task, and they logged the call + set Call Outcome.

## F. The 10 golden rules + common mistakes to pre-empt

Read the **10 golden rules** from the SOP aloud. Then call out the mistakes people actually make:
- ❌ Moving a card but **not logging the call** (or vice-versa) → do the full 4-step ritual.
- ❌ Leaving a deal with **no next task** → it goes cold. Every touch = a task.
- ❌ Advancing past GMEET1 **without an Amount** → forecast breaks.
- ❌ Forgetting the **GMEET link**.
- ❌ Freehand emails instead of the **templates**.
- ❌ **Deleting** dead deals instead of moving them to a Dead stage (we lose the record + reporting).
- ❌ Ignoring **overdue red tasks**.

---

## G. Per-rep sign-off checklist (confirm before they leave)

Tick this for **each** of the 4 reps — they're not "trained" until all are ✅:

- [ ] Seat accepted, profile + signature set
- [ ] **Inbox connected** (sent one test email from a deal, saw it log)
- [ ] **Calendar connected + meeting link created**
- [ ] **Task reminders on**
- [ ] Found the **M1V1/M1V2 templates**
- [ ] **Ran one UAT deal end-to-end** correctly (call logged, stage moved, task created)
- [ ] Ran the **⑤ no-pickup escalation** at least once (as a group is fine)
- [ ] Knows where **Amount** and **GMEET1 Link** live and why they're mandatory

## H. Support & what's coming

- **Questions / stuck:** they message you (the admin). You can inspect/fix any deal.
- **Cleanup after KT:** delete the 8 UAT practice deals when done (ask your pipeline admin — one command clears all `lead_source = UAT` deals).
- **Coming with the Pro upgrade** (set expectations, don't over-promise now): auto-send M1V1/M1V2 on stage entry, auto-created reminder tasks (Awaiting Meeting / Awaiting Results), email sequences, and Amount **hard-required** to advance past GMEET1. Until then, those are **manual habits** in the SOP.
