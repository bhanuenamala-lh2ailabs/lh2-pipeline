"""Phase 5d tests — automated outreach, fully offline (injected SMTP + responder).
Covers template rendering, stage-triggered selection, idempotency (already-sent
skipped), missing-contact skip, deal-property update, and dry-run."""

from __future__ import annotations

from lh2_pipeline.export.hubspot_client import HubspotClient
from lh2_pipeline.export.hubspot_emails import render, run_send_emails
from lh2_pipeline.export.hubspot_setup import EMAIL_TEMPLATES
from lh2_pipeline.models import Company, Person
from lh2_pipeline.store import Store

STAGES = {"results": [{"id": "pipe1", "label": "Codebase Acquisition", "stages": [
    {"id": "s-m1v1", "label": "M1V1 Sent"},
    {"id": "s-m1v2", "label": "M1V2 Sent"},
    {"id": "s-new", "label": "New Lead"},
]}]}


class _OC:
    enabled = True
    smtp_host = "smtp.test"; smtp_port = 587
    from_name = "Bhanu"; from_email = ""
    calendly_link = "https://calendly.com/bhanu/15min"


class _Sec:
    hubspot_api_key = "tok"; smtp_user = "bhanu@lh2.ai"; smtp_password = "pw"


class FakeCfg:
    outreach = _OC(); secrets = _Sec()


def _store(tmp_path):
    s = Store(tmp_path / "e.sqlite"); s.init_db()
    s.upsert_company(Company(domain="acme.com", company_name="Acme Labs", gate_pass=True))
    s.upsert_person(Person(domain="acme.com", name="Asha Rao", is_primary=True,
                           email="asha@acme.com", phone="+91", linkedin_url="x"))
    return s


def test_render_fills_all_placeholders():
    subj, body = render(EMAIL_TEMPLATES["M1V1"], "Asha", "Acme Labs", "Bhanu",
                        "https://calendly.com/x")
    assert subj == "Following Up - LH2 Data Labs x Acme Labs"
    assert "Hi Asha," in body
    assert "Acme Labs" in body and "Bhanu" in body
    assert "https://calendly.com/x" in body
    assert "[CALENDLY_LINK]" not in body and "{{" not in body


def _responder_factory(deals, patched):
    def responder(method, path, json):
        if path == "/crm/v3/pipelines/deals":
            return 200, STAGES
        if path.endswith("/deals/search"):
            return 200, {"results": deals}
        if method == "PATCH" and "/deals/" in path:
            patched.append((path, json["properties"]))
            return 200, {}
        if path.endswith("/emails"):                 # timeline logging
            return 201, {"id": "em1"}
        if path.endswith("/contacts/search"):
            return 200, {"results": [{"id": "ct1", "properties": {"email": "asha@acme.com"}}]}
        if "associate/default" in path:
            return 201, {}
        raise AssertionError(f"unexpected {method} {path}")
    return responder


def test_send_emails_sends_and_marks_deal(tmp_path):
    s = _store(tmp_path)
    sent, patched = [], []
    deals = [{"id": "D1", "properties": {"dealstage": "s-m1v1", "lh2_domain": "acme.com",
                                         "email_version_sent": "None", "dealname": "Acme Labs - ..."}}]
    stats = run_send_emails(FakeCfg(), s, client=HubspotClient(responder=_responder_factory(deals, patched)),
                            sender=lambda to, subj, body: sent.append((to, subj, body)))
    assert stats["sent"] == 1
    to, subj, body = sent[0]
    assert to == "asha@acme.com" and "Acme Labs" in subj and "Hi Asha," in body
    # deal marked so it never re-sends, and calendly flagged
    assert patched[0][1] == {"email_version_sent": "M1V1", "calendly_link_sent": "true"}
    s.close()


def test_send_emails_is_idempotent(tmp_path):
    s = _store(tmp_path)
    sent = []
    deals = [{"id": "D1", "properties": {"dealstage": "s-m1v1", "lh2_domain": "acme.com",
                                         "email_version_sent": "M1V1", "dealname": "x"}}]
    stats = run_send_emails(FakeCfg(), s, client=HubspotClient(responder=_responder_factory(deals, [])),
                            sender=lambda *a: sent.append(a))
    assert stats["sent"] == 0 and stats["skipped_already_sent"] == 1 and sent == []
    s.close()


def test_send_emails_skips_missing_contact(tmp_path):
    s = _store(tmp_path)                              # no company for 'ghost.com'
    deals = [{"id": "D1", "properties": {"dealstage": "s-m1v2", "lh2_domain": "ghost.com",
                                         "email_version_sent": "None", "dealname": "x"}}]
    stats = run_send_emails(FakeCfg(), s, client=HubspotClient(responder=_responder_factory(deals, [])),
                            sender=lambda *a: (_ for _ in ()).throw(AssertionError("must not send")))
    assert stats["sent"] == 0 and stats["skipped_no_contact"] == 1
    s.close()


def test_send_emails_dry_run_sends_nothing(tmp_path):
    s = _store(tmp_path)
    deals = [{"id": "D1", "properties": {"dealstage": "s-m1v1", "lh2_domain": "acme.com",
                                         "email_version_sent": "None", "dealname": "x"}}]
    def responder(method, path, json):
        if path == "/crm/v3/pipelines/deals":
            return 200, STAGES
        if path.endswith("/deals/search"):
            return 200, {"results": deals}
        raise AssertionError("dry-run must only read pipeline + search")
    stats = run_send_emails(FakeCfg(), s, client=HubspotClient(responder=responder), dry_run=True)
    assert stats["would_send"] == 1 and stats["sent"] == 0
    assert stats["preview"][0]["to"] == "asha@acme.com"
    s.close()
