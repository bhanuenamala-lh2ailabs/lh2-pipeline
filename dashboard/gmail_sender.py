# -*- coding: utf-8 -*-
"""Email sender for LH2 automation. Resolves the first working transport, in this order:

  1. gmail_oauth   — OAuth 2.0 desktop client + stored refresh token.  NO admin needed.
                     One browser consent ever (`python gmail_sender.py --auth`), after which
                     it sends unattended forever as the consenting user.
  2. gmail_sa      — the lh2-pipeline service account impersonating a mailbox. Only works
                     once a Workspace super-admin enables DOMAIN-WIDE DELEGATION for client
                     id 100170198106213149801 with scope .../auth/gmail.send.
                     Verified 2026-08-04: currently returns `unauthorized_client`.
  3. smtp          — SMTP_HOST / SMTP_USER / SMTP_PASSWORD in .env (Gmail app password).
  4. outbox        — writes the message + attachment to disk so nothing is ever lost.

A service account has no mailbox of its own, so path 2 is impersonation or nothing.

Usage:
  python gmail_sender.py --auth              one-time browser consent -> gmail_token.json
  python gmail_sender.py --check             report which transport is live
  python gmail_sender.py --test you@lh2.ai   send a real test message
"""
import os, sys, json, base64, smtplib, mimetypes
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__)); HUB = os.path.dirname(os.path.dirname(HERE))
# CI writes the credentials next to this file; locally they already live there.
TOKEN = next((p for p in (os.path.join(HERE, "gmail_token.json"),
                          os.path.join(HUB,  "gmail_token.json"))
              if os.path.exists(p)), os.path.join(HERE, "gmail_token.json"))
def _find_client():
    """The Cloud Console downloads as client_secret_<id>.json — accept that name as-is
    rather than making anyone rename a credential file."""
    import glob
    for base in (HERE, HUB):
        p = os.path.join(base, "gmail_oauth_client.json")
        if os.path.exists(p): return p
        hits = sorted(glob.glob(os.path.join(base, "client_secret_*.json")))
        if hits: return hits[0]
    return os.path.join(HUB, "gmail_oauth_client.json")
CLIENT = _find_client()
OUTBOX = os.path.join(HUB, "crm_mirror", "vcf_outbox")
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
SA_KEY = os.path.join(HUB, "lh2-pipeline-9982aa4422f5.json")
def _load_env():
    """.env is a local convenience and does not exist in CI. Missing is normal, not an error."""
    for base in (HUB, HERE):
        p = os.path.join(base, '.env')
        if os.path.exists(p):
            return {l.split('=', 1)[0].strip().lower(): l.split('=', 1)[1].strip()
                    for l in open(p, encoding='utf-8-sig')
                    if '=' in l and not l.strip().startswith('#')}
    return {}
env = _load_env()
IMPERSONATE = (os.environ.get("GMAIL_SEND_AS")
               or env.get("gmail_send_as", "bhanu.enamala@lh2.ai"))   # the account that consented


def build_message(to_addr, subject, body, attachments=(), sender=None, html=None):
    """attachments: [(filename, bytes, 'text/vcard'), ...]

    `html` adds an HTML alternative. The plain-text `body` stays as the fallback, so a client
    that will not render HTML still shows something readable rather than an empty message.
    """
    m = EmailMessage()
    m["To"] = to_addr; m["Subject"] = subject
    if sender: m["From"] = sender
    m.set_content(body)
    if html: m.add_alternative(html, subtype="html")
    for fn, data, ctype in attachments:
        maintype, _, subtype = (ctype or mimetypes.guess_type(fn)[0] or
                                "application/octet-stream").partition("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=fn)
    return m


# ---------------------------------------------------------------- transports
def _oauth_creds():
    if not os.path.exists(TOKEN): return None
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    c = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
        open(TOKEN, "w", encoding="utf-8").write(c.to_json())
    return c if c and c.valid else None


def _sa_creds():
    if not os.path.exists(SA_KEY): return None
    try:
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(
            SA_KEY, scopes=SCOPES).with_subject(IMPERSONATE)
    except Exception:
        return None


def _gmail_send(creds, msg):
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return svc.users().messages().send(userId="me", body={"raw": raw}).execute()


def authorize():
    """One-time browser consent. Needs gmail_oauth_client.json next to .env."""
    if not os.path.exists(CLIENT):
        print(f"Missing {CLIENT}\n\nCreate it once:\n"
              "  1. console.cloud.google.com -> project 'lh2-pipeline'\n"
              "  2. APIs & Services -> Library -> enable 'Gmail API'\n"
              "  3. APIs & Services -> Credentials -> Create credentials -> OAuth client ID\n"
              "     Application type: Desktop app\n"
              "  4. Download JSON, save it as the path above\n"
              "  (If asked to configure the consent screen: type Internal, add scope\n"
              "   .../auth/gmail.send, add yourself as a test user.)")
        return False
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    open(TOKEN, "w", encoding="utf-8").write(creds.to_json())
    print(f"authorised — refresh token stored at {TOKEN}\nThis machine can now send unattended.")
    return True


def transport():
    """-> name of the transport that would be used right now."""
    if _oauth_creds(): return "gmail_oauth"
    c = _sa_creds()
    if c:
        try:
            from google.auth.transport.requests import Request
            c.refresh(Request()); return "gmail_sa"
        except Exception: pass
    if env.get("smtp_host") and env.get("smtp_user") and env.get("smtp_password"): return "smtp"
    return "outbox"


def send(to_addr, subject, body, attachments=(), dry=False, html=None):
    """-> (transport_used, detail). Never raises: falls through to the outbox."""
    if dry or transport() == "outbox":
        os.makedirs(OUTBOX, exist_ok=True)
        for fn, data, _ in attachments:
            open(os.path.join(OUTBOX, fn), "wb").write(data)
        stem = attachments[0][0].rsplit(".", 1)[0] if attachments else "message"
        open(os.path.join(OUTBOX, stem + ".txt"), "w", encoding="utf-8").write(
            f"TO: {to_addr}\nSUBJECT: {subject}\n\n{body}")
        return ("dry-run" if dry else "outbox"), os.path.join(OUTBOX, stem + ".txt")

    t = transport()
    try:
        if t == "gmail_oauth":
            r = _gmail_send(_oauth_creds(), build_message(to_addr, subject, body, attachments, html=html))
            return t, r.get("id", "sent")
        if t == "gmail_sa":
            r = _gmail_send(_sa_creds(),
                            build_message(to_addr, subject, body, attachments, sender=IMPERSONATE, html=html))
            return t, r.get("id", "sent")
        if t == "smtp":
            user = env["smtp_user"]
            msg = build_message(to_addr, subject, body, attachments, sender=user)
            with smtplib.SMTP(env["smtp_host"], int(env.get("smtp_port", 587)), timeout=30) as s:
                s.starttls(); s.login(user, env["smtp_password"]); s.send_message(msg)
            return t, "sent"
    except Exception as e:
        os.makedirs(OUTBOX, exist_ok=True)
        for fn, data, _ in attachments:
            open(os.path.join(OUTBOX, fn), "wb").write(data)
        return "outbox", f"{t} FAILED ({type(e).__name__}: {str(e)[:180]}) — saved to outbox"
    return "outbox", "no transport"


if __name__ == "__main__":
    if "--auth" in sys.argv:
        authorize(); sys.exit()
    t = transport()
    print(f"active transport: {t}")
    print(f"  gmail_oauth  token file  : {'present' if os.path.exists(TOKEN) else 'MISSING (run --auth)'}")
    print(f"  gmail_oauth  client file : {'present' if os.path.exists(CLIENT) else 'MISSING'}")
    c = _sa_creds()
    if c:
        try:
            from google.auth.transport.requests import Request
            c.refresh(Request()); print(f"  gmail_sa     : OK, impersonating {IMPERSONATE}")
        except Exception as e:
            print(f"  gmail_sa     : unavailable — {str(e)[:120]}")
    print(f"  smtp         : {'configured' if env.get('smtp_host') else 'not configured'}")
    if "--test" in sys.argv:
        to = sys.argv[sys.argv.index("--test") + 1]
        vcf = ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:Test;LH2;;;\r\nFN:LH2 Test\r\n"
               "ORG:LH2 AI Labs\r\nTEL;TYPE=CELL,VOICE:+919999999999\r\nEND:VCARD")
        print(send(to, "LH2 vCard transport test",
                   "If you can open the attached contact, the notifier is ready.",
                   [("lh2_test.vcf", vcf.encode(), "text/vcard")]))
