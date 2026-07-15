"""Workflow-engine tests (scalingPlanV2 §3-5) — offline via injected responder.
Covers business-day math, task creation + associations, stage transitions by
label→ID, all five call-outcome branches, the no-pickup escalation chain, and
the client's sliding-window rate limiter."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lh2_pipeline.export.hubspot_client import HubspotClient, HubspotError
from lh2_pipeline.export.hubspot_workflow import (
    create_task,
    move_deal_to_stage,
    next_business_day,
    process_call_outcome,
)

FAKE_PIPELINE = {"results": [{"id": "pipe1", "label": "Codebase Acquisition", "stages": [
    {"id": "s-new", "label": "New Lead"},
    {"id": "s-attempted", "label": "Call Attempted"},
    {"id": "s-m1v1", "label": "M1V1 Sent"},
    {"id": "s-m1v2", "label": "M1V2 Sent"},
    {"id": "s-dead-rej", "label": "Dead - Rejected"},
    {"id": "s-dead-nr", "label": "Dead - No Response"},
]}]}


# --------------------------------------------------------------------------- #
# Harness: records every call; scripted deal state
# --------------------------------------------------------------------------- #
class Recorder:
    def __init__(self, deal_props=None):
        self.deal_props = deal_props or {}
        self.patches: list[dict] = []
        self.tasks: list[dict] = []
        self.assocs: list[str] = []

    def __call__(self, method, path, json):
        if path == "/crm/v3/pipelines/deals":
            return 200, FAKE_PIPELINE
        if method == "GET" and path.startswith("/crm/v3/objects/deals/"):
            return 200, {"id": "D1", "properties": self.deal_props}
        if method == "PATCH" and path.startswith("/crm/v3/objects/deals/"):
            self.patches.append(json["properties"])
            return 200, {}
        if method == "POST" and path == "/crm/v3/objects/tasks":
            self.tasks.append(json["properties"])
            return 201, {"id": f"task{len(self.tasks)}"}
        if "associate/default" in path:
            self.assocs.append(path)
            return 201, {}
        raise AssertionError(f"unexpected {method} {path}")


def _hc(rec: Recorder) -> HubspotClient:
    return HubspotClient(responder=rec)


# --------------------------------------------------------------------------- #
# Business days
# --------------------------------------------------------------------------- #
def test_next_business_day_skips_weekend():
    fri = datetime(2026, 7, 17, 15, 0, tzinfo=timezone.utc)      # Friday
    nbd = next_business_day(1, from_dt=fri)
    assert nbd.weekday() == 0 and nbd.day == 20                  # Monday Jul 20
    assert nbd.hour == 5 and nbd.minute == 0
    wed = datetime(2026, 7, 15, tzinfo=timezone.utc)             # Wednesday
    assert next_business_day(2, from_dt=wed).day == 17           # Friday


# --------------------------------------------------------------------------- #
# Tasks + stage moves
# --------------------------------------------------------------------------- #
def test_create_task_posts_and_associates():
    rec = Recorder()
    due = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
    tid = create_task(_hc(rec), "Do the thing", due, "D1", contact_id="C1",
                      notes="ctx", priority="HIGH", task_type="CALL")
    assert tid == "task1"
    t = rec.tasks[0]
    assert t["hs_task_subject"] == "Do the thing"
    assert t["hs_task_priority"] == "HIGH" and t["hs_task_type"] == "CALL"
    assert t["hs_timestamp"] == int(due.timestamp() * 1000)
    assert any("tasks/deals" in p for p in rec.assocs)
    assert any("tasks/contacts" in p for p in rec.assocs)


def test_move_deal_resolves_stage_id_and_rejects_unknown():
    rec = Recorder()
    move_deal_to_stage(_hc(rec), "D1", "M1V1 Sent", {"call_outcome": "Connected - Interested"})
    assert rec.patches[0]["dealstage"] == "s-m1v1"
    assert rec.patches[0]["call_outcome"] == "Connected - Interested"
    with pytest.raises(HubspotError):
        move_deal_to_stage(_hc(Recorder()), "D1", "No Such Stage")


# --------------------------------------------------------------------------- #
# Call outcomes
# --------------------------------------------------------------------------- #
def _fresh_deal():
    return {"dealname": "Acme Labs - Codebase Acquisition",
            "call_attempt_count": "0", "call_notes": "", "email_version_sent": "None"}


def test_outcome_1_interested_moves_to_m1v1_with_task():
    rec = Recorder(_fresh_deal())
    r = process_call_outcome(_hc(rec), "D1", 1, contact_id="C1", call_notes="keen on eval")
    p = rec.patches[0]
    assert p["dealstage"] == "s-m1v1"
    assert p["call_outcome"] == "Connected - Interested"
    assert p["email_version_sent"] == "M1V1" and p["calendly_link_sent"] == "true"
    assert p["call_attempt_count"] == 1 and "keen on eval" in p["call_notes"]
    assert rec.tasks[0]["hs_task_subject"] == "Follow up - no meeting booked"
    assert r["stage"] == "M1V1 Sent" and r["company"] == "Acme Labs"


def test_outcome_2_rejected_closes_lost():
    rec = Recorder(_fresh_deal())
    process_call_outcome(_hc(rec), "D1", 2, call_notes="not selling, ever")
    p = rec.patches[0]
    assert p["dealstage"] == "s-dead-rej"
    assert p["call_outcome"] == "Connected - Rejected"
    assert "not selling" in p["call_notes"]
    assert rec.tasks == []                                    # no follow-up task


def test_outcome_3_busy_with_callback_time():
    rec = Recorder(_fresh_deal())
    cb = datetime(2026, 7, 16, 14, 30, tzinfo=timezone.utc)
    process_call_outcome(_hc(rec), "D1", 3, callback_time=cb)
    p = rec.patches[0]
    assert p["dealstage"] == "s-attempted"
    assert p["callback_datetime"] == int(cb.timestamp() * 1000)
    t = rec.tasks[0]
    assert t["hs_task_subject"] == "Callback - Acme Labs"
    assert t["hs_task_priority"] == "HIGH"
    assert t["hs_timestamp"] == int(cb.timestamp() * 1000)    # due at the exact time


def test_outcome_3_busy_without_time_next_business_day():
    rec = Recorder(_fresh_deal())
    process_call_outcome(_hc(rec), "D1", 3)
    assert "callback_datetime" not in rec.patches[0]
    assert rec.tasks[0]["hs_task_subject"] == "Callback - was busy"


def test_outcome_4_wrong_number_flags_lookup():
    rec = Recorder(_fresh_deal())
    process_call_outcome(_hc(rec), "D1", 4)
    p = rec.patches[0]
    assert p["needs_number_lookup"] == "true"
    assert "Apollo/alternate lookup" in p["call_notes"]
    assert rec.tasks[0]["hs_task_subject"] == "Apollo lookup - wrong number"
    assert rec.tasks[0]["hs_task_priority"] == "HIGH"


def test_outcome_5_no_pickup_escalation_chain():
    # 1st no-pickup: fresh deal → M1V2 + call-again task
    rec = Recorder(_fresh_deal())
    process_call_outcome(_hc(rec), "D1", 5)
    assert rec.patches[0]["dealstage"] == "s-m1v2"
    assert rec.patches[0]["email_version_sent"] == "M1V2"
    assert rec.tasks[0]["hs_task_subject"] == "Call again - no pickup"

    # 2nd no-pickup (M1V2 already sent) → escalate to M1V1 + final follow-up
    rec2 = Recorder(_fresh_deal() | {"email_version_sent": "M1V2", "call_attempt_count": "1"})
    process_call_outcome(_hc(rec2), "D1", 5)
    assert rec2.patches[0]["dealstage"] == "s-m1v1"
    assert rec2.patches[0]["email_version_sent"] == "M1V1"
    assert rec2.patches[0]["call_attempt_count"] == 2
    assert rec2.tasks[0]["hs_task_subject"] == "Final follow-up call"

    # 3rd no-pickup (already escalated to M1V1) → Dead - No Response
    rec3 = Recorder(_fresh_deal() | {"email_version_sent": "M1V1", "call_attempt_count": "2"})
    r3 = process_call_outcome(_hc(rec3), "D1", 5)
    assert rec3.patches[0]["dealstage"] == "s-dead-nr"
    assert r3["stage"] == "Dead - No Response"
    assert rec3.tasks == []


def test_outcome_out_of_range_rejected():
    with pytest.raises(ValueError):
        process_call_outcome(_hc(Recorder(_fresh_deal())), "D1", 6)


# --------------------------------------------------------------------------- #
# Rate limiter (client) — fake clock, never really sleeps
# --------------------------------------------------------------------------- #
def test_client_rate_limiter_paces_after_window_fills():
    class Clock:
        t = 0.0
        def now(self):
            return self.t
        def sleep(self, s):
            self.t += s
    ck = Clock()
    slept = []
    def sleep(s):
        slept.append(s)
        ck.sleep(s)
    hc = HubspotClient(responder=None, token="t", rate_limit=10, rate_window_s=10.0,
                       clock=ck.now, sleep=sleep)
    # drive the pacer directly (no HTTP): 90% of 10 = 9 free slots
    for _ in range(9):
        hc._pace()
    assert slept == []
    hc._pace()                                   # 10th within the window → must wait
    assert len(slept) == 1 and slept[0] > 0
