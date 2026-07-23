#!/usr/bin/env python3
"""CI-ready: pull the Scraped-pipeline dashboard data from HubSpot -> dashboard_data.json.

Reads the token from the HUBSPOT_API_KEY env var (a GitHub Actions secret in CI),
or falls back to `.env` (hubspot_key=...) for local runs. No other dependencies.
"""
import json, os, sys, urllib.request, urllib.error

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
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read().decode()
            return r.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

# stage id -> furthest funnel index (live = order; dead = where it died)
REACHED = {
    "3992480462":0,"3992480464":1,"3992480465":2,"3992480469":3,"3992480471":4,
    "3992480473":5,"4030231231":6,"4029653710":7,"3992480475":8,"4036632313":9,
    "4036633274":10,"4036632309":11,"4036632310":1,"4036687547":1,"4036632311":3,
    "4036687548":3,"4036687549":5,"4035313388":6,"4036632312":6}
WON = "4036632309"
DEAD = {"4036632310","4036687547","4036632311","4036687548","4036687549","4035313388","4036632312"}

PROPS = ["hubspot_owner_id","scraped_type","dealstage","createdate","hs_v2_date_entered_current_stage",
         "loc","pr_count","num_projects","num_repos","cost"]

def scan():
    out, after = [], None
    while True:
        b = {"limit":100,"properties":PROPS,
             "filterGroups":[{"filters":[{"propertyName":"pipeline","operator":"EQ","value":"default"}]}]}
        if after: b["after"] = after
        s, d = call("/crm/v3/objects/deals/search", "POST", b)
        if s != 200:
            sys.exit(f"HubSpot error {s}: {str(d)[:200]}")
        out += d.get("results", [])
        after = d.get("paging", {}).get("next", {}).get("after")
        if not after: return out

def num(p, k):
    v = p.get(k)
    try: return float(v) if v not in (None, "") else 0
    except: return 0

s, own = call("/crm/v3/owners?limit=100")
owners = {o["id"]: f"{o.get('firstName','')} {o.get('lastName','')}".strip() for o in own.get("results", [])}

rows = []
for r in scan():
    p = r["properties"]; oid = p.get("hubspot_owner_id"); st = p.get("dealstage")
    if not oid or st not in REACHED:
        continue
    rows.append({"o":oid, "t":p.get("scraped_type") or "Untagged", "c":(p.get("createdate") or "")[:10],
        "r":REACHED[st], "sd":(p.get("hs_v2_date_entered_current_stage") or "")[:10],
        "won":st==WON, "dead":st in DEAD,
        "loc":num(p,"loc"), "pr":num(p,"pr_count"), "pj":num(p,"num_projects"),
        "rp":num(p,"num_repos"), "cost":num(p,"cost")})

CORE = [("166420402","Shreyas Boosnoor"),("166322228","Ishpreet Sood"),("166262056","Shobit Gupta"),
        ("166483631","Yash Wani"),("166322218","Ashish Ranjan"),("95472647","Bhanu Enamala")]
out = {"generated": max((r["c"] for r in rows), default=""), "core": CORE, "rows": rows}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_data.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"wrote dashboard_data.json — {len(rows)} deals")
