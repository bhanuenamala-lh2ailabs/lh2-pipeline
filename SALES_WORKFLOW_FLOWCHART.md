# Codebase Acquisition — Sales Workflow (start → end)

One diagram, every scenario. Renders automatically on GitHub. To get an image for
slides: copy the ```mermaid``` block into **https://mermaid.live** → Actions →
Export PNG/SVG.

**Legend:** 🔵 pipeline stage · 🟠 decision · 🔴 dead end · 🟡 won ·
**solid arrow** = normal path · **dotted arrow** = "they came back / picked up".
Outcomes ①–⑤ and their stage moves + tasks are **automated** by
`lh2 hubspot-call-outcome`; everything after the M1V1 email is a **manual** stage
move in HubSpot.

```mermaid
flowchart TD
    START(["🔄 Nightly pipeline sync<br/>Company + Contact + Deal created"]) --> NL["New Lead"]
    NL --> ASG["Assigned<br/>owner claims the lead"]
    ASG --> CALL{"📞 COLD CALL"}

    %% --- the 5 cold-call outcomes (automated by the CLI) ---
    CALL -->|"① Connected — Interested"| M1V1["M1V1 Sent<br/>task: Follow up +1d"]
    CALL -->|"② Connected — Rejected"| DR(["Dead — Rejected"])
    CALL -->|"③ Busy"| BUSY["Call Attempted<br/>task: Callback"]
    CALL -->|"④ Wrong Number"| WN["Call Attempted<br/>task: Apollo lookup"]
    CALL -->|"⑤ No Pickup"| NP1["M1V2 Sent<br/>task: Call again +1d"]

    %% --- retry loops ---
    BUSY -->|"call back at set time"| CALL
    WN -->|"fix number, retry"| CALL

    %% --- no-pickup escalation chain ---
    NP1 -->|"no pickup again"| NP2["M1V1 Sent (escalation)<br/>task: Final follow-up"]
    NP1 -.->|"they reply / pick up"| M1V1
    NP2 -->|"no pickup again"| DNR(["Dead — No Response"])
    NP2 -.->|"they reply / pick up"| M1V1

    %% --- post-call: email + meeting booking (manual) ---
    M1V1 --> EMAIL["Send M1V1 email<br/>with Calendly link"]
    EMAIL --> BOOK{"Meeting booked<br/>within 1 day?"}
    BOOK -->|"yes"| GS["GMEET1 Scheduled"]
    BOOK -->|"no"| AM["Awaiting Meeting<br/>owner pushes for booking"]
    AM --> PUSH{"Booked after push?"}
    PUSH -->|"yes"| GS
    PUSH -->|"no / refused"| DMR(["Dead — Meeting Rejected"])

    %% --- GMEET1 tech eval call (manual) ---
    GS --> GC["GMEET1 Completed<br/>tech eval call"]
    GC --> GO{"GMEET1 outcome"}
    GO -->|"O1 — runs script on call"| SR["Script Running"]
    GO -->|"O2 — will run later"| AR["Awaiting Results<br/>task: Follow up +2d"]
    SR --> RR["Results Received"]
    AR --> RR

    %% --- results + handoff ---
    RR --> RUR["Results Under Review<br/>handoff to ops/sales"]
    RUR --> WON(["🏆 Won"])
    RUR -.->|"not a fit"| DWF(["Dead — Wrong Fit"])

    %% --- styling ---
    classDef stage fill:#e8f0fe,stroke:#1a73e8,color:#0b1f44;
    classDef decision fill:#fef7e0,stroke:#f29900,color:#3d2c00;
    classDef dead fill:#fce8e6,stroke:#c5221f,color:#5c0f0a;
    classDef won fill:#fff2cc,stroke:#f9ab00,color:#4a3600;
    classDef start fill:#e6f4ea,stroke:#188038,color:#0b3d1a;

    class START start;
    class NL,ASG,M1V1,BUSY,WN,NP1,NP2,GS,AM,GC,SR,AR,RR,RUR stage;
    class CALL,BOOK,PUSH,GO decision;
    class DR,DNR,DMR,DWF dead;
    class WON won;
```

## The 5 cold-call outcomes at a glance (what the tool does for you)

| # | Situation | Deal moves to | Auto-task |
|---|---|---|---|
| **①** | Picked up, interested | **M1V1 Sent** | Follow up — no meeting booked (+1 day) |
| **②** | Picked up, hard rejection | **Dead — Rejected** | — (closed lost) |
| **③** | Picked up, busy | **Call Attempted** | Callback (at given time, else next day) |
| **④** | Wrong number | **Call Attempted** | Apollo lookup (today) → fix & retry |
| **⑤** | No pickup | **M1V2 Sent** → escalate → **Dead — No Response** | Call again → Final follow-up |

## Two nuances for the team
- **Escalation (⑤):** no-pickup once → M1V2 email; no-pickup again → M1V1 email
  (escalation); no-pickup a third time → Dead — No Response. If they reply/pick up
  at any point, you jump into the interested flow (M1V1 Sent).
- **Retries (③ ④):** Busy and Wrong-Number keep the deal alive in *Call Attempted* —
  you loop back and call again once the time comes / number is fixed.

> The pipeline also has two optional manual stages not shown as auto-steps —
> **Call Connected** (an intermediate you can use before M1V1) — the automated
> flow skips straight to *M1V1 Sent* on an interested call.
