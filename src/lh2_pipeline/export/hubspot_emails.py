"""Phase 5d — automated M1V1/M1V2 outreach, triggered by HubSpot deal stage.

The lead owner just moves a deal to **"M1V1 Sent"** (or **"M1V2 Sent"**) in the
HubSpot UI. `run_send_emails` then, for every such deal that hasn't had that email
yet:
  1. renders the template (contact first name, company, owner, Calendly link),
  2. sends it over SMTP from the owner's mailbox,
  3. sets the deal's ``email_version_sent`` (+ ``calendly_link_sent`` for M1V1)
     so it's never re-sent,
  4. best-effort logs the email onto the HubSpot timeline (contact + deal).

Contact/company details come from the local pipeline DB (via the deal's
``lh2_domain``) — no extra HubSpot reads. SMTP + template rendering are injectable
so tests run fully offline. STANDARD-tier friendly (no Workflows/Sequences).
"""

from __future__ import annotations

from typing import Callable, Optional

from ..logging_setup import get_logger
from ..models import utcnow
from .hubspot_client import HubspotClient
from .hubspot_setup import EMAIL_TEMPLATES

log = get_logger("lh2.outreach")

# deal stage label → which template that stage triggers
STAGE_TO_VERSION = {"M1V1 Sent": "M1V1", "M1V2 Sent": "M1V2"}


def render(template: dict, first_name: str, company: str, owner: str, calendly: str) -> tuple[str, str]:
    subj = (template["subject"]
            .replace("{{company.name}}", company)
            .replace("{{contact.firstname}}", first_name))
    body = (template["body"]
            .replace("{{contact.firstname}}", first_name)
            .replace("{{company.name}}", company)
            .replace("{{owner.first_name}}", owner)
            .replace("[CALENDLY_LINK]", calendly))
    return subj, body


def smtp_send(cfg, to_email: str, subject: str, body: str) -> None:  # noqa: ANN001
    import smtplib
    from email.message import EmailMessage

    oc = cfg.outreach
    from_email = oc.from_email or cfg.secrets.smtp_user
    msg = EmailMessage()
    msg["From"] = f"{oc.from_name} <{from_email}>" if oc.from_name else from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(oc.smtp_host, oc.smtp_port, timeout=30) as s:
        s.starttls()
        s.login(cfg.secrets.smtp_user, cfg.secrets.smtp_password)
        s.send_message(msg)


def _log_email(hc: HubspotClient, deal_id: str, to_email: str, subject: str, body: str) -> None:
    """Best-effort: record the sent email on the HubSpot timeline (never fatal)."""
    try:
        ts = int(utcnow().timestamp() * 1000)
        st, resp = hc._request("POST", "/crm/v3/objects/emails", {"properties": {
            "hs_timestamp": ts, "hs_email_direction": "EMAIL", "hs_email_status": "SENT",
            "hs_email_subject": subject, "hs_email_text": body}})
        eid = resp.get("id") if st in (200, 201) else None
        if not eid:
            return
        hc.associate_default("emails", "deals", [(eid, deal_id)])
        cid = hc.search_ids("contacts", "email", [to_email]).get(to_email.lower())
        if cid:
            hc.associate_default("emails", "contacts", [(eid, cid)])
    except Exception as e:  # noqa: BLE001
        log.info("email_log_failed", deal_id=deal_id, err=str(e))


def _first_name(person) -> str:  # noqa: ANN001
    if person and person.name and person.name != "(verify)":
        return person.name.strip().split()[0]
    return "there"


def run_send_emails(cfg, store, client: Optional[HubspotClient] = None,  # noqa: ANN001
                    sender: Optional[Callable[[str, str, str], None]] = None,
                    dry_run: bool = False, limit: Optional[int] = None) -> dict:
    from .hubspot_workflow import get_stage_map

    hc = client or HubspotClient(token=cfg.secrets.hubspot_api_key)
    oc = cfg.outreach
    calendly = oc.calendly_link
    owner = oc.from_name or "the LH2 team"

    if not dry_run:
        if not (cfg.secrets.smtp_user and cfg.secrets.smtp_password):
            raise RuntimeError("SMTP_USER / SMTP_PASSWORD not set in .env")
        if not calendly:
            raise RuntimeError("outreach.calendly_link is empty in config.yaml")
    send = sender or (lambda to, subj, body: smtp_send(cfg, to, subj, body))

    _, stages = get_stage_map(hc)
    stage_version = {stages[label]: v for label, v in STAGE_TO_VERSION.items() if label in stages}
    if not stage_version:
        raise RuntimeError("M1V1 Sent / M1V2 Sent stages not found — run `lh2 hubspot-setup`")

    deals = hc.search_all(
        "deals",
        [{"propertyName": "dealstage", "operator": "IN", "values": list(stage_version)}],
        ["dealstage", "lh2_domain", "email_version_sent", "dealname"])

    stats = {"in_email_stages": len(deals), "would_send": 0, "sent": 0,
             "skipped_already_sent": 0, "skipped_no_contact": 0, "dry_run": dry_run,
             "preview": []}
    for d in deals:
        pr = d["properties"]
        version = stage_version.get(pr.get("dealstage"))
        if not version:
            continue
        if pr.get("email_version_sent") == version:      # already emailed this version
            stats["skipped_already_sent"] += 1
            continue
        domain = pr.get("lh2_domain")
        co = store.get_company(domain) if domain else None
        people = store.people_for(domain) if domain else []
        primary = people[0] if people else None
        if not (co and primary and primary.email):
            stats["skipped_no_contact"] += 1
            continue

        subj, body = render(EMAIL_TEMPLATES[version], _first_name(primary),
                            co.company_name, owner, calendly)
        if dry_run:
            stats["would_send"] += 1
            if len(stats["preview"]) < 5:
                stats["preview"].append(
                    {"version": version, "to": primary.email, "company": co.company_name, "subject": subj})
            continue

        send(primary.email, subj, body)
        props = {"email_version_sent": version}
        if version == "M1V1":
            props["calendly_link_sent"] = "true"
        hc._request("PATCH", f"/crm/v3/objects/deals/{d['id']}", {"properties": props})
        _log_email(hc, d["id"], primary.email, subj, body)
        stats["sent"] += 1
        log.info("outreach_sent", version=version, to=primary.email, company=co.company_name)
        if limit and stats["sent"] >= limit:
            break

    log.info("outreach_run", **{k: v for k, v in stats.items() if k != "preview"})
    return stats
