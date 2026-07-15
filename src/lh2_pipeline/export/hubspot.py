"""Backward-compat shim — the HubSpot integration now lives in focused modules
(scalingPlanV2 §Architecture):

  * hubspot_client.py   — shared HTTP client (auth, retries, rate limiting)
  * hubspot_setup.py    — properties, deal pipeline, email templates
  * hubspot_sync.py     — nightly Company+Contact+Deal upsert + feedback pull
  * hubspot_workflow.py — call outcomes, tasks, stage transitions

Import from those directly in new code; this module just re-exports.
"""

from .hubspot_client import (  # noqa: F401
    BASE_URL,
    HubspotClient,
    HubspotError,
    Responder,
    _chunks,
)
from .hubspot_setup import (  # noqa: F401
    CALL_FEEDBACK_PROPERTIES,
    CALL_OUTCOMES,
    COMPANY_GROUP,
    COMPANY_PROPERTIES,
    CONTACT_GROUP,
    CONTACT_PROPERTIES,
    DEAL_GROUP,
    DEAL_PROPERTIES,
    EMAIL_TEMPLATES,
    PIPELINE_NAME,
    PIPELINE_STAGES,
    run_hubspot_setup,
    templates_markdown,
)
from .hubspot_sync import (  # noqa: F401
    _company_props,
    _contact_props,
    _is_qualified,
    _split_name,
    run_hubspot_pull,
    run_hubspot_sync,
)
from .hubspot_workflow import (  # noqa: F401
    create_call_again_task,
    create_callback_task,
    create_followup_no_booking_task,
    create_number_lookup_task,
    create_results_followup_task,
    create_task,
    move_deal_to_stage,
    next_business_day,
    process_call_outcome,
)
