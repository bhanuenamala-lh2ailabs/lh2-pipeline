# -*- coding: utf-8 -*-
"""Daily 18:30 IST report to the Supply Head — the three tracker tables, filled from HubSpot.

Reads dashboard_data.json, which the dashboard build already produces from live HubSpot, so
the email and the dashboard can never disagree. Run the build first if you want it fresh.

Metric definitions are exactly the dashboard's — see docs/sop/DASHBOARD_METRIC_SPEC.md.

Usage:
  python daily_report.py                      write the HTML to disk, send nothing
  python daily_report.py --send               send it to the Supply Head
  python daily_report.py --send --test        send to the test mailbox instead
  python daily_report.py --date 2026-08-05    report as if it were that day
"""
import os, sys, json, html, datetime

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
HUB = os.path.dirname(ROOT)
sys.path.insert(0, HERE)
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

# Next to this file when deployed (CI copies it there), else the repo root locally.
DATA = next((p for p in (os.path.join(HERE, "dashboard_data.json"),
                         os.path.join(HUB,  "dashboard_data.json"))
             if os.path.exists(p)), os.path.join(HUB, "dashboard_data.json"))
OUT  = os.path.join(HERE, "daily_report.html")
TO      = "shobit.gupta@lh2.ai"      # the real recipient
TEST_TO = "bhanu.enamala@lh2.ai"     # every test send goes here, never to the team
IST  = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------- the tracker, as written
# One entry PER PERSON. Yuktha and Lamiya are listed separately: the quota is written per
# team member, so merging them hides which of the two is actually hitting it.
ROLES = [
    ("GTM Analyst", "Yuktha", "96573782",
     "Moving the funnel from introductory calls to the first VC",
     [("# of calls attempted", "att"), ("# of calls connected", "conn")],
     [("# of VCs setup", "gm")]),
    ("GTM Analyst", "Lamiya", "96574824",
     "Moving the funnel from introductory calls to the first VC",
     [("# of calls attempted", "att"), ("# of calls connected", "conn")],
     [("# of VCs setup", "gm")]),
    ("Pod Lead", "Ishpreet", "166322228",
     "Moving the funnel from VC to negotiation stage",
     [("# of VCs attended", "vc"), ("# of scripts shared", "ss")],
     [("# of scripts output received", "rr"),
      ("# of script output evaluation conducted", "ev"),
      ("# of deals moved to negotiation stage", "cn")]),
    ("Pod Head", "Shobit", "166262056",
     "Moving the funnel from negotiation to deal closure",
     [("# of script output evaluation conducted", "ev"),
      ("# of deal negotiation calls conducted", "neg")],
     [("# of deals closed", "won_d")]),
]

# Per person, so the target is the individual quota — no team multiplier.
TARGETS = [
    ("Yuktha", "96573782", "Daily",
     [("40 connected calls", "conn", 40, "daily"),
      ("At least 5 VCs set up", "gm", 5, "daily")]),
    ("Lamiya", "96574824", "Daily",
     [("40 connected calls", "conn", 40, "daily"),
      ("At least 5 VCs set up", "gm", 5, "daily")]),
    ("Ishpreet", "166322228", "Weekly",
     [("40 VCs attended",           "vc", 40, "weekly"),
      ("25 script shared",          "ss", 25, "weekly"),
      ("15 script output received", "rr", 15, "weekly")]),
]
SPRINT = [(1, "27th Jul - 31st Jul", "2026-07-27", "2026-07-31", 40),
          (2, "3rd Aug - 7th Aug",   "2026-08-03", "2026-08-07", 60),
          (3, "10th Aug - 14th Aug", "2026-08-10", "2026-08-14", 80),
          (4, "17th Aug - 21st Aug", "2026-08-17", "2026-08-21", 100),
          (5, "23rd Aug - 28th Aug", "2026-08-23", "2026-08-28", 120)]

# ---------------------------------------------------------------- counting
d = json.load(open(DATA, encoding="utf-8"))
rows = d["rows"]
# --date lets a past day be re-reported: useful for verifying the numbers against a day
# that actually had activity, rather than a day that has barely started.
if "--date" in sys.argv:
    today = datetime.date.fromisoformat(sys.argv[sys.argv.index("--date") + 1])
else:
    today = datetime.datetime.now(IST).date()

# The report is only as fresh as the file it reads. A stale file does not error — it quietly
# reports ZERO for every one of today's metrics, which reads as "the team did nothing today"
# rather than "this data predates today". Refuse to send that.
# Data must cover the day being reported. Reporting a PAST day from newer data is fine —
# the events are already in there. Only a file OLDER than the reported day is a problem.
GEN = (d.get("generated") or "")[:10]
STALE = GEN < today.isoformat()
if STALE:
    print(f"!! dashboard_data.json was generated {GEN or 'unknown'}, today is {today}.")
    print("   Every 'today' figure below would be 0 because the file predates today.")
    print("   Run build_dashboard.py first. Sending is blocked unless --force is passed.")
monday = today - datetime.timedelta(days=today.weekday())
DAY = today.isoformat()
WK_FROM, WK_TO = monday.isoformat(), today.isoformat()

def count(metric, frm, to, owners=None):
    """Events in [frm,to]. Activity is actor-attributed, exactly as the dashboard does it."""
    n = 0
    for r in rows:
        for day, actor in (r.get("m") or {}).get(metric, []):
            if frm <= day <= to and (owners is None or actor in owners):
                n += 1
    return n

def sprint_loc(frm, to):
    return sum(r.get("loc", 0) for r in rows
               if any(frm <= x <= to for x in (r.get("won_any") or []))) / 1e6

def working_days(frm, to):
    n, x = 0, datetime.date.fromisoformat(frm)
    end = datetime.date.fromisoformat(to)
    while x <= end:
        if x.weekday() < 5: n += 1
        x += datetime.timedelta(days=1)
    return max(1, n)

# ---------------------------------------------------------------- render
E = html.escape
TH = ("padding:7px 9px;background:#1447e6;color:#fff;font-size:11px;text-align:left;"
      "font-family:Arial,sans-serif;border:1px solid #1039b5")
TD = ("padding:7px 9px;border:1px solid #d8dee8;font-size:12px;"
      "font-family:Arial,sans-serif;vertical-align:top")
TB = "border-collapse:collapse;width:100%;margin:6px 0 22px"
H2 = ("font-family:Arial,sans-serif;font-size:14px;margin:26px 0 4px;color:#0b1220;"
      "border-left:4px solid #1447e6;padding-left:9px")

def pct_cell(got, want):
    if not want: return f'<td style="{TD}">—</td>'
    p = got / want * 100
    col = "#12803d" if p >= 100 else "#b06d00" if p >= 60 else "#b3261e"
    return (f'<td style="{TD};font-weight:700;color:{col}">{p:.1f}%</td>')

P = []
A = P.append
A(f'<div style="font-family:Arial,sans-serif;color:#0b1220;max-width:1000px">')
A(f'<p style="font-size:13px">Daily supply-funnel update — <b>{today.strftime("%d %b %Y")}</b>, '
  f'6:30 pm IST.</p>')
A(f'<p style="font-size:12px;color:#5b6472">Pulled from HubSpot. Every figure counts how many '
  f'deals <b>entered</b> a stage, credited to whoever made the move. Day = today; '
  f'week = Mon {monday.strftime("%d %b")} to today.</p>')

# --- 0. Funnel summary — the whole team, not per person ---
# 1-8 are the day. 9 is the week plus today's share. 10 is a snapshot of what is open right
# now, so it is neither daily nor weekly — it rises and falls as deals land or die.
def loc_closed(frm, to):
    return sum(r.get("loc", 0) for r in rows
               if any(frm <= x <= to for x in (r.get("won_any") or []))) / 1e6
loc_pipe = sum(r.get("loc", 0) for r in rows if not r.get("won") and not r.get("dead")) / 1e6

SUMMARY = [("No. of calls attempted",          count("att",  DAY, DAY), "today"),
           ("No. of calls connected",          count("conn", DAY, DAY), "today"),
           ("No. of VCs done",                 count("vc",   DAY, DAY), "today"),
           ("No. of scripts shared",           count("ss",   DAY, DAY), "today"),
           ("No. of script output received",   count("rr",   DAY, DAY), "today"),
           ("No. of commercial negotiation done", count("cn", DAY, DAY), "today"),
           ("No. of Deal Contract signed",     count("dcs",  DAY, DAY), "today"),
           ("No. of Closed/Won",               count("won_d", DAY, DAY), "today")]

A(f'<div style="{H2}">Funnel summary</div>')
A(f'<table style="{TB}"><tr><th style="{TH}">S.No.</th><th style="{TH}">Metric</th>'
  f'<th style="{TH}">Value</th><th style="{TH}">Period</th></tr>')
for i, (lbl, val, per) in enumerate(SUMMARY, 1):
    A(f'<tr><td style="{TD};text-align:center">{i}</td><td style="{TD}">{E(lbl)}</td>'
      f'<td style="{TD};font-weight:700;font-size:14px">{val}</td>'
      f'<td style="{TD};color:#8a94a6">{per}</td></tr>')
A(f'<tr><td style="{TD};text-align:center">9</td><td style="{TD}">No. of LoC closed</td>'
  f'<td style="{TD};font-weight:700;font-size:14px">{loc_closed(WK_FROM, WK_TO):.2f} Mn'
  f'<span style="font-weight:400;color:#5b6472"> &nbsp;· {loc_closed(DAY, DAY):.2f} Mn today</span></td>'
  f'<td style="{TD};color:#8a94a6">week to date</td></tr>')
A(f'<tr><td style="{TD};text-align:center">10</td><td style="{TD}">No. of LoC in pipeline</td>'
  f'<td style="{TD};font-weight:700;font-size:14px">{loc_pipe:.2f} Mn</td>'
  f'<td style="{TD};color:#8a94a6">open right now</td></tr>')
A('</table>')

# --- 1. Role definition, with today's numbers ---
A(f'<div style="{H2}">Role Definition — today</div>')
A(f'<table style="{TB}"><tr>'
  f'<th style="{TH}">S.No.</th><th style="{TH}">Team Structure</th><th style="{TH}">Current Team</th>'
  f'<th style="{TH}">Role Description</th><th style="{TH}">Input Matrix (today)</th>'
  f'<th style="{TH}">Outcome Matrix (today)</th></tr>')
for i, (role, person, oid, desc, inp, outp) in enumerate(ROLES, 1):
    who = [oid]
    fmt = lambda items: "<br>".join(
        f'{E(lbl)} — <b>{count(k, DAY, DAY, who)}</b>' for lbl, k in items)
    # merge the role cell down when the previous row is the same role
    span = sum(1 for x in ROLES if x[0] == role)
    first = ROLES[i-2][0] != role if i > 1 else True
    A(f'<tr><td style="{TD};text-align:center">{i}</td>'
      + (f'<td style="{TD}" rowspan="{span}"><b>{E(role)}</b></td>' if first else "")
      + f'<td style="{TD}"><b>{E(person)}</b></td>'
      + (f'<td style="{TD};color:#5b6472" rowspan="{span}">{E(desc)}</td>' if first else "")
      + f'<td style="{TD}">{fmt(inp)}</td><td style="{TD}">{fmt(outp)}</td></tr>')
A('</table>')

# --- 2. Individual targets ---
A(f'<div style="{H2}">Individual targets — achieved vs target</div>')
A(f'<table style="{TB}"><tr><th style="{TH}">S.No.</th><th style="{TH}">Team Member/s</th>'
  f'<th style="{TH}">Duration</th><th style="{TH}">Outcome Target</th>'
  f'<th style="{TH}">Achieved</th><th style="{TH}">Target</th><th style="{TH}">%</th></tr>')
n = 0
for member, oid, dur, items in TARGETS:
    n += 1
    for j, (lbl, k, per, cad) in enumerate(items):
        if cad == "daily":
            frm, to = DAY, DAY; want = per
        else:
            frm, to = WK_FROM, WK_TO
            want = round(per * (working_days(frm, to) / 5))
        got = count(k, frm, to, [oid])
        first = j == 0
        A(f'<tr>'
          + (f'<td style="{TD};text-align:center" rowspan="{len(items)}">{n}</td>'
             f'<td style="{TD}" rowspan="{len(items)}"><b>{E(member)}</b></td>'
             f'<td style="{TD}" rowspan="{len(items)}">{E(dur)}</td>' if first else "")
          + f'<td style="{TD}">{E(lbl)}</td>'
            f'<td style="{TD};font-weight:700">{got}</td><td style="{TD}">{want}</td>'
          + pct_cell(got, want) + '</tr>')
# Shobit's weekly target is the sprint volume, shown in full below.
n += 1
A(f'<tr><td style="{TD};text-align:center">{n}</td><td style="{TD}"><b>Shobit</b></td>'
  f'<td style="{TD}">Weekly</td>'
  f'<td style="{TD}">- Weekly Target Volume (LoC) with quality</td>'
  f'<td style="{TD}" colspan="3">see August Sprint Campaign below</td></tr>')
# Ashish's row is deliberately BLANK pending a decision on what belongs there. Shown rather
# than omitted so the row is visibly awaiting content instead of quietly missing.
n += 1
A(f'<tr><td style="{TD};text-align:center">{n}</td><td style="{TD}"><b>Ashish</b></td>'
  f'<td style="{TD}">Weekly</td>'
  f'<td style="{TD};color:#8a94a6" colspan="4">to be defined</td></tr>')
A('</table>')

# --- 3. August sprint ---
A(f'<div style="{H2}">August Sprint Campaign</div>')
A(f'<table style="{TB}"><tr><th style="{TH}">S.No.</th><th style="{TH}">Week</th>'
  f'<th style="{TH}">Target # of LoC (Mn)</th><th style="{TH}">Actual # of LoC procured</th>'
  f'<th style="{TH}">Achievement (%)</th></tr>')
gt = ga = 0
for num, lbl, frm, to, tgt in SPRINT:
    future = frm > DAY
    loc = 0 if future else sprint_loc(frm, to)
    live = frm <= DAY <= to
    bg = ';background:#eef2ff' if live else ''
    A(f'<tr><td style="{TD}{bg};text-align:center">{num}</td>'
      f'<td style="{TD}{bg}">{E(lbl)}{" <b>(this week)</b>" if live else ""}</td>'
      f'<td style="{TD}{bg}">{tgt}</td>'
      f'<td style="{TD}{bg}">{"—" if future else f"{loc:.2f}"}</td>'
      + (f'<td style="{TD}{bg};color:#8a94a6">not started</td>' if future
         else pct_cell(loc, tgt).replace(f'"{TD}', f'"{TD}{bg}')) + '</tr>')
    if not future: gt += tgt; ga += loc
A(f'<tr style="background:#f4f6fa;font-weight:700"><td style="{TD}"></td>'
  f'<td style="{TD}">To date</td><td style="{TD}">{gt}</td>'
  f'<td style="{TD}">{ga:.2f}</td>' + pct_cell(ga, gt) + '</tr>')
A('</table>')
A('<p style="font-size:11px;color:#8a94a6">Automated from HubSpot · '
  'definitions in docs/sop/DASHBOARD_METRIC_SPEC.md</p></div>')
HTML = "\n".join(P)

# plain-text fallback
TXT = [f"Daily supply-funnel update — {today.strftime('%d %b %Y')}, 6:30 pm IST", ""]
for role, person, oid, desc, inp, outp in ROLES:
    TXT.append(f"{role} — {person}")
    for lbl, k in inp + outp:
        TXT.append(f"   {lbl}: {count(k, DAY, DAY, [oid])}")
TXT.append("")
TXT.append("Funnel summary:")
for lbl, val, per in SUMMARY:
    TXT.append(f"   {lbl}: {val} ({per})")
TXT.append(f"   No. of LoC closed: {loc_closed(WK_FROM, WK_TO):.2f} Mn week to date "
           f"({loc_closed(DAY, DAY):.2f} Mn today)")
TXT.append(f"   No. of LoC in pipeline: {loc_pipe:.2f} Mn (open right now)")
TXT.append("")
TXT.append("August sprint:")
for num, lbl, frm, to, tgt in SPRINT:
    if frm > DAY: continue
    loc = sprint_loc(frm, to)
    TXT.append(f"   {lbl}: {loc:.2f} / {tgt} Mn ({loc/tgt*100:.1f}%)")
TEXT = "\n".join(TXT)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write(HTML)
print(TEXT)
print(f"\nwrote {OUT}")

if "--send" in sys.argv:
    if STALE and "--force" not in sys.argv:
        sys.exit(f"\nREFUSING TO SEND — data is from {GEN}, not {today}. "
                 f"Run build_dashboard.py first, or pass --force to send anyway.")
    to = TEST_TO if "--test" in sys.argv else TO
    if "--to" in sys.argv: to = sys.argv[sys.argv.index("--to") + 1]
    import gmail_sender
    subj = ("[TEST] " if "--test" in sys.argv else "") +            f"LH2 supply funnel — daily update {today.strftime('%d %b %Y')}"
    t, detail = gmail_sender.send(to, subj, TEXT, html=HTML)
    print(f"sent to {to} via [{t}] {detail}")
else:
    print("\nnot sent — pass --send")
