"""HubSpot one-time setup (idempotent): properties, deal pipeline, email templates.

scalingPlanV2 §1: everything a lead owner needs is configured via the API — no
UI clicking. Safe to re-run: existing properties/pipeline are skipped.

Pipeline note: this portal's tier caps deal pipelines at 1. If creating
"Codebase Acquisition" hits that limit, we REPURPOSE the default pipeline in
place (PUT replaces its label + stages) — safe here because deals are only ever
created by this pipeline's own sync.

Email templates note: HubSpot has no public API for creating sales email
templates on this tier, so per spec they are documented loudly (returned for
the CLI to print + write to hubspot_email_templates.md) — never silently skipped.
"""

from __future__ import annotations

from typing import Optional

from ..logging_setup import get_logger
from .hubspot_client import HubspotClient, HubspotError

log = get_logger("lh2.hubspot")


# --------------------------------------------------------------------------- #
# Property schema (scalingPlanV2 §1B-D)
# --------------------------------------------------------------------------- #
def _enum(options: list[str]) -> list[dict]:
    return [{"label": o, "value": o, "displayOrder": i} for i, o in enumerate(options)]


_BOOL_OPTIONS = [{"label": "Yes", "value": "true", "displayOrder": 0},
                 {"label": "No", "value": "false", "displayOrder": 1}]

COMPANY_GROUP = "companyinformation"
CONTACT_GROUP = "contactinformation"
DEAL_GROUP = "dealinformation"

COMPANY_PROPERTIES = [
    # Unique-value key for true idempotent upsert (standard `domain` isn't unique-value).
    {"name": "lh2_domain", "label": "LH2 Domain (unique key)", "type": "string",
     "fieldType": "text", "hasUniqueValue": True},
    {"name": "founded_year", "label": "Founded Year", "type": "number", "fieldType": "number"},
    {"name": "size_bucket", "label": "Size Bucket", "type": "enumeration", "fieldType": "select",
     "options": _enum(["1-100", "100-500", "500-1000"])},
    {"name": "headcount_source", "label": "Headcount Source", "type": "string", "fieldType": "text"},
    {"name": "segment", "label": "Segment", "type": "string", "fieldType": "text"},
    {"name": "pipeline_source", "label": "Pipeline Source", "type": "string", "fieldType": "text"},
    {"name": "pipeline_notes", "label": "Pipeline Notes", "type": "string", "fieldType": "textarea"},
    {"name": "pipeline_synced_at", "label": "Pipeline Synced At", "type": "date", "fieldType": "date"},
    # V2: evaluation results land on the company record (GMEET1 → Results stage).
    {"name": "eval_results", "label": "Evaluation Results", "type": "string", "fieldType": "textarea"},
    {"name": "eval_results_received_at", "label": "Results Received Date", "type": "date", "fieldType": "date"},
]

CONTACT_PROPERTIES = [
    {"name": "linkedin_url", "label": "LinkedIn URL", "type": "string", "fieldType": "text"},
    {"name": "contact_role", "label": "Contact Role", "type": "string", "fieldType": "text"},
    {"name": "spoc_type", "label": "SPOC Type", "type": "enumeration", "fieldType": "select",
     "options": _enum(["Primary", "Secondary"])},
]

# Caller fills these after each call → `lh2 hubspot-pull` reads them back into the
# pipeline so real outcomes can refine targeting/scoring (the feedback loop).
CALL_OUTCOMES = [
    "Not Called", "Connected", "No Answer", "Left Voicemail", "Interested",
    "Not Interested", "Callback Requested", "Wrong Contact", "Do Not Contact",
]
CALL_FEEDBACK_PROPERTIES = [
    {"name": "call_outcome", "label": "Call Outcome", "type": "enumeration",
     "fieldType": "select", "options": _enum(CALL_OUTCOMES)},
    {"name": "call_notes", "label": "Call Notes", "type": "string", "fieldType": "textarea"},
    {"name": "call_date", "label": "Call Date", "type": "date", "fieldType": "date"},
    {"name": "next_step", "label": "Next Step", "type": "string", "fieldType": "text"},
]

# V2: deals carry the sales-workflow state (scalingPlanV2 §1D).
DEAL_PROPERTIES = [
    # Unique key → deal-per-company dedup that can't race the search index.
    {"name": "lh2_domain", "label": "LH2 Domain (unique key)", "type": "string",
     "fieldType": "text", "hasUniqueValue": True},
    {"name": "call_outcome", "label": "Call Outcome", "type": "enumeration", "fieldType": "select",
     "options": _enum(["Connected - Interested", "Connected - Rejected", "Connected - Busy",
                       "Wrong Number", "No Pickup"])},
    {"name": "callback_datetime", "label": "Callback Date/Time", "type": "datetime", "fieldType": "date"},
    {"name": "needs_number_lookup", "label": "Needs Number Lookup", "type": "enumeration",
     "fieldType": "booleancheckbox", "options": _BOOL_OPTIONS},
    {"name": "email_version_sent", "label": "Email Version Sent", "type": "enumeration",
     "fieldType": "select", "options": _enum(["M1V1", "M1V2", "None"])},
    {"name": "calendly_link_sent", "label": "Calendly Link Sent", "type": "enumeration",
     "fieldType": "booleancheckbox", "options": _BOOL_OPTIONS},
    {"name": "gmeet1_date", "label": "GMEET1 Date", "type": "datetime", "fieldType": "date"},
    # Google Meet link, filled when a deal enters "GMEET1 Scheduled" (Calendly will
    # auto-populate this once connected; manual paste for now).
    {"name": "gmeet1_link", "label": "GMEET1 Link", "type": "string", "fieldType": "text"},
    {"name": "gmeet1_outcome", "label": "GMEET1 Outcome", "type": "enumeration", "fieldType": "select",
     "options": _enum(["Script Run On Call", "Client Will Run Later", "Rejected", "No Show"])},
    {"name": "script_status", "label": "Script Status", "type": "enumeration", "fieldType": "select",
     "options": _enum(["Not Started", "Sent to Client", "Running", "Results Received"])},
    {"name": "lead_source", "label": "Lead Source", "type": "string", "fieldType": "text"},
    {"name": "call_notes", "label": "Call Notes", "type": "string", "fieldType": "textarea"},
    {"name": "call_attempt_count", "label": "Call Attempt Count", "type": "number", "fieldType": "number"},
]


# --------------------------------------------------------------------------- #
# Deal pipeline (scalingPlanV2 §1A) — 18 stages, exact order
# --------------------------------------------------------------------------- #
PIPELINE_NAME = "Codebase Acquisition"
# (label, win probability, is_closed)
PIPELINE_STAGES = [
    ("New Lead", 0.10, False),
    ("Assigned", 0.10, False),
    ("Call Attempted", 0.15, False),
    ("Call Connected", 0.20, False),
    ("M1V1 Sent", 0.25, False),
    ("M1V2 Sent", 0.20, False),
    ("Awaiting Meeting", 0.30, False),
    ("GMEET1 Scheduled", 0.40, False),
    ("GMEET1 Completed", 0.50, False),
    ("Script Running", 0.55, False),
    ("Awaiting Results", 0.55, False),
    ("Results Received", 0.60, False),
    ("Results Under Review", 0.65, False),
    ("Won", 1.0, True),
    ("Dead - Rejected", 0.0, True),
    ("Dead - No Response", 0.0, True),
    ("Dead - Meeting Rejected", 0.0, True),
    ("Dead - Wrong Fit", 0.0, True),
]


def _pipeline_body() -> dict:
    return {
        "label": PIPELINE_NAME,
        "displayOrder": 0,
        "stages": [
            {"label": label, "displayOrder": i,
             "metadata": {"probability": str(prob), "isClosed": "true" if closed else "false"}}
            for i, (label, prob, closed) in enumerate(PIPELINE_STAGES)
        ],
    }


def ensure_pipeline(hc: HubspotClient) -> tuple[Optional[str], Optional[str]]:
    """Ensure the Codebase Acquisition pipeline exists.
    Returns (action, error): action in {None(exists), 'created', 'replaced_default'}."""
    pipelines = hc.list_deal_pipelines()
    if any(p.get("label") == PIPELINE_NAME for p in pipelines):
        return None, None

    status, resp = hc._request("POST", "/crm/v3/pipelines/deals", _pipeline_body())
    if status in (200, 201):
        return "created", None

    msg = str(resp)
    if status == 400 and "limit" in msg.lower() and "pipeline" in msg.lower() and pipelines:
        # Tier caps at 1 pipeline → repurpose the default one in place.
        default = sorted(pipelines, key=lambda p: p.get("displayOrder", 0))[0]
        status2, resp2 = hc._request(
            "PUT", f"/crm/v3/pipelines/deals/{default['id']}", _pipeline_body())
        if status2 in (200, 201):
            log.info("hubspot_pipeline_replaced_default", old_label=default.get("label"))
            return "replaced_default", None
        return None, f"replace default pipeline failed: {status2} {resp2}"
    return None, f"create pipeline failed: {status} {resp}"


# --------------------------------------------------------------------------- #
# Email templates (scalingPlanV2 §1E)
# --------------------------------------------------------------------------- #
# There is no public API for creating sales email templates on this tier, so per
# spec these are DOCUMENTED (printed + written to hubspot_email_templates.md by
# the CLI) for one-time manual creation in HubSpot UI — never silently skipped.
EMAIL_TEMPLATES = {
    "M1V1": {
        "subject": "Following Up - LH2 Data Labs x {{company.name}}",
        "body": (
            "Hi {{contact.firstname}},\n\n"
            "Great speaking with you earlier. As discussed, LH2 Data Labs acquires legacy "
            "codebases from established Indian IT-services firms like {{company.name}}.\n\n"
            "I'd love to walk you through how the evaluation process works — it's quick and "
            "straightforward.\n\n"
            "Pick a time that works for you: [CALENDLY_LINK]\n\n"
            "Looking forward to connecting.\n\n"
            "Best,\n{{owner.first_name}}\nLH2 Data Labs"
        ),
        "when": "After a connected, interested cold call (Outcome 1).",
    },
    "M1V2": {
        "subject": "Quick question about {{company.name}}'s codebase",
        "body": (
            "Hi {{contact.firstname}},\n\n"
            "I'm reaching out from LH2 Data Labs. We work with Indian IT-services firms to "
            "acquire legacy codebases — turning unused projects into real value.\n\n"
            "Would love to have a quick 15-minute call to see if there's a fit.\n\n"
            "Here's my calendar: [CALENDLY_LINK]\n\n"
            "Best,\n{{owner.first_name}}\nLH2 Data Labs"
        ),
        "when": "Cold email when the call wasn't picked up (Outcome 5).",
    },
}


# --------------------------------------------------------------------------- #
# run_hubspot_setup
# --------------------------------------------------------------------------- #
def run_hubspot_setup(cfg, store=None, client: Optional[HubspotClient] = None,  # noqa: ANN001
                      dry_run: bool = False) -> dict:
    hc = client or HubspotClient(token=cfg.secrets.hubspot_api_key)
    created = {"company_props": [], "contact_props": [], "deal_props": [],
               "pipeline": None, "pipeline_action": None, "pipeline_error": None,
               "templates": {name: "manual" for name in EMAIL_TEMPLATES},
               "skipped": []}

    for obj, props, group, key in (
        ("companies", COMPANY_PROPERTIES, COMPANY_GROUP, "company_props"),
        ("contacts", CONTACT_PROPERTIES + CALL_FEEDBACK_PROPERTIES, CONTACT_GROUP, "contact_props"),
        ("deals", DEAL_PROPERTIES, DEAL_GROUP, "deal_props"),
    ):
        for spec in props:
            if hc.property_exists(obj, spec["name"]):
                created["skipped"].append(f"{obj}.{spec['name']}")
                continue
            if not dry_run:
                hc.create_property(obj, spec, group)
            created[key].append(spec["name"])

    if hc.get_deal_pipeline(PIPELINE_NAME) is not None:
        created["skipped"].append(f"pipeline:{PIPELINE_NAME}")
    elif dry_run:
        created["pipeline"] = PIPELINE_NAME
    else:
        action, err = ensure_pipeline(hc)
        if err:
            created["pipeline_error"] = err
        elif action:
            created["pipeline"] = PIPELINE_NAME
            created["pipeline_action"] = action

    log.info("hubspot_setup",
             created_company=len(created["company_props"]),
             created_contact=len(created["contact_props"]),
             created_deal=len(created["deal_props"]),
             pipeline=created["pipeline"], pipeline_action=created["pipeline_action"],
             skipped=len(created["skipped"]))
    return created


def templates_markdown() -> str:
    """The email templates as a markdown doc for one-time manual creation."""
    lines = [
        "# HubSpot Email Templates — create once in HubSpot UI",
        "",
        "> HubSpot's tier has no API for sales email templates, so create these",
        "> manually: **Settings → Objects → Activities → Email templates** (or",
        "> compose an email → Templates → Save as template). Replace",
        "> `[CALENDLY_LINK]` with the lead owner's real Calendly URL.",
        "",
    ]
    for name, t in EMAIL_TEMPLATES.items():
        lines += [f"## {name}", "", f"**Use:** {t['when']}", "",
                  f"**Subject:** `{t['subject']}`", "", "```", t["body"], "```", ""]
    return "\n".join(lines)
