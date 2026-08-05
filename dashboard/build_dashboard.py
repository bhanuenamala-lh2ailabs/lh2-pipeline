#!/usr/bin/env python3
"""CI-ready: pull BOTH deal pipelines from HubSpot -> dashboard_data.json.

Every metric is a count of TIMES A DEAL ENTERED a qualifying stage, on the day it entered,
read from each deal's stage-change history. Only human moves (sourceType == CRM_UI) count;
activity is credited to whoever made the move, assignment to whoever received the deal.

Full specification: docs/sop/DASHBOARD_METRIC_SPEC.md

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

# ---- both pipelines, treated as one ----
# Scraped and Campaign carry identical stage labels in identical order; only the internal
# ids differ. Nothing is scoped by pipeline any more — every count is both, combined.
PIPELINES = {"default": "scraped", "2425754306": "campaign"}

# A metric is the set of stages that, when a deal ENTERS one, means the thing happened.
# Not a level threshold: `Dead/ColdCall/Not Interested` and `Dead/ColdCall/WrongNumber`
# would sit at the same level, yet one means a human answered and the other means the
# number was junk. "Calls connected" needs to separate exactly those two, so membership
# has to be explicit.
METRICS = {
    # --- GTM analyst ---
    # WrongFit is absent on purpose: that lead was screened out and never dialled.
    "att":  {"No Pickup", "Dead/ColdCall/WrongNumber", "Dead/ColdCall/Not Interested",
             "Dead/ColdCall/NoPickup", "Interested"},
    "conn": {"Dead/ColdCall/Not Interested", "Interested"},
    "gm":   {"GMeet Fixed"},
    # --- lead manager ---
    # Cancelled is absent on purpose: called off in advance, so no time was spent sitting in it.
    "vc":   {"Dead/GMeet/NoShow", "Dead/GMeet/wrong fit", "Dead/GMeet/Privacy Concerns",
             "Script Shared"},
    "ss":   {"Script Shared"},
    "rr":   {"Script Results Received"},
    "ev":   {"Dead/ResultsReceived/WrongFit-Rejected", "Commercial Negotiation"},
    "cn":   {"Commercial Negotiation"},
    # --- lead closer ---  ("ev" is shown on this panel too, deliberately: both pods do it)
    "neg":  {"Dead/Negotiation/Pricing", "Dead/Negotiation/Contractual", "Deal Contract Signed"},
    # Contract signings on their own. `neg` counts negotiation CALLS, which includes the two
    # ways a negotiation dies — so it can never answer "how many did we sign".
    "dcs":  {"Deal Contract Signed"},
    "won_d": {"Closed/Won"},
}
# `Call Attempted` was retired on 2026-08-05 and its deals moved to `No Pickup`, but it
# stays in the history of ~100 deals. Treat it as No Pickup so the series before that date
# does not fall off a cliff.
ALIAS = {"Call Attempted": "No Pickup", "Call Attempted (retired)": "No Pickup",
         "Dead/Gmeet/Privacy Concerns": "Dead/GMeet/Privacy Concerns"}

STAGE_LABEL = {}          # stage id -> canonical label, across both pipelines
WON_IDS = set(); COLD_IDS = set(); DEAD = set(); ORDER = {}
_SEQ = ["Cold Call","No Pickup","Interested","GMeet Fixed","Script Shared",
        "Script Results Received","Commercial Negotiation","Deal Contract Signed",
        "Data Migration Done","Metadata Matched","Payment Initiation","Closed/Won"]
# How far a deal got before it died. A dead stage is not "off the end of the funnel" — it
# marks the point the deal reached, so Dead/GMeet/* means it got as far as the GMeet.
# Without this every dead deal sorts as 99 and the Hot & Won table fills with them.
_DEAD_SEQ = {"Dead/ColdCall/WrongFit":0,          # screened out, never dialled
             "Dead/ColdCall/Not Interested":1, "Dead/ColdCall/WrongNumber":1,
             "Dead/ColdCall/NoPickup":1,
             "Dead/Interested/NoShow":2,
             "Dead/GMeet/NoShow":3, "Dead/GMeet/Cancelled":3,
             "Dead/GMeet/wrong fit":3, "Dead/GMeet/Privacy Concerns":3,
             "Dead/ScriptShared/NoShow":4,
             "Dead/ResultsReceived/WrongFit-Rejected":5,
             "Dead/Negotiation/Pricing":6, "Dead/Negotiation/Contractual":6}
for _pid in PIPELINES:
    _s, _pp = call(f"/crm/v3/pipelines/deals/{_pid}")
    for st in _pp.get("stages", []):
        sid, lab = st["id"], ALIAS.get(st["label"], st["label"])
        STAGE_LABEL[sid] = lab
        if str(st["metadata"].get("isClosed")).lower() == "true": DEAD.add(sid)
        if lab == "Closed/Won": WON_IDS.add(sid); DEAD.discard(sid)
        if lab == "Cold Call": COLD_IDS.add(sid)
        ORDER[sid] = _SEQ.index(lab) if lab in _SEQ else _DEAD_SEQ.get(lab, 0)

def metrics_for(label):
    """which metric keys does entering this stage satisfy"""
    return [k for k, s in METRICS.items() if label in s]

# Stage history identifies the actor by USER id; deals identify people by OWNER id. They are
# separate namespaces in HubSpot and only coincide by luck, so map them explicitly.
#
# Why the actor matters: a GTM analyst logs GMeet Fixed and hands the deal over in the same
# action, so by build time the deal belongs to the Lead Manager. Crediting activity to the
# CURRENT owner would take that GMeet off the analyst who booked it — and the better the
# handoff discipline, the more work gets misattributed. Assignment metrics stay owner-based
# (they really are about who received the deal); activity metrics follow the actor.
_s, _ow0 = call("/crm/v3/owners?limit=200")
USER2OWNER = {str(o["userId"]): o["id"]
              for o in (_ow0.get("results") or []) if o.get("userId")}
def actor_owner(uid):
    if uid is None: return ""
    return USER2OWNER.get(str(uid), str(uid))

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
    if not oid or st not in STAGE_LABEL:
        continue
    d = {"o":oid, "pl":PIPELINES.get(p.get("pipeline"), "scraped"),
         "t":p.get("scraped_type") or bucket_ls(p.get("lead_source")) or "Untagged",
         "c":ist_day(p.get("createdate")),
         "r":ORDER[st], "sl":STAGE_LABEL[st],
         "cc":st in COLD_IDS, "won":st in WON_IDS, "dead":st in DEAD,
         "nm":p.get("dealname") or "", "ml":p.get("metadata_link") or "",
         "dvr":p.get("deal_value_range") or "",
         "loc":num(p,"loc"), "pr":num(p,"pr_count"), "pj":num(p,"num_projects"),
         "rp":num(p,"num_repos"), "cost":num(p,"cost"),
         # per-metric list of IST days on which this deal ENTERED a qualifying stage.
         # A list, not a single date: under the callback loop a deal legitimately hits the
         # calling stages twice (No Pickup Monday, Not Interested Tuesday) and both are real
         # dials. Keeping only the first would make the whole callback loop invisible.
         "m": {k: [] for k in METRICS},
         "asg": [],                      # IST days this deal was assigned to its owner
         "won_any": []}                  # IST days it hit Closed/Won, ANY source (sprint LoC)
    funnel.append((len(rows), r["id"]))   # every deal needs history now, incl. Cold Call
    if d["r"] >= 5 or d["won"]:
        hotnote.append((len(rows), r["id"]))
    rows.append(d)

print(f"{len(rows)} deals | fetching stage history for {len(funnel)} funnel deals...", file=sys.stderr)

for i, (idx, did) in enumerate(funnel):
    s, h = call(f"/crm/v3/objects/deals/{did}"
                "?propertiesWithHistory=dealstage,hubspot_owner_id")
    hist = h.get("propertiesWithHistory", {}) if s == 200 else {}
    d = rows[idx]

    # ONLY human moves count. ~42% of stage-history entries are sourceType=INTEGRATION —
    # bulk API writes, including our own migration of 245 deals. Counting those would have
    # rendered that migration as the biggest calling day the company has ever had.
    for e in hist.get("dealstage", []):
        if not e.get("timestamp"):
            continue
        lab = STAGE_LABEL.get(e.get("value"))
        if not lab:                     # a stage that has since been deleted — skip, don't guess
            continue
        # Procurement is a fact about the ASSET, not about who moved the deal. A codebase we
        # won is ours whether a person clicked the stage or a script set it, so the sprint
        # LoC total ignores sourceType. Activity metrics below do not — see the filter.
        if lab == "Closed/Won":
            wd = ist_day(e["timestamp"])
            if wd not in d["won_any"]: d["won_any"].append(wd)
        if e.get("sourceType") != "CRM_UI":
            continue
        day = ist_day(e["timestamp"])
        who = actor_owner(e.get("updatedByUserId"))
        for k in metrics_for(lab):
            ev = [day, who]
            if ev not in d["m"][k]:     # same stage, same person, same day is one event
                d["m"][k].append(ev)

    # assignment is an OWNER change, not a stage change. createdate was the old proxy and it
    # is wrong the moment a lead is reassigned.
    for e in hist.get("hubspot_owner_id", []):
        if e.get("value") == d["o"] and e.get("timestamp"):
            day = ist_day(e["timestamp"])
            if day not in d["asg"]: d["asg"].append(day)
    if not d["asg"] and d["c"]:
        d["asg"].append(d["c"])         # never reassigned — creation is when they got it

    if (i+1) % 100 == 0: print(f"  {i+1}/{len(funnel)}", file=sys.stderr)

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

# Team list for the member dropdown. Pulled LIVE from HubSpot owners rather than hardcoded —
# the old fixed list silently omitted Yuktha and Lamiya for their whole first week, so every
# per-member view was blind to them. Anyone added in HubSpot now shows up automatically.
# PREFERRED fixes the order for people we already know; newcomers append alphabetically, so
# the dropdown never reshuffles under someone mid-session.
PREFERRED = ["166420402", "166322228", "166262056", "166483631", "96574824", "96573782",
             "166322218", "95472647"]
_s, _ow = call("/crm/v3/owners?limit=200")
_all = [(o["id"], f'{o.get("firstName","")} {o.get("lastName","")}'.strip())
        for o in (_ow.get("results") or []) if o.get("id")]
_byid = dict(_all)
CORE = [(i, _byid[i]) for i in PREFERRED if i in _byid]
CORE += sorted([(i, n) for i, n in _all if i not in PREFERRED], key=lambda x: x[1])
print(f"dashboard members: {len(CORE)} -> {[n for _, n in CORE]}", file=sys.stderr)
out = {"generated": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"), "core": CORE, "rows": rows}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_data.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"wrote dashboard_data.json — {len(rows)} deals, {len(funnel)} with history")
