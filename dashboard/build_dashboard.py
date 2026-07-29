#!/usr/bin/env python3
"""CI-ready: pull the Scraped-pipeline dashboard data from HubSpot -> dashboard_data.json.

Uses each deal's STAGE-CHANGE HISTORY (for the funnel deals only) to get accurate,
date-stamped milestones: when a call was attempted, when interested, when a GMeet was
actually fixed. Deals sitting at Cold Call are skipped (no history call needed).

Token: HUBSPOT_API_KEY env (CI) or local .env (hubspot_key=...).
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
def ist_day(iso):
    """UTC ISO timestamp -> YYYY-MM-DD in IST (HubSpot's display zone)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).strftime("%Y-%m-%d")
    except Exception:
        return iso[:10]

def token():
    t = os.environ.get("HUBSPOT_API_KEY")
    if t:
        return t.strip()
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8-sig"):
            if line.lower().startswith("hubspot") and "=" in line:
                return line.split("=", 1)[1].strip()
    sys.exit("HUBSPOT_API_KEY not set (env or .env)")

TOK = token()

def call(path, method="GET", payload=None):
    url = path if path.startswith("http") else "https://api.hubapi.com" + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read().decode()
                return r.status, (json.loads(b) if b else {})
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2); continue
            return e.code, json.loads(e.read().decode() or "{}")
    return 429, {}

# ---- stage->level maps built dynamically from BOTH pipelines (same SOP cadence, different stage ids) ----
PIPELINES = {"default": "scraped", "2425754306": "campaign"}
LEVEL = {"Cold Call":0,"Call Attempted":1,"Interested":2,"GMeet Fixed":3,"Script Shared":4,
    "Script Results Received":5,"Commercial Negotiation":6,"Deal Contract Signed":7,
    "Data Migration Done":8,"Metadata Matched":9,"Payment Initiation":10,"Closed/Won":11}
DEAD_LEVEL = {"Dead/ColdCall/Not Interested":1,"Dead/ColdCall/WrongFit":0,"Dead/Interested/NoShow":2,
    "Dead/GMeet/wrong fit":3,"Dead/Gmeet/Privacy Concerns":3,"Dead/ResultsReceived/WrongFit-Rejected":5,
    "Dead/Negotiation/Pricing":6,"Dead/Negotiation/Contractual":6}
REACHED = {}; DEAD = set(); WON_IDS = set(); COLD_IDS = set()
for _pid in PIPELINES:
    _s, _pp = call(f"/crm/v3/pipelines/deals/{_pid}")
    for st in _pp.get("stages", []):
        sid, lab = st["id"], st["label"]
        if lab in LEVEL:
            REACHED[sid] = LEVEL[lab]
            if lab == "Closed/Won": WON_IDS.add(sid)
            if lab == "Cold Call": COLD_IDS.add(sid)
        elif lab in DEAD_LEVEL:
            REACHED[sid] = DEAD_LEVEL[lab]; DEAD.add(sid)

def bucket_ls(ls):
    ls = (ls or "").lower()
    if "indonesia" in ls: return "Indonesia"
    if "india" in ls: return "India"
    return None

PROPS = ["hubspot_owner_id","scraped_type","lead_source","pipeline","dealstage","createdate","dealname",
         "metadata_link","deal_value_range","loc","pr_count","num_projects","num_repos","cost"]

def scan():
    out, after = [], None
    while True:
        b = {"limit":100,"properties":PROPS,
             "filterGroups":[{"filters":[{"propertyName":"pipeline","operator":"IN","values":list(PIPELINES)}]}]}
        if after: b["after"] = after
        s, d = call("/crm/v3/objects/deals/search", "POST", b)
        if s != 200: sys.exit(f"HubSpot error {s}: {str(d)[:200]}")
        out += d.get("results", [])
        after = d.get("paging", {}).get("next", {}).get("after")
        if not after: return out

def num(p, k):
    v = p.get(k)
    try: return float(v) if v not in (None, "") else 0
    except: return 0

s, own = call("/crm/v3/owners?limit=100")
owners = {o["id"]: f"{o.get('firstName','')} {o.get('lastName','')}".strip() for o in own.get("results", [])}

deals = scan()
rows = []
funnel = []   # (index, deal_id) needing history
hotnote = []  # (index, deal_id) for metric-bearing / won deals -> fetch note
for r in deals:
    p = r["properties"]; oid = p.get("hubspot_owner_id"); st = p.get("dealstage")
    if not oid or st not in REACHED:
        continue
    d = {"o":oid, "pl":PIPELINES.get(p.get("pipeline"), "scraped"),
         "t":p.get("scraped_type") or bucket_ls(p.get("lead_source")) or "Untagged", "c":ist_day(p.get("createdate")),
         "r":REACHED[st], "cc":st in COLD_IDS, "won":st in WON_IDS, "dead":st in DEAD,
         "nm":p.get("dealname") or "", "ml":p.get("metadata_link") or "", "dvr":p.get("deal_value_range") or "",
         "loc":num(p,"loc"), "pr":num(p,"pr_count"), "pj":num(p,"num_projects"),
         "rp":num(p,"num_repos"), "cost":num(p,"cost"),
         "att":None, "ind":None, "gm":None, "ss":None, "rr":None, "cn":None,
         "dc":None, "pi":None, "won_d":None}
    if st not in COLD_IDS:
        funnel.append((len(rows), r["id"]))
    if d["r"] >= 5 or d["won"]:   # Script Results Received or beyond (even if metadata missing)
        hotnote.append((len(rows), r["id"]))
    rows.append(d)

print(f"{len(rows)} deals | fetching stage history for {len(funnel)} funnel deals...", file=sys.stderr)

for i, (idx, did) in enumerate(funnel):
    s, h = call(f"/crm/v3/objects/deals/{did}?propertiesWithHistory=dealstage")
    entries = h.get("propertiesWithHistory", {}).get("dealstage", []) if s == 200 else []
    # (reached-level, timestamp) for every stage this deal ever entered.
    # A deal counts toward a milestone if it EVER reached that stage OR BEYOND
    # (incl. dying at/after it, e.g. Dead/GMeet/* == reached the GMeet milestone).
    evs = [(REACHED.get(e.get("value"), 0), e.get("timestamp")) for e in entries if e.get("timestamp")]
    def first_at(thr):
        ts = [t for lvl, t in evs if lvl >= thr]
        return ist_day(min(ts)) if ts else None  # earliest date (IST) it hit that milestone-or-beyond
    d = rows[idx]
    cur = d["r"]             # current furthest stage; only credit milestones it currently sits at/beyond
    d["att"] = first_at(1) if cur >= 1 else None   # reached Call Attempted or beyond
    d["ind"] = first_at(2) if cur >= 2 else None   # reached Interested or beyond
    d["gm"]  = first_at(3) if cur >= 3 else None   # reached GMeet or beyond == a gmeet was fixed
    d["ss"]  = first_at(4) if cur >= 4 else None   # reached Script Shared or beyond
    d["rr"]  = first_at(5) if cur >= 5 else None   # reached Script Results or beyond
    d["cn"]  = first_at(6) if cur >= 6 else None   # reached Commercial Negotiation or beyond
    d["dc"]  = first_at(7) if cur >= 7 else None   # reached Deal Contract Signed or beyond
    d["pi"]  = first_at(10) if cur >= 10 else None # reached Payment Initiation or beyond
    d["won_d"] = first_at(11) if cur >= 11 else None  # reached Closed/Won
    if (i+1) % 50 == 0: print(f"  {i+1}/{len(funnel)}", file=sys.stderr)

import re as _re, html as _html
print(f"fetching notes for {len(hotnote)} hot/won deals...", file=sys.stderr)
for idx, did in hotnote:
    s, a = call(f"/crm/v4/objects/deals/{did}/associations/notes")
    nids = [str(x["toObjectId"]) for x in a.get("results", [])] if s == 200 else []
    body = ""
    if nids:
        s, nb = call("/crm/v3/objects/notes/batch/read", "POST",
                     {"properties": ["hs_note_body", "hs_timestamp"], "inputs": [{"id": n} for n in nids]})
        notes = nb.get("results", []) if s == 200 else []
        notes.sort(key=lambda x: x["properties"].get("hs_timestamp", ""), reverse=True)
        for n in notes:
            raw = n["properties"].get("hs_note_body", "") or ""
            raw = _re.sub("(?i)<br\\s*/?>", "\n", raw)
            raw = _html.unescape(_re.sub("<[^>]+>", "", raw))
            if raw.strip(): body = raw; break
    # surface the actual Remarks line, not the migration boilerplate
    note = ""
    for line in [l.strip() for l in body.split("\n") if l.strip()]:
        if line.lower().startswith("remarks:"):
            note = line.split(":", 1)[1].strip(); break
    if not note:
        skip = ("[pipeline tracker", "sheet stage", "category:", "priority:", "metadata:",
                "script output:", "last update:", "status (", "(phase-2")
        keep = [l.strip() for l in body.split("\n") if l.strip() and not l.strip().lower().startswith(skip)]
        note = " · ".join(keep)
    rows[idx]["note"] = note[:260]

CORE = [("166420402","Shreyas Boosnoor"),("166322228","Ishpreet Sood"),("166262056","Shobit Gupta"),
        ("166483631","Yash Wani"),("166322218","Ashish Ranjan"),("95472647","Bhanu Enamala")]
out = {"generated": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"), "core": CORE, "rows": rows}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_data.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"wrote dashboard_data.json — {len(rows)} deals, {len(funnel)} with history")
