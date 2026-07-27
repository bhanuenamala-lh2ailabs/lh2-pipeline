#!/usr/bin/env python3
"""CI-ready: pull the Scraped-pipeline dashboard data from HubSpot -> dashboard_data.json.

Uses each deal's STAGE-CHANGE HISTORY (for the funnel deals only) to get accurate,
date-stamped milestones: when a call was attempted, when interested, when a GMeet was
actually fixed. Deals sitting at Cold Call are skipped (no history call needed).

Token: HUBSPOT_API_KEY env (CI) or local .env (hubspot_key=...).
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

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

# stage ids (Scraped pipeline)
COLD="3992480462"; CALLATT="3992480464"; INTER="3992480465"; GMEET="3992480469"
SS="3992480471"; RRS="3992480473"; CN="4030231231"; DC="4029653710"; DMG="3992480475"
MDT="4036632313"; PI="4036633274"; WON="4036632309"
NEWLEAD="4002503379"; ASSIGNED="4018854632"  # legacy pre-migration stages
DEAD = {"4036632310","4036687547","4036632311","4036687548","4036687549","4035313388","4036632312"}
REACHED = {COLD:0,CALLATT:1,INTER:2,GMEET:3,SS:4,RRS:5,CN:6,DC:7,DMG:8,MDT:9,PI:10,WON:11,
    "4036632310":1,   # Dead/ColdCall/Not Interested = a call was made (picked up, said no)
    "4036687547":0,   # Dead/ColdCall/WrongFit = screened out from profile BEFORE dialing -> NOT a call
    "4061963984":2,   # Dead/Interested/NoShow = said interested, never made the gmeet -> level 2
    "4036632311":3,"4036687548":3,"4036687549":5,"4035313388":6,"4036632312":6}

PROPS = ["hubspot_owner_id","scraped_type","dealstage","createdate",
         "loc","pr_count","num_projects","num_repos","cost"]

def scan():
    out, after = [], None
    while True:
        b = {"limit":100,"properties":PROPS,
             "filterGroups":[{"filters":[{"propertyName":"pipeline","operator":"EQ","value":"default"}]}]}
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
for r in deals:
    p = r["properties"]; oid = p.get("hubspot_owner_id"); st = p.get("dealstage")
    if not oid or st not in REACHED:
        continue
    d = {"o":oid, "t":p.get("scraped_type") or "Untagged", "c":(p.get("createdate") or "")[:10],
         "r":REACHED[st], "won":st==WON, "dead":st in DEAD,
         "loc":num(p,"loc"), "pr":num(p,"pr_count"), "pj":num(p,"num_projects"),
         "rp":num(p,"num_repos"), "cost":num(p,"cost"),
         "att":None, "ind":None, "gm":None, "ss":None, "rr":None, "cn":None,
         "dc":None, "pi":None, "won_d":None}
    if st != COLD:
        funnel.append((len(rows), r["id"]))
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
        return min(ts)[:10] if ts else None      # earliest date it hit that milestone-or-beyond
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

CORE = [("166420402","Shreyas Boosnoor"),("166322228","Ishpreet Sood"),("166262056","Shobit Gupta"),
        ("166483631","Yash Wani"),("166322218","Ashish Ranjan"),("95472647","Bhanu Enamala")]
out = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "core": CORE, "rows": rows}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_data.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"wrote dashboard_data.json — {len(rows)} deals, {len(funnel)} with history")
