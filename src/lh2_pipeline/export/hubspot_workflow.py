"""HubSpot sales-workflow engine: tasks, stage transitions, call outcomes.

scalingPlanV2 §3-5. Lead owners drive the journey mostly in HubSpot UI; these
helpers (and `lh2 hubspot-call-outcome`) automate the branchy parts:

  Cold call → 5 outcomes:
    1 Connected+interested → "M1V1 Sent" + follow-up task (+1 business day)
    2 Connected+rejected   → "Dead - Rejected" (closed lost) + reason logged
    3 Connected+busy       → callback task (at the given time, else next b-day)
    4 Wrong number         → flag needs_number_lookup + Apollo-lookup task (today)
    5 No pickup            → "M1V2 Sent" + call-again task; a 2nd no-pickup
                             escalates to M1V1 + final-follow-up; a 3rd goes to
                             "Dead - No Response".

Stage names are resolved to HubSpot's internal stage IDs at call time (the
``dealstage`` property takes IDs, not labels).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ..logging_setup import get_logger
from .hubspot_client import HubspotClient, HubspotError
from .hubspot_setup import PIPELINE_NAME

log = get_logger("lh2.hubspot")


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def next_business_day(days: int = 1, from_dt: Optional[datetime] = None,
                      at_hour_utc: int = 5) -> datetime:
    """``days`` business days after ``from_dt`` (default now, UTC), skipping
    weekends, at ``at_hour_utc``:00 (05:00 UTC ≈ 10:30 IST — start of workday)."""
    dt = from_dt or datetime.now(timezone.utc)
    remaining = max(1, days)
    while remaining > 0:
        dt += timedelta(days=1)
        if dt.weekday() < 5:               # Mon-Fri
            remaining -= 1
    return dt.replace(hour=at_hour_utc, minute=0, second=0, microsecond=0)


def _ms(dt: datetime) -> int:
    """Datetime → UTC epoch milliseconds (HubSpot datetime format).
    Naive datetimes are treated as local time."""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return int(dt.timestamp() * 1000)


# --------------------------------------------------------------------------- #
# Pipeline stage resolution
# --------------------------------------------------------------------------- #
def get_stage_map(hc: HubspotClient) -> tuple[str, dict]:
    """(pipeline_id, {stage label: stage id}) for the Codebase Acquisition pipeline."""
    pipeline = hc.get_deal_pipeline(PIPELINE_NAME)
    if pipeline is None:
        raise HubspotError(f"pipeline '{PIPELINE_NAME}' not found — run `lh2 hubspot-setup` first")
    return pipeline["id"], {s["label"]: s["id"] for s in pipeline.get("stages", [])}


def move_deal_to_stage(hc: HubspotClient, deal_id: str, stage_name: str,
                       properties: Optional[dict] = None,
                       stage_map: Optional[dict] = None) -> None:
    """Move a deal to a named stage (resolved to its internal ID), optionally
    updating other deal properties in the same PATCH. Logs the transition."""
    if stage_map is None:
        _, stage_map = get_stage_map(hc)
    stage_id = stage_map.get(stage_name)
    if not stage_id:
        raise HubspotError(f"unknown stage '{stage_name}' (have: {sorted(stage_map)})")
    props = dict(properties or {})
    props["dealstage"] = stage_id
    status, resp = hc._request("PATCH", f"/crm/v3/objects/deals/{deal_id}", {"properties": props})
    if status not in (200, 201):
        raise HubspotError(f"move deal {deal_id} to '{stage_name}' failed: {status} {resp}")
    log.info("hubspot_deal_stage", deal_id=deal_id, stage=stage_name)


# --------------------------------------------------------------------------- #
# Tasks (scalingPlanV2 §3)
# --------------------------------------------------------------------------- #
def create_task(hc: HubspotClient, title: str, due: datetime, deal_id: str,
                contact_id: Optional[str] = None, notes: str = "",
                priority: str = "MEDIUM", task_type: str = "TODO") -> str:
    """Create a HubSpot task associated with a deal (and optionally a contact).
    Tasks are action items — intentionally not idempotent."""
    props = {
        "hs_task_subject": title,
        "hs_task_body": notes,
        "hs_timestamp": _ms(due),
        "hs_task_priority": priority,        # HIGH | MEDIUM | LOW
        "hs_task_status": "NOT_STARTED",
        "hs_task_type": task_type,           # CALL | EMAIL | TODO
    }
    status, resp = hc._request("POST", "/crm/v3/objects/tasks", {"properties": props})
    if status not in (200, 201) or not resp.get("id"):
        raise HubspotError(f"create task '{title}' failed: {status} {resp}")
    task_id = resp["id"]
    hc.associate_default("tasks", "deals", [(task_id, deal_id)])
    if contact_id:
        hc.associate_default("tasks", "contacts", [(task_id, contact_id)])
    log.info("hubspot_task", task=title, due=str(due), deal_id=deal_id)
    return task_id


# Pre-built task templates (spec table).
def create_callback_task(hc, deal_id, callback_time: datetime, company: str = "",
                         contact_id=None) -> str:  # noqa: ANN001
    return create_task(hc, f"Callback - {company}".strip(" -"), callback_time, deal_id,
                       contact_id=contact_id, priority="HIGH", task_type="CALL",
                       notes="Prospect asked to be called back at this time.")


def create_followup_no_booking_task(hc, deal_id, contact_id=None) -> str:  # noqa: ANN001
    return create_task(hc, "Follow up - no meeting booked", next_business_day(1), deal_id,
                       contact_id=contact_id, priority="MEDIUM", task_type="CALL",
                       notes="M1V1 sent; call to push for a Calendly booking if none yet.")


def create_number_lookup_task(hc, deal_id, contact_id=None) -> str:  # noqa: ANN001
    due = datetime.now(timezone.utc) + timedelta(hours=2)
    return create_task(hc, "Apollo lookup - wrong number", due, deal_id,
                       contact_id=contact_id, priority="HIGH", task_type="TODO",
                       notes="Wrong number - needs Apollo/alternate lookup. Update the "
                             "contact's phone, then restart the call process.")


def create_call_again_task(hc, deal_id, contact_id=None) -> str:  # noqa: ANN001
    return create_task(hc, "Call again - no pickup", next_business_day(1), deal_id,
                       contact_id=contact_id, priority="MEDIUM", task_type="CALL",
                       notes="No pickup on last attempt; M1V2 sent. Try again.")


def create_results_followup_task(hc, deal_id, contact_id=None) -> str:  # noqa: ANN001
    return create_task(hc, "Follow up on script results", next_business_day(2), deal_id,
                       contact_id=contact_id, priority="MEDIUM", task_type="TODO",
                       notes="Client said they'd run the eval script and send results.")


# --------------------------------------------------------------------------- #
# Call-outcome engine (scalingPlanV2 §5)
# --------------------------------------------------------------------------- #
OUTCOME_LABELS = {
    1: "Connected - Interested",
    2: "Connected - Rejected",
    3: "Connected - Busy",
    4: "Wrong Number",
    5: "No Pickup",
}


def _get_deal(hc: HubspotClient, deal_id: str) -> dict:
    status, resp = hc._request(
        "GET",
        f"/crm/v3/objects/deals/{deal_id}"
        "?properties=dealname,call_attempt_count,call_notes,email_version_sent")
    if status != 200:
        raise HubspotError(f"deal {deal_id} not found: {status} {resp}")
    return resp.get("properties", {}) or {}


def process_call_outcome(hc: HubspotClient, deal_id: str, outcome: int,
                         contact_id: Optional[str] = None,
                         callback_time: Optional[datetime] = None,
                         call_notes: str = "") -> dict:
    """Process a cold-call outcome (1-5): move the deal, set properties, create
    the right follow-up task. Returns a summary of the actions taken."""
    if outcome not in OUTCOME_LABELS:
        raise ValueError(f"outcome must be 1-5, got {outcome}")

    deal = _get_deal(hc, deal_id)
    company = (deal.get("dealname") or "").replace(" - Codebase Acquisition", "")
    attempts = int(float(deal.get("call_attempt_count") or 0)) + 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    note_line = f"[{stamp}] call #{attempts} — {OUTCOME_LABELS[outcome]}"
    if call_notes:
        note_line += f": {call_notes}"

    props: dict = {"call_outcome": OUTCOME_LABELS[outcome],
                   "call_attempt_count": attempts}
    actions: list[str] = []
    tasks: list[str] = []

    if outcome == 1:
        # Connected + interested → M1V1 + Calendly; follow up if no booking.
        stage = "M1V1 Sent"
        props |= {"email_version_sent": "M1V1", "calendly_link_sent": "true"}
        actions.append("Send the M1V1 email (HubSpot template) with your Calendly link")
        tasks.append(create_followup_no_booking_task(hc, deal_id, contact_id))

    elif outcome == 2:
        # Hard rejection → closed lost, reason in notes.
        stage = "Dead - Rejected"
        if not call_notes:
            note_line += " (no reason recorded)"
        actions.append("Deal closed as Lost (Dead - Rejected)")

    elif outcome == 3:
        # Busy → stays in play; callback at the given time or next business day.
        stage = "Call Attempted"
        if callback_time is not None:
            props["callback_datetime"] = _ms(callback_time)
            tasks.append(create_callback_task(hc, deal_id, callback_time, company, contact_id))
            actions.append(f"Callback task created for {callback_time}")
        else:
            tasks.append(create_task(hc, "Callback - was busy", next_business_day(1), deal_id,
                                     contact_id=contact_id, priority="MEDIUM", task_type="CALL",
                                     notes="Said busy, no specific time given."))
            actions.append("Callback task created for the next business day")

    elif outcome == 4:
        # Wrong number → flag for Apollo lookup; restart calls once fixed.
        stage = "Call Attempted"
        props["needs_number_lookup"] = "true"
        note_line += " | Wrong number - needs Apollo/alternate lookup"
        tasks.append(create_number_lookup_task(hc, deal_id, contact_id))
        actions.append("Flagged needs_number_lookup; Apollo-lookup task due today")

    else:  # outcome == 5 — no pickup, with escalation chain
        prev = (deal.get("email_version_sent") or "None").strip()
        if prev in ("", "None"):
            stage = "M1V2 Sent"
            props["email_version_sent"] = "M1V2"
            actions.append("Send the M1V2 cold email (no prior call context)")
            tasks.append(create_call_again_task(hc, deal_id, contact_id))
        elif prev == "M1V2":
            # 2nd no-pickup after M1V2 → escalate with M1V1 + final follow-up.
            stage = "M1V1 Sent"
            props["email_version_sent"] = "M1V1"
            actions.append("Escalation: send the M1V1 email")
            tasks.append(create_task(hc, "Final follow-up call", next_business_day(1), deal_id,
                                     contact_id=contact_id, priority="HIGH", task_type="CALL",
                                     notes="Second no-pickup; M1V1 escalation sent. Last attempt."))
        else:
            # Already escalated and still nothing → dead.
            stage = "Dead - No Response"
            actions.append("No response after full sequence — closed as Dead - No Response")

    existing_notes = deal.get("call_notes") or ""
    props["call_notes"] = f"{existing_notes}\n{note_line}".strip()

    move_deal_to_stage(hc, deal_id, stage, props)
    summary = {"deal_id": deal_id, "company": company, "outcome": OUTCOME_LABELS[outcome],
               "stage": stage, "call_attempt_count": attempts,
               "tasks_created": tasks, "actions": actions}
    log.info("hubspot_call_outcome", **{k: v for k, v in summary.items() if k != "actions"})
    return summary
