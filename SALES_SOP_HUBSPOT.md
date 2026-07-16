# Sales SOP — HubSpot (Codebase Acquisition)

**This is mandatory.** Every lead moves through HubSpot the same way, every time.
If a step here says **MUST**, it is not optional. Consistent data = accurate
forecasting and no lead going cold.

> Everything is done in the **HubSpot web UI**. You never touch a terminal.
> Pipeline: **Codebase Acquisition** (CRM → Deals). Each lead = a **Deal** with a
> **Company** and its founder **Contacts** (SPOC 1 + sometimes SPOC 2).

---

## 0. ONE-TIME SETUP (Day 1 — do all of it before working any lead)

1. **Accept your seat invite** (email from HubSpot) and set your password.
2. **Add your profile + email signature:** top-right avatar → **Profile & Preferences → Signature** → add your name, title, phone.
3. **Connect your inbox (MUST).** Settings (gear) → **General → Email** tab → **Connect personal email** → choose **Google/Gmail** → sign in with your **@lh2.ai** address → allow access.
   - This makes every email you send from HubSpot go from *you* and log automatically.
4. **Connect your calendar + create your meeting link (MUST).** Settings → **General → Calendar** → connect Google Calendar. Then **CRM → Meetings scheduling pages → Create scheduling page** → name it (e.g. "Bhanu – 15-min intro") → copy the link. **This is your "Calendly link"** you paste into the M1V1 email.
5. **Turn on task reminders (MUST).** Settings → **Notifications** → enable **Tasks** (email + in-app) so overdue tasks nudge you.
6. **Find your two email templates.** CRM → **Email templates** → confirm **M1V1** and **M1V2** exist (your manager shares them). You'll use these on every lead — do not rewrite them.
7. **Bookmark two screens:** the **Deals board** (Codebase Acquisition pipeline, board view) and your **Tasks** queue.

✅ You're set up when: inbox connected, meeting link created, templates visible, task reminders on.

---

## 1. YOUR DAILY RHYTHM

1. **Open your Tasks queue first.** Work **overdue (red)** tasks before anything else — those are callbacks, follow-ups, and nudges that are already late.
2. **Claim new leads.** On the Deals board, in **New Lead**, open a card → set **Deal owner = you** → move it to **Assigned**. (Only work leads you own.)
3. **Make your calls.** After **every** call, run the ritual below.

---

## 2. THE "AFTER EVERY CALL" RITUAL — 4 steps, always

No matter the outcome, after each call you MUST do these four, in order:

1. **Log the call.** On the deal → **Call** icon → pick the closest **call outcome**, write **notes** → **Log activity**.
2. **Set the deal's `Call Outcome` field.** About this deal → **Actions ▸ View all properties** → **Call Outcome** → pick the matching value (see §3).
3. **Move the Deal Stage** to the one for that outcome (§3).
4. **Create the next Task** (§3) so the lead never stalls.

> If you did a call and there's **no task on the deal afterward**, you did it wrong.

---

## 3. THE 5 CALL OUTCOMES — exact actions (STRICT)

| # | What happened on the call | Set `Call Outcome` = | Move stage to | Create task |
|---|---|---|---|---|
| **①** | Picked up, right person, **interested** | `Connected - Interested` | **Call Connected**, then **M1V1 Sent** (after you send M1V1) | "Follow up - no meeting booked" · **due +1 day** |
| **②** | Picked up, **hard rejection** | `Connected - Rejected` | **Dead - Rejected** | none (log the reason in notes) |
| **③** | Picked up, **busy** | `Connected - Busy` | **Call Attempted** | If they gave a time → "Callback" **at that exact time**; else "Callback - was busy" **+1 day** |
| **④** | **Wrong number** | `Wrong Number` | **Call Attempted** | "Apollo lookup - wrong number" · **due today**; also set **Needs Number Lookup = Yes** |
| **⑤** | **No pickup** | `No Pickup` | see escalation ↓ | see escalation ↓ |

### Outcome ① — the interested path (most important)
1. Ritual steps 1–2 (log call, set Call Outcome = Connected - Interested).
2. Move stage → **Call Connected**.
3. **Send the M1V1 email:** deal → **Email** → **Templates → M1V1** → make sure the Calendly link is **your** meeting link → **Send**.
4. Move stage → **M1V1 Sent**.
5. Create task **"Follow up - no meeting booked"**, due **+1 day**.

### Outcome ⑤ — no-pickup escalation (follow exactly)
- **1st no-pickup:** send **M1V2** (Email → Templates → M1V2) → stage **M1V2 Sent** → task **"Call again - no pickup"** (+1 day).
- **2nd no-pickup:** send **M1V1** → stage **M1V1 Sent** → task **"Final follow-up call"** (+1 day).
- **3rd no-pickup:** stage **Dead - No Response**. Stop.
- *If they ever reply or pick up → jump to the interested path (M1V1 Sent).*

### Outcomes ③ & ④ keep the deal alive
Busy and Wrong-Number stay in **Call Attempted** — you loop back and call again (at the callback time / once the number is fixed). Don't let them rot: the task is your reminder.

---

## 4. AFTER THE INTRO EMAIL — meeting → eval → results

### 4a. Waiting on the meeting
- Deal is in **M1V1 Sent** with your Calendly link out.
- **They book quickly** → move to **GMEET1 Scheduled**.
- **They don't book** → move to **Awaiting Meeting** and create a task **"Push for meeting - book or drop"** due **+2 days** (MUST — this is your nudge). Call to push:
  - booked → **GMEET1 Scheduled**
  - refused → **Dead - Meeting Rejected**

### 4b. GMEET1 Scheduled (MUST paste the meeting link)
- When you schedule, **paste the Google Meet link** into the deal's **GMEET1 Link** field (Actions ▸ View all properties → GMEET1 Link).

### 4c. After the eval call — enter the DEAL VALUE (MUST)
- Move stage → **GMEET1 Completed**.
- **MUST: enter the `Amount` (deal value)** on the deal before advancing. No Amount → do not move forward. *(This number is what your forecast is built on and becomes the closed value when Won.)*
- Set the **GMEET1 Outcome**:
  - **They run the script on the call (O1):** GMEET1 Outcome = `Script Run On Call`, Script Status = `Running` → stage **Script Running** → task **"Collect script results"** (today).
  - **They'll run it later (O2):** GMEET1 Outcome = `Client Will Run Later`, Script Status = `Sent to Client` → stage **Awaiting Results** → task **"Follow up on script results"** (+2 days).

### 4d. Results
- Results in → on the **Company** record, fill **Evaluation Results** + **Results Received Date**; set deal **Script Status = Results Received**.
- Move deal → **Results Received** → **Results Under Review** (handoff).

### 4e. Closing
- Deal won → **Won** (the Amount becomes closed revenue).
- Any point it's not a fit → **Dead - Wrong Fit** (note why).

---

## 5. THE 10 GOLDEN RULES (non-negotiable)

1. **Only work leads you own.** Claim it (Assigned) before you call.
2. **Log every call.** No exceptions.
3. **Move the stage after every call.** The board must reflect reality.
4. **Every deal you touch leaves with a next task.** No orphan deals.
5. **Clear your overdue (red) tasks first, every morning.**
6. **Send M1V1/M1V2 only from the shared templates** — never freehand.
7. **Paste the GMEET1 Link** when you schedule a meeting.
8. **MUST enter `Amount` (deal value) after GMEET1** before advancing.
9. **Never delete a deal.** Dead deals go to a **Dead - …** stage, not the trash.
10. **Notes matter** — write what was said; the next person (and forecasting) relies on it.

---

## 6. QUICK REFERENCE

**The 18 stages (left → right on the board):**
New Lead → Assigned → Call Attempted → Call Connected → M1V1 Sent → M1V2 Sent →
Awaiting Meeting → GMEET1 Scheduled → GMEET1 Completed → Script Running →
Awaiting Results → Results Received → Results Under Review → **Won** ·
**Dead - Rejected · Dead - No Response · Dead - Meeting Rejected · Dead - Wrong Fit**

**Where things live:**
- **Deal fields** (Call Outcome, Amount, GMEET1 Link/Outcome, Script Status): open the deal → **Actions ▸ View all properties**, or the pinned card.
- **Founder info** (LinkedIn, phone, role) — the **Contacts** card on the right (SPOC 1 = Primary, SPOC 2 = Secondary).
- **Company info** (headcount, size, founded, segment) — the **Companies** card on the right.
- **Your work list** — the **Tasks** queue.

**Picture of the whole flow:** see the workflow flowchart your manager shares.
